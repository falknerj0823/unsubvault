from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.sql import func
from app.core.database import Base

class SenderCheck(Base):
    """Cached domain-level facts (age, SPF, DMARC, mail provider). Public DNS/registry data only, no email content."""
    __tablename__ = "sender_checks"
    domain = Column(String, primary_key=True)
    checked_at = Column(DateTime, server_default=func.now())
    facts = Column(Text, nullable=False)  # JSON
