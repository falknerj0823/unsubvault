import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core import app_settings, audit
from app.core.database import get_db
from app.core.timeutil import iso_utc
from app.models.unsub_job import UnsubJob
from app.core.timeutil import iso_utc
from app.models.sender_rule import SenderRule
from app.services.bulk_unsub import mark_safe, run_job, sender_groups, undo_safe

router = APIRouter()

class SenderRef(BaseModel):
    account_id: int
    sender_email: str

class BulkRequest(BaseModel):
    senders: list[SenderRef] = Field(min_length=1, max_length=500)
    dry_run: bool = True

def _job(j: UnsubJob) -> dict:
    return {"id": j.id, "status": j.status, "dry_run": j.dry_run, "total": j.total, "done": j.done,
            "confirmed": j.confirmed, "unverified": j.unverified, "manual": j.manual, "failed": j.failed,
            "simulated": j.simulated, "error": j.error, "started_at": iso_utc(j.started_at),
            "completed_at": iso_utc(j.completed_at)}

def start_job(db: Session, background: BackgroundTasks, request: Request, senders: list[tuple[int, str]], dry_run_requested: bool) -> UnsubJob:
    """The server-side dry-run setting can force dry-run on; a request can never force it off."""
    dry_run = bool(app_settings.get("dry_run") or dry_run_requested)
    running = db.query(UnsubJob).filter(UnsubJob.status.in_(["pending", "running"])).first()
    if running:
        raise HTTPException(409, "Another bulk unsubscribe is still running. Wait for it to finish.")
    job = UnsubJob(status="pending", dry_run=dry_run, selection=json.dumps([[a, s.lower()] for a, s in senders]), total=len(senders))
    db.add(job); db.commit(); db.refresh(job)
    audit.record("bulk_unsubscribe_started", request=request, detail={
        "job_id": job.id, "senders": len(senders), "dry_run": dry_run,
        "dry_run_forced_by_server": bool(app_settings.get("dry_run") and not dry_run_requested)})
    background.add_task(run_job, job.id)
    return job

@router.get("/senders")
def senders(db: Session = Depends(get_db)):
    return {"dry_run": bool(app_settings.get("dry_run")), "senders": sender_groups(db)}

@router.post("/bulk")
def bulk(body: BulkRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    job = start_job(db, background, request, [(s.account_id, s.sender_email) for s in body.senders], body.dry_run)
    return _job(job)

@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(UnsubJob).filter(UnsubJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "No such job")
    return _job(job)


class KeepRequest(BaseModel):
    senders: list[SenderRef] = Field(min_length=1, max_length=200)

@router.post("/keep")
def keep(body: KeepRequest, request: Request, db: Session = Depends(get_db)):
    """Mark senders as safe: never spam, never offered for unsubscribe, not sent to the LLM again."""
    changed = 0
    for s in body.senders:
        if s.sender_email.startswith("@"):
            raise HTTPException(400, "That sender is stored by company only and cannot be marked safe.")
        changed += mark_safe(db, s.account_id, s.sender_email)
    audit.record("safe_sender_added", request=request, detail={"senders": len(body.senders), "emails_relabelled": changed,
                                                               "domains": sorted({s.sender_email.rsplit("@", 1)[-1].lower() for s in body.senders})[:20]})
    return {"senders": len(body.senders), "emails": changed}

@router.get("/keep")
def list_keep(db: Session = Depends(get_db)):
    rules = db.query(SenderRule).order_by(SenderRule.id.desc()).all()
    return [{"id": r.id, "account_id": r.account_id, "decision": r.decision, "sender_email": r.sender_email, "sender_name": r.sender_name, "created_at": iso_utc(r.created_at)} for r in rules]

@router.delete("/keep/{rule_id}")
def undo_keep(rule_id: int, request: Request, db: Session = Depends(get_db)):
    rule = db.query(SenderRule).filter(SenderRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "No such rule")
    domain = rule.sender_email.rsplit("@", 1)[-1]
    restored = undo_safe(db, rule)
    audit.record("safe_sender_removed", request=request, detail={"domain": domain, "emails_restored": restored})
    return {"restored": restored}


class DoneRequest(BaseModel):
    senders: list[SenderRef] = Field(min_length=1, max_length=200)

@router.post("/mark-done")
def mark_done(body: DoneRequest, request: Request, db: Session = Depends(get_db)):
    """You unsubscribed yourself (opened the sender's page or sent the email). Record it so the sender leaves the queue."""
    from datetime import datetime
    from sqlalchemy import func
    from app.models.email_record import EmailAction, EmailRecord
    n = 0
    for s in body.senders:
        recs = db.query(EmailRecord).filter(EmailRecord.account_id == s.account_id, func.lower(EmailRecord.sender_email) == s.sender_email.lower(),
                                            EmailRecord.action == EmailAction.unsubscribe_pending).all()
        for r in recs:
            r.action, r.unsubscribe_result, r.unsubscribe_method, r.unsubscribed_at = EmailAction.unsubscribed, "manual_done", "manual", datetime.utcnow()
        n += len(recs)
    db.commit()
    audit.record("unsubscribe_marked_done", request=request, detail={"senders": len(body.senders), "emails": n,
                                                                      "domains": sorted({s.sender_email.rsplit("@", 1)[-1].lower() for s in body.senders})[:20]})
    return {"emails": n}
