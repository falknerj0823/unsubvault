"""Scan pipeline: IMAP (read-only) -> classify with the configured LLM -> store for review.
Only mail with a List-Unsubscribe header is classified (it is the only mail that can be unsubscribed from,
and it keeps everything else off the LLM). Nothing is unsubscribed here: that stays a manual approval."""
import asyncio, logging
from datetime import datetime, timedelta
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core import app_settings, audit
from app.core.crypto import decrypt, encrypt
from app.core.database import SessionLocal
from app.models.account import Account, ProviderType
from app.models.email_record import EmailRecord, EmailAction
from app.models.scan_run import ScanRun, ScanStatus
from app.models.sender_rule import SenderRule
from app.services import oauth_microsoft
from app.services.classifier import classify_email
from app.services.imap_client import IMAPClient, RawEmail
from app.services import sender_check
from app.services.domains import brand_mismatch, domain_of, minimized_sender
from app.services.unsubscriber import pick_target

log = logging.getLogger(__name__)
MAX_CONSECUTIVE_LLM_ERRORS = 3

def _reviewable(result: dict, is_spam: bool) -> bool:
    """Only mail that is actually marketing is offered for unsubscribe. Receipts, account notices and
    personal mail are never offered, even if the model also ticked a newsletter/promotional flag."""
    if is_spam or str(result.get("category", "")).lower() in ("transactional", "personal"):
        return False
    return bool(result.get("is_newsletter") or result.get("is_promotional"))

def purge_old_records(db: Session) -> int:
    """Retention: delete stored detail older than the configured number of days (0 = keep). Mail still waiting for you is never
    purged: that means unsubscribe candidates, spam waiting to be moved to Junk, and failed unsubscribes you may retry."""
    days = int(app_settings.get("scan_retention_days") or 0)
    if days <= 0:
        return 0
    n = (db.query(EmailRecord).filter(EmailRecord.action.notin_([EmailAction.unsubscribe_pending, EmailAction.unsubscribe_failed]),
         or_(EmailRecord.unsubscribe_method.is_(None), EmailRecord.unsubscribe_method != "spam_skipped"),  # NULL != x is not true in SQL
         EmailRecord.created_at < datetime.utcnow() - timedelta(days=days)).delete(synchronize_session=False))
    db.commit()
    if n:
        audit.record("scan_data_purged", actor="system", detail={"deleted": n, "older_than_days": days})
    return n

def recover_interrupted() -> dict:
    """Called at startup: a restart kills background work, so anything still 'running' will never finish."""
    from app.models.unsub_job import UnsubJob
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        scans = db.query(ScanRun).filter(ScanRun.status.in_([ScanStatus.pending, ScanStatus.running])).all()
        for r in scans:
            r.status, r.completed_at = ScanStatus.failed, now
            r.error = "Interrupted: the app restarted during this scan. Start it again; emails already stored are skipped."
        jobs = db.query(UnsubJob).filter(UnsubJob.status.in_(["pending", "running"])).all()
        for j in jobs:
            j.status, j.completed_at = "failed", now
            j.error = "Interrupted: the app restarted during this run. Senders already done are not repeated; start it again for the rest."
        db.commit()
        return {"scans": len(scans), "unsubscribe_jobs": len(jobs)}
    finally:
        db.close()

class ScanError(Exception):
    """A failure whose message is safe and useful to show the user."""

def _microsoft_access_token(acct: Account, db: Session) -> str:
    if acct.access_token and acct.token_expires_at and acct.token_expires_at > datetime.utcnow() + timedelta(seconds=120):
        return decrypt(acct.access_token)
    if not acct.refresh_token:
        raise ScanError("The Microsoft sign-in expired and no refresh token is stored. Remove the account and connect it again.")
    if not oauth_microsoft.is_configured():
        raise ScanError("The Microsoft sign-in expired and the app's client secret is missing. Re-enter it on the Accounts page, then try again.")
    result = oauth_microsoft.refresh_token(decrypt(acct.refresh_token))
    if "access_token" not in result:
        raise ScanError(f"Microsoft refused to renew the sign-in ({result.get('error', 'unknown')}). Remove the account and connect it again.")
    acct.access_token = encrypt(result["access_token"])
    if result.get("refresh_token"):
        acct.refresh_token = encrypt(result["refresh_token"])
    acct.token_expires_at = datetime.utcnow() + timedelta(seconds=int(result.get("expires_in", 3600)))
    db.commit()
    return result["access_token"]

def _client_for(acct: Account, db: Session) -> IMAPClient:
    try:
        return _client_for_unchecked(acct, db)
    except ValueError as e:
        if "Cannot decrypt" in str(e):
            raise ScanError("The stored sign-in for this account can't be read (SECRET_KEY changed?). Remove the account and add it again.")
        raise

def _client_for_unchecked(acct: Account, db: Session) -> IMAPClient:
    if acct.provider_type == ProviderType.microsoft:
        return IMAPClient(acct.imap_host, acct.imap_port or 993, acct.imap_username, access_token=_microsoft_access_token(acct, db))
    if acct.provider_type == ProviderType.imap:
        return IMAPClient(acct.imap_host, acct.imap_port or 993, acct.imap_username, password=decrypt(acct.imap_password_encrypted))
    raise ScanError(f"Scanning {acct.provider_type.value} accounts is not supported yet.")

def _friendly_imap_error(e: Exception) -> str:
    text = str(e)
    if "AUTHENTICATIONFAILED" in text.upper() or "LOGIN failed" in text or "authenticate" in text.lower():
        return "The mail server rejected the login. For IMAP accounts check the app password; for Microsoft, reconnect the account."
    return f"Could not read the mailbox: {text[:200]}"

async def _scan(run_id: int):
    db = SessionLocal()
    run = db.query(ScanRun).filter(ScanRun.id == run_id).first()
    try:
        run.status = ScanStatus.running; db.commit()
        acct = db.query(Account).filter(Account.id == run.account_id).first()
        if not acct:
            raise ScanError("That account no longer exists.")
        client = _client_for(acct, db)
        limit = max(1, min(int(run.batch_size or app_settings.get("scan_batch_size")), 1000))
        found = skipped_known = consecutive_errors = 0
        rules = db.query(SenderRule).filter(SenderRule.account_id == acct.id).all()
        keep_rules = {r.sender_email for r in rules if r.decision == "keep"}
        not_spam_rules = {r.sender_email for r in rules if r.decision == "not_spam"}
        auto_verify = bool(app_settings.get("auto_verify"))
        for raw in client.fetch_emails(run.folder or "INBOX", limit):
            run.emails_scanned += 1
            if not raw.list_unsubscribe:
                run.emails_no_link += 1; db.commit(); continue
            message_id = raw.message_id or f"<no-id-{run.folder}-{raw.uid}>"
            if db.query(EmailRecord.id).filter(EmailRecord.account_id == acct.id, EmailRecord.message_id == message_id).first():
                skipped_known += 1; run.emails_known += 1; db.commit(); continue
            if (raw.sender_email or "").lower() in keep_rules:  # standing decision: no LLM call, nothing stored beyond the company
                db.add(EmailRecord(account_id=acct.id, scan_run_id=run.id, message_id=message_id, sender_email=minimized_sender(raw.sender_email),
                                   received_at=raw.received_at, is_newsletter=False, is_promotional=False, confidence=1.0, category="kept",
                                   action=EmailAction.none, unsubscribe_method="kept_by_rule"))
                db.commit(); continue
            result = await classify_email(raw.subject, f"{raw.sender_name} <{raw.sender_email}>", raw.snippet)
            if result.get("error"):
                run.emails_failed += 1
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_LLM_ERRORS:
                    db.commit()  # keep this failure's counters; the except block rolls back anything uncommitted
                    raise ScanError(f"The LLM is not responding correctly, so the scan stopped. Last error: {result['error'][:200]}")
                db.commit(); continue
            consecutive_errors = 0
            is_spam = bool(result.get("is_spam")) or str(result.get("category", "")).lower() == "spam"
            if is_spam and (raw.sender_email or "").lower() in not_spam_rules:  # you told us this sender is not spam
                is_spam = False
                result = {**result, "category": "promotional", "is_promotional": True, "is_spam": False}
            https_url, mailto = pick_target(raw.list_unsubscribe)
            one_click = bool(https_url and raw.list_unsubscribe_post and "one-click" in raw.list_unsubscribe_post.lower())
            category = "spam" if is_spam else str(result.get("category", "other"))[:50]
            verdict = None
            if auto_verify and (is_spam or brand_mismatch(raw.sender_name, raw.sender_email)):
                try:  # DNS and registry lookups only; the scan never fails because of them
                    facts = await sender_check.domain_facts(db, domain_of(raw.sender_email))
                    verdict = sender_check.evaluate(domain_of(raw.sender_email), raw.sender_name, raw.sender_email, facts, sender_check.parse_auth(raw.auth_results), None)
                except Exception:
                    log.exception("Automatic sender verification failed")
            # Receipts, account notices and personal mail are never offered for unsubscribe, so keep only the company
            # (enough to warn about mixed senders) and none of the subject, name or the model's description of the mail.
            minimal = category.lower() in ("transactional", "personal")
            db.add(EmailRecord(
                account_id=acct.id, scan_run_id=run.id, message_id=message_id,
                subject=None if minimal else raw.subject[:500],
                sender_name=None if minimal else raw.sender_name[:200],
                sender_email=minimized_sender(raw.sender_email) if minimal else raw.sender_email[:200], received_at=raw.received_at,
                is_newsletter=bool(result.get("is_newsletter")) and not is_spam, is_promotional=bool(result.get("is_promotional")) and not is_spam,
                confidence=float(result.get("confidence") or 0), category=category,
                classification_reason=None if minimal else str(result.get("reason", ""))[:500],
                action=EmailAction.unsubscribe_pending if _reviewable(result, is_spam) else EmailAction.none,
                unsubscribe_url=None if minimal else (https_url or mailto), unsubscribe_one_click=False if minimal else one_click,
                unsubscribe_method="spam_skipped" if is_spam else "minimized" if minimal else "pending_review",
                verify_verdict=verdict["verdict"] if verdict else None, verify_summary=verdict["summary"] if verdict else None))
            if is_spam:
                run.emails_spam += 1
            else:
                found += 1; run.emails_found += 1
            db.commit()
        run.status = ScanStatus.complete; run.completed_at = datetime.utcnow(); db.commit()
        purge_old_records(db)
        audit.record("scan_completed", actor="system", detail={
            "run_id": run.id, "scanned": run.emails_scanned, "classified": found,
            "already_known": skipped_known, "spam": run.emails_spam, "llm_failures": run.emails_failed})
    except Exception as e:
        db.rollback()
        message = str(e) if isinstance(e, ScanError) else _friendly_imap_error(e)
        if not isinstance(e, ScanError):
            log.exception("Scan %s failed", run_id)
        run = db.query(ScanRun).filter(ScanRun.id == run_id).first()
        run.status = ScanStatus.failed; run.error = message[:500]; run.completed_at = datetime.utcnow(); db.commit()
        audit.record("scan_failed", success=False, actor="system", detail={"run_id": run_id, "error": message[:300]})
    finally:
        db.close()

def run_scan(run_id: int):
    """Entry point for FastAPI BackgroundTasks (runs in a worker thread)."""
    asyncio.run(_scan(run_id))
