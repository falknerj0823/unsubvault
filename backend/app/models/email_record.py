from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.sql import func
import enum
from app.core.database import Base

class EmailAction(enum.Enum):
    none = "none"
    unsubscribed = "unsubscribed"
    unsubscribe_pending = "unsubscribe_pending"
    unsubscribe_failed = "unsubscribe_failed"
    archived = "archived"
    deleted = "deleted"
    labeled = "labeled"

class EmailRecord(Base):
    __tablename__ = "email_records"
    __table_args__ = (UniqueConstraint("account_id", "message_id", name="uq_account_message"),)
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    scan_run_id = Column(Integer, ForeignKey("scan_runs.id", ondelete="SET NULL"))
    message_id = Column(String)
    subject = Column(String)
    sender_name = Column(String)
    sender_email = Column(String)
    received_at = Column(DateTime)
    is_newsletter = Column(Boolean)
    is_promotional = Column(Boolean)
    confidence = Column(Float)
    category = Column(String)
    classification_reason = Column(String)
    action = Column(Enum(EmailAction), default=EmailAction.none)
    unsubscribe_url = Column(String)
    unsubscribe_method = Column(String)
    unsubscribe_one_click = Column(Boolean, default=False)
    unsubscribe_result = Column(String)
    unsubscribe_error = Column(String)
    unsubscribed_at = Column(DateTime)
    prior_category = Column(String)  # set while a safe-sender rule overrides the classification
    prior_action = Column(String)
    verify_verdict = Column(String)   # legitimate | unclear | suspicious (technical authenticity of the sender)
    verify_summary = Column(String)
    created_at = Column(DateTime, server_default=func.now())
