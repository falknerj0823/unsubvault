from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from app.core.database import Base

class SenderRule(Base):
    """A standing decision about a sender, so it is not offered again. Currently only 'keep'."""
    __tablename__ = "sender_rules"
    __table_args__ = (UniqueConstraint("account_id", "sender_email", name="uq_rule_account_sender"),)
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    sender_email = Column(String, nullable=False)  # lowercase
    decision = Column(String, nullable=False, default="keep")
    sender_name = Column(String)  # display only
    created_at = Column(DateTime, server_default=func.now())
