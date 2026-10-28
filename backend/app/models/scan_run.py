from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.sql import func
import enum
from app.core.database import Base

class ScanStatus(enum.Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"

class ScanRun(Base):
    __tablename__ = "scan_runs"
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum(ScanStatus), nullable=False, default=ScanStatus.pending)
    folder = Column(String, default="INBOX")
    dry_run = Column(Boolean, default=True)
    emails_scanned = Column(Integer, default=0)
    emails_unsubscribed = Column(Integer, default=0)
    emails_failed = Column(Integer, default=0)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    error = Column(String)
    batch_size = Column(Integer)
    emails_found = Column(Integer, default=0)
    emails_known = Column(Integer, default=0)
    emails_no_link = Column(Integer, default=0)
    emails_spam = Column(Integer, default=0)
