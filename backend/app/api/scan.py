from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core import app_settings, audit
from app.core.database import get_db
from sqlalchemy import func
from app.models.email_record import EmailRecord
from app.core.timeutil import iso_utc
from app.models.scan_run import ScanRun, ScanStatus
from app.services.scanner import run_scan

router = APIRouter()

class ScanRequest(BaseModel):
    account_id: int
    folder: str = "INBOX"
    batch_size: int = 50
    dry_run: bool = True

@router.post("/start")
def start_scan(body: ScanRequest, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if db.query(ScanRun).filter(ScanRun.account_id == body.account_id, ScanRun.status.in_([ScanStatus.pending, ScanStatus.running])).first():
        raise HTTPException(409, "A scan of this account is already running.")
    run = ScanRun(account_id=body.account_id, folder=body.folder, batch_size=max(1, min(body.batch_size, 1000)),
                  dry_run=app_settings.get("dry_run") or body.dry_run, status=ScanStatus.pending)
    db.add(run); db.commit(); db.refresh(run)
    audit.record("scan_started", request=request, detail={"run_id": run.id, "account_id": body.account_id, "folder": body.folder, "dry_run": run.dry_run, "dry_run_forced_by_server": bool(app_settings.get("dry_run") and not body.dry_run)})
    background_tasks.add_task(run_scan, run.id)
    return {"run_id": run.id}

@router.get("/runs")
def list_runs(db: Session = Depends(get_db)):
    runs = db.query(ScanRun).order_by(ScanRun.id.desc()).limit(100).all()
    # Counts come from what is actually stored, so cards stay correct after reclassification or cleanup.
    by_run: dict[int, dict[str, int]] = {}
    for run_id, category, n in (db.query(EmailRecord.scan_run_id, EmailRecord.category, func.count())
                                .filter(EmailRecord.scan_run_id.in_([r.id for r in runs]))
                                .group_by(EmailRecord.scan_run_id, EmailRecord.category).all()):
        by_run.setdefault(run_id, {})[category or "other"] = n

    def tally(run_id: int) -> tuple[int, int, int]:
        c = by_run.get(run_id, {})
        review = c.get("newsletter", 0) + c.get("promotional", 0)
        spam = c.get("spam", 0)
        return review, spam, sum(c.values()) - review - spam

    return [{"id": r.id, "account_id": r.account_id, "status": r.status.value, "folder": r.folder, "batch_size": r.batch_size,
             "dry_run": r.dry_run, "emails_scanned": r.emails_scanned, "emails_found": tally(r.id)[0],
             "emails_known": r.emails_known or 0, "emails_spam": tally(r.id)[1], "emails_kept": tally(r.id)[2], "emails_no_link": r.emails_no_link or 0, "emails_failed": r.emails_failed,
             "error": r.error, "started_at": iso_utc(r.started_at), "completed_at": iso_utc(r.completed_at)} for r in runs]
