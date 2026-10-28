from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class LLMProfile(Base):
    """One saved configuration per provider; which one is active lives in app_settings (llm_active_provider)."""
    __tablename__ = "llm_profiles"
    provider = Column(String, primary_key=True)
    model = Column(String)
    base_url = Column(String)
    api_key_encrypted = Column(String)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
