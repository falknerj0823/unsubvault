from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Index
from sqlalchemy.sql import func
from app.core.database import Base

class AuditEvent(Base):
    """Append-only record of security-relevant actions. Never holds secrets or email content."""
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_created_at", "created_at"), Index("ix_audit_event_type", "event_type"))
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    event_type = Column(String, nullable=False)
    success = Column(Boolean, nullable=False, default=True)
    actor = Column(String, nullable=False, default="admin")
    ip = Column(String)
    detail = Column(Text)  # JSON object, values truncated, secret-looking keys dropped
