"""Audit trail. record() never raises: a logging failure must not break the action being logged."""
import ipaddress, json, logging
from datetime import datetime, timedelta
from fastapi import Request
from app.core.database import SessionLocal
from app.models.audit_event import AuditEvent

log = logging.getLogger(__name__)

RETENTION_DAYS = 180
_SECRET_HINTS = ("password", "secret", "token", "key", "code", "authorization", "cookie")

def client_ip(request: Request | None) -> str | None:
    """Best effort. nginx (a private Docker address) sets X-Real-IP; a header from anywhere else is ignored."""
    if request is None:
        return None
    host = request.client.host if request.client else None
    try:
        if host and ipaddress.ip_address(host).is_private:
            return request.headers.get("x-real-ip") or host
    except ValueError:
        pass
    return host

def _clean(detail: dict | None) -> str | None:
    if not detail:
        return None
    out = {}
    for k, v in detail.items():
        if any(h in k.lower() for h in _SECRET_HINTS) and not isinstance(v, bool):
            continue  # booleans like api_key_changed are fine; values never are
        if isinstance(v, (list, tuple)):
            v = [str(x)[:80] for x in v][:20]
        elif isinstance(v, (int, float, bool)) or v is None:
            pass
        else:
            v = str(v)[:300]
        out[k] = v
    return json.dumps(out)

def record(event_type: str, *, success: bool = True, request: Request | None = None,
           actor: str = "admin", detail: dict | None = None) -> None:
    try:
        db = SessionLocal()
        try:
            db.add(AuditEvent(event_type=event_type, success=success, actor=actor,
                              ip=client_ip(request), detail=_clean(detail)))
            db.commit()
        finally:
            db.close()
    except Exception:
        log.exception("Could not write audit event %s", event_type)

def prune() -> int:
    """Drop events older than the retention window. Called at startup."""
    try:
        db = SessionLocal()
        try:
            n = db.query(AuditEvent).filter(AuditEvent.created_at < datetime.utcnow() - timedelta(days=RETENTION_DAYS)).delete()
            db.commit()
            return n
        finally:
            db.close()
    except Exception:
        log.exception("Audit prune failed")
        return 0
