"""Bulk unsubscribe: one request per sender, result applied to every pending email from that sender."""
import asyncio, json, logging
from collections import Counter
from datetime import datetime
from urllib.parse import urlsplit
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core import audit
from app.core.database import SessionLocal
from app.models.email_record import EmailAction, EmailRecord
from app.core.timeutil import iso_utc
from app.models.sender_rule import SenderRule
from app.models.unsub_job import UnsubJob
from app.services.domains import brand_mismatch, root_domain
from app.services.unsubscriber import pick_target, unsubscribe

log = logging.getLogger(__name__)
DELAY_BETWEEN_SENDERS = 1.0  # be polite, and never hammer one host
MAX_GROUP_ROWS = 5000

def _target(records: list[EmailRecord]) -> tuple[str | None, str | None, bool]:
    """Best (https_url, mailto, one_click) for a sender, preferring a one-click link."""
    best = None
    for r in sorted(records, key=lambda r: (not r.unsubscribe_one_click, -(r.confidence or 0))):
        url, mailto = pick_target(r.unsubscribe_url and f"<{r.unsubscribe_url}>")
        if url:
            return url, None, bool(r.unsubscribe_one_click)
        best = best or mailto
    return None, best, False

def sender_groups(db: Session) -> list[dict]:
    """Pending senders for the review screen."""
    recs = (db.query(EmailRecord).filter(EmailRecord.action == EmailAction.unsubscribe_pending)
            .order_by(EmailRecord.id.desc()).limit(MAX_GROUP_ROWS).all())
    # Companies we also get receipts / account / personal mail from: unsubscribing there risks missing real notices.
    account_mail = Counter(root_domain(a) for (a,) in db.query(EmailRecord.sender_email)
                           .filter(EmailRecord.category.in_(["transactional", "personal"])).all())
    groups: dict[tuple[int, str], list[EmailRecord]] = {}
    for r in recs:
        groups.setdefault((r.account_id, (r.sender_email or "").lower()), []).append(r)
    out = []
    for (account_id, sender), rs in groups.items():
        url, mailto, one_click = _target(rs)
        best = max(rs, key=lambda r: r.confidence or 0)
        out.append({
            "account_id": account_id, "sender_email": sender, "sender_name": rs[0].sender_name,
            "email_count": len(rs), "confidence": round(sum(r.confidence or 0 for r in rs) / len(rs), 2),
            "category": Counter(r.category for r in rs).most_common(1)[0][0],
            "reason": best.classification_reason,
            "samples": [{"subject": r.subject, "received_at": iso_utc(r.received_at)} for r in rs[:5]],
            "sample_subject": rs[0].subject,
            "mixed_count": account_mail.get(root_domain(sender), 0),
            "brand_mismatch": brand_mismatch(rs[0].sender_name, sender),
            "verify_verdict": next((r.verify_verdict for r in rs if r.verify_verdict), None),
            "verify_summary": next((r.verify_summary for r in rs if r.verify_summary), None),
            "record_id": rs[0].id,
            "method": "one_click" if one_click else "web_link" if url else "mailto" if mailto else "none",
            "target": url or mailto,
            "last_result": next((r.unsubscribe_result for r in rs if r.unsubscribe_result), None),
        })
    return sorted(out, key=lambda g: (-g["email_count"], g["sender_email"]))

def mark_safe(db: Session, account_id: int, sender: str, name: str | None = None, decision: str = "keep") -> int:
    """Create a standing rule for a sender and relabel what is already stored. Returns emails changed.
    decision "keep": never spam, never offered for unsubscribe. decision "not_spam": the model got it wrong; treat it as
    ordinary marketing so it appears in the Review list."""
    sender = sender.lower()
    rule = db.query(SenderRule).filter(SenderRule.account_id == account_id, SenderRule.sender_email == sender).first()
    if rule and rule.decision != decision:
        undo_safe(db, rule)  # switching decisions: restore first, then apply the new one
        rule = None
    if not rule:
        db.add(SenderRule(account_id=account_id, sender_email=sender, decision=decision, sender_name=name))
    q = db.query(EmailRecord).filter(EmailRecord.account_id == account_id, func.lower(EmailRecord.sender_email) == sender)
    if decision == "keep":
        recs = q.filter(EmailRecord.category != "kept", EmailRecord.action.in_([EmailAction.unsubscribe_pending, EmailAction.none])).all()
    else:
        recs = q.filter(EmailRecord.category == "spam").all()
    for r in recs:
        r.prior_category, r.prior_action = r.category, r.action.value
        if decision == "keep":
            r.category, r.action = "kept", EmailAction.none
            r.is_newsletter = r.is_promotional = False
            r.unsubscribe_method = "kept_by_rule"
        else:
            r.category, r.is_promotional = "promotional", True
            r.action = EmailAction.unsubscribe_pending if r.unsubscribe_url else EmailAction.none
            r.unsubscribe_method = "not_spam_by_rule"
    db.commit()
    return len(recs)

def undo_safe(db: Session, rule: SenderRule) -> int:
    """Remove the rule and restore what it overrode (mail stored after the rule was made has nothing to restore)."""
    recs = db.query(EmailRecord).filter(EmailRecord.account_id == rule.account_id, func.lower(EmailRecord.sender_email) == rule.sender_email,
                                        EmailRecord.unsubscribe_method.in_(["kept_by_rule", "not_spam_by_rule"]),
                                        EmailRecord.prior_category.isnot(None)).all()
    for r in recs:
        r.category, r.action = r.prior_category, EmailAction(r.prior_action or "none")
        r.is_newsletter, r.is_promotional = r.category == "newsletter", r.category == "promotional"
        r.unsubscribe_method = "pending_review" if r.action == EmailAction.unsubscribe_pending else "spam_skipped" if r.category == "spam" else "restored"
        r.prior_category = r.prior_action = None
    db.delete(rule)
    db.commit()
    return len(recs)

def _apply(rs: list[EmailRecord], result, dry_run: bool):
    now = datetime.utcnow()
    for r in rs:
        r.unsubscribe_result, r.unsubscribe_method, r.unsubscribe_error = result.status, result.method, (result.error or None)
        if result.status in ("confirmed", "sent_unverified"):
            r.action, r.unsubscribed_at = EmailAction.unsubscribed, now
        elif result.status == "failed":
            r.action = EmailAction.unsubscribe_failed
        # manual and dry_run leave the email pending so it can be retried or handled by hand

async def _run(job_id: int):
    db = SessionLocal()
    job = db.query(UnsubJob).filter(UnsubJob.id == job_id).first()
    try:
        job.status = "running"; db.commit()
        selection = json.loads(job.selection)
        job.total = len(selection); db.commit()
        for i, (account_id, sender) in enumerate(selection):
            rs = (db.query(EmailRecord).filter(EmailRecord.account_id == account_id,
                  func.lower(EmailRecord.sender_email) == sender, EmailRecord.action == EmailAction.unsubscribe_pending).all())
            if rs:
                url, mailto, one_click = _target(rs)
                result = await unsubscribe(url, mailto, one_click, dry_run=job.dry_run)
                _apply(rs, result, job.dry_run)
                bucket = {"confirmed": "confirmed", "sent_unverified": "unverified", "manual": "manual",
                          "failed": "failed", "dry_run": "simulated"}[result.status]
                setattr(job, bucket, getattr(job, bucket) + 1)
                # audit the outcome per sender; log the host only, since unsubscribe URLs often carry personal tokens
                audit.record("unsubscribe_attempt", success=result.status != "failed", actor="system", detail={
                    "job_id": job.id, "sender": sender, "emails": len(rs), "result": result.status, "method": result.method,
                    "host": urlsplit(url).hostname if url else None, "error": result.error})
            job.done = i + 1; db.commit()
            if not job.dry_run and rs and i < len(selection) - 1:
                await asyncio.sleep(DELAY_BETWEEN_SENDERS)
        job.status = "complete"; job.completed_at = datetime.utcnow(); db.commit()
        audit.record("bulk_unsubscribe_completed", actor="system", detail={
            "job_id": job.id, "dry_run": job.dry_run, "senders": job.total, "confirmed": job.confirmed,
            "unverified": job.unverified, "manual": job.manual, "failed": job.failed, "simulated": job.simulated})
    except Exception as e:
        db.rollback()
        log.exception("Bulk unsubscribe job %s failed", job_id)
        job = db.query(UnsubJob).filter(UnsubJob.id == job_id).first()
        job.status, job.error, job.completed_at = "failed", f"Stopped unexpectedly: {type(e).__name__}", datetime.utcnow(); db.commit()
        audit.record("bulk_unsubscribe_completed", success=False, actor="system", detail={"job_id": job_id, "error": type(e).__name__})
    finally:
        db.close()

def run_job(job_id: int):
    """Entry point for FastAPI BackgroundTasks."""
    asyncio.run(_run(job_id))
