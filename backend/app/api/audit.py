import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.audit_event import AuditEvent

router = APIRouter()

@router.get("/")
def list_events(event_type: str | None = None, failures_only: bool = False,
                limit: int = Query(50, ge=1, le=200), before_id: int | None = None,
                db: Session = Depends(get_db)):
    """Newest first. Page with before_id = the smallest id from the previous page."""
    q = db.query(AuditEvent)
    if event_type:
        q = q.filter(AuditEvent.event_type == event_type)
    if failures_only:
        q = q.filter(AuditEvent.success.is_(False))
    if before_id:
        q = q.filter(AuditEvent.id < before_id)
    rows = q.order_by(AuditEvent.id.desc()).limit(limit + 1).all()
    return {"has_more": len(rows) > limit, "events": [
        {"id": r.id, "at": r.created_at.isoformat() + "Z", "type": r.event_type, "success": r.success,
         "actor": r.actor, "ip": r.ip, "detail": json.loads(r.detail) if r.detail else {}} for r in rows[:limit]]}

@router.get("/types")
def event_types(db: Session = Depends(get_db)):
    return sorted(t for (t,) in db.query(AuditEvent.event_type).distinct().all())
