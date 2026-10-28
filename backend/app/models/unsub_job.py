from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class UnsubJob(Base):
    """A bulk unsubscribe run over a chosen set of senders."""
    __tablename__ = "unsub_jobs"
    id = Column(Integer, primary_key=True)
    status = Column(String, nullable=False, default="pending")  # pending | running | complete | failed
    dry_run = Column(Boolean, nullable=False, default=True)
    selection = Column(Text, nullable=False)  # JSON [[account_id, sender_email], ...]
    total = Column(Integer, default=0)
    done = Column(Integer, default=0)
    confirmed = Column(Integer, default=0)
    unverified = Column(Integer, default=0)
    manual = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    simulated = Column(Integer, default=0)
    error = Column(String)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
