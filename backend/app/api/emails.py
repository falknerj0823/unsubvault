from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional
from app.core import audit
from app.core.database import get_db
from app.models.email_record import EmailRecord, EmailAction
from app.services.bulk_unsub import mark_safe
from app.services.domains import brand_mismatch, brand_tokens

router = APIRouter()

@router.get("/counts")
def counts(db: Session = Depends(get_db)):
    """Tab badges: pending / unsubscribed / failed / kept (not spam) / spam / all."""
    rows = db.query(EmailRecord.action, EmailRecord.category, func.count()).group_by(EmailRecord.action, EmailRecord.category).all()
    out = {"pending": 0, "unsubscribed": 0, "failed": 0, "kept": 0, "spam": 0, "all": 0}
    for action, category, n in rows:
        out["all"] += n
        if category == "spam":
            out["spam"] += n
        elif action == EmailAction.unsubscribe_pending:
            out["pending"] += n
        elif action == EmailAction.unsubscribed:
            out["unsubscribed"] += n
        elif action == EmailAction.unsubscribe_failed:
            out["failed"] += n
        else:
            out["kept"] += n
    return out

@router.get("/")
def list_emails(action: Optional[str] = Query(None), category: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(EmailRecord)
    if category == "!spam":
        q = q.filter((EmailRecord.category.is_(None)) | (EmailRecord.category != "spam"))
    elif category:
        q = q.filter(EmailRecord.category == category)
    if action:
        try:
            q = q.filter(EmailRecord.action == EmailAction(action))
        except ValueError:
            raise HTTPException(400, f"action must be one of {[a.value for a in EmailAction]}")
    records = q.order_by(EmailRecord.created_at.desc()).limit(200).all()
    return [{"id": r.id, "account_id": r.account_id, "brand_mismatch": brand_mismatch(r.sender_name, r.sender_email), "verify_verdict": r.verify_verdict, "verify_summary": r.verify_summary, "subject": r.subject, "sender_name": r.sender_name,
             "sender_email": r.sender_email, "action": r.action.value if r.action else "none",
             "confidence": r.confidence, "category": r.category, "classification_reason": r.classification_reason,
             "unsubscribe_url": r.unsubscribe_url, "unsubscribe_result": r.unsubscribe_result,
             "unsubscribe_error": r.unsubscribe_error} for r in records]


@router.post("/{email_id}/not-spam")
def not_spam(email_id: int, request: Request, db: Session = Depends(get_db)):
    """The model called this sender spam and it is not. Treat the sender as ordinary marketing from now on (it appears in
    the Review list), and remember the decision for future scans."""
    r = db.query(EmailRecord).filter(EmailRecord.id == email_id).first()
    if not r or r.category != "spam":
        raise HTTPException(404, "That email is not marked as spam.")
    if r.sender_email.startswith("@"):
        raise HTTPException(400, "That sender is stored by company only.")
    n = mark_safe(db, r.account_id, r.sender_email, r.sender_name, decision="not_spam")
    audit.record("marked_not_spam", request=request, detail={"domain": r.sender_email.rsplit("@", 1)[-1].lower(), "emails_relabelled": n})
    return {"emails": n}


@router.post("/{email_id}/verify")
async def verify_sender(email_id: int, request: Request, explain: bool = False, db: Session = Depends(get_db)):
    """Run the technical checks on this email's sender. Optionally ask the configured model to weigh the evidence
    (it sees only the domain and the technical facts, never the email)."""
    import asyncio
    from app.models.account import Account
    from app.models.scan_run import ScanRun
    from app.services import sender_check
    from app.services.domains import domain_of
    from app.services.scanner import _client_for
    r = db.query(EmailRecord).filter(EmailRecord.id == email_id).first()
    if not r:
        raise HTTPException(404, "No such email")
    domain = domain_of(r.sender_email)
    if not domain:
        raise HTTPException(400, "No sender domain stored for that email.")
    facts = await sender_check.domain_facts(db, domain)
    auth = history = None
    notes = []
    acct = db.query(Account).filter(Account.id == r.account_id).first()
    run = db.query(ScanRun).filter(ScanRun.id == r.scan_run_id).first() if r.scan_run_id else None
    if acct and run and r.message_id and not r.sender_email.startswith("@"):
        try:
            client = _client_for(acct, db)
            auth = sender_check.parse_auth(await asyncio.to_thread(client.read_auth_results, run.folder or "INBOX", r.message_id))
            tokens = brand_tokens(r.sender_name)
            if tokens:
                history = await asyncio.to_thread(client.sender_history, tokens)
        except Exception as e:  # the domain checks are still useful without the mailbox
            notes.append(f"Mailbox checks skipped: {str(e)[:120]}")
    result = sender_check.evaluate(domain, r.sender_name, r.sender_email, facts, auth, history)
    for rec in db.query(EmailRecord).filter(EmailRecord.account_id == r.account_id, EmailRecord.sender_email == r.sender_email).all():
        rec.verify_verdict, rec.verify_summary = result["verdict"], result["summary"]
    db.commit()
    out = {**result, "domain": domain, "facts": facts, "history": history or [], "notes": notes,
           "caveat": "Authentic means the sender is who its domain says. It does not prove the domain belongs to the brand named in the sender name, and it does not mean you want the mail."}
    if explain:
        try:
            out["explanation"] = await sender_check.explain({"sender_name": r.sender_name, "sender_domain": domain, "facts": facts, "signature": auth,
                                                            "mailbox_history": history, "technical_verdict": result["verdict"], "checks": result["reasons"]})
        except Exception as e:
            out["explanation_error"] = str(e)[:200]
    audit.record("sender_verified", request=request, detail={"domain": domain, "verdict": result["verdict"], "model_explained": explain})
    return out
