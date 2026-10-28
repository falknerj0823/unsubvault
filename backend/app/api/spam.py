import re
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core import app_settings, audit
from app.core.database import get_db
from app.models.account import Account
from app.models.email_record import EmailRecord
from app.models.scan_run import ScanRun
from app.services.scanner import ScanError, _client_for, _friendly_imap_error

router = APIRouter()
MAX_PER_CALL = 100
_JUNK_LIKE = re.compile(r"junk|spam|bulk|trash|deleted", re.I)

def _candidates(db: Session):
    """Spam that sits in a normal folder (not already Junk/Trash) and has not been moved yet."""
    rows = (db.query(EmailRecord, ScanRun.folder).join(ScanRun, EmailRecord.scan_run_id == ScanRun.id)
            .filter(EmailRecord.category == "spam", EmailRecord.unsubscribe_method == "spam_skipped").order_by(EmailRecord.id.desc()).all())
    return [(r, folder) for r, folder in rows if folder and not _JUNK_LIKE.search(folder) and r.message_id]

@router.get("/candidates")
def candidates(db: Session = Depends(get_db)):
    items = [{"id": r.id, "account_id": r.account_id, "folder": folder, "sender_name": r.sender_name, "sender_email": r.sender_email, "subject": r.subject}
             for r, folder in _candidates(db)]
    return {"dry_run": bool(app_settings.get("dry_run")), "count": len(items), "items": items[:MAX_PER_CALL], "more": max(0, len(items) - MAX_PER_CALL)}

class MoveRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_PER_CALL)

@router.post("/move")
def move(body: MoveRequest, request: Request, db: Session = Depends(get_db)):
    """Move chosen spam to Junk. The server-side dry-run setting forces a read-only check instead of a move."""
    dry_run = bool(app_settings.get("dry_run"))
    wanted = set(body.ids)
    groups: dict[tuple[int, str], list[EmailRecord]] = {}
    for r, folder in _candidates(db):
        if r.id in wanted:
            groups.setdefault((r.account_id, folder), []).append(r)
    if not groups:
        raise HTTPException(400, "None of those messages can be moved (already moved, or not spam in a normal folder).")
    moved = found = missing = 0
    junk_names: set[str] = set()
    for (account_id, folder), records in groups.items():
        acct = db.query(Account).filter(Account.id == account_id).first()
        if not acct:
            continue
        try:
            res = _client_for(acct, db).move_to_junk(folder, [r.message_id for r in records], dry_run=dry_run)
        except ScanError as e:
            raise HTTPException(400, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, _friendly_imap_error(e))
        junk_names.add(res["junk_folder"])
        ok, gone = set(res["found"]), set(res["missing"])
        found += len(ok); missing += len(gone)
        for r in records:
            if r.message_id in gone:
                r.unsubscribe_method = "not_in_folder"
            elif r.message_id in ok and not dry_run:
                r.unsubscribe_method, r.unsubscribe_result = "moved_to_junk", "moved"
                moved += 1
        db.commit()
    audit.record("spam_moved_to_junk", request=request, detail={"dry_run": dry_run, "requested": len(body.ids), "found": found,
                                                                "moved": moved, "not_found": missing})
    return {"dry_run": dry_run, "found": found, "moved": moved, "not_found": missing, "junk_folder": sorted(junk_names)[0] if junk_names else None}
