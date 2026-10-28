from sqlalchemy import Column, String, Boolean
from app.core.database import Base

class AppSetting(Base):
    """Key/value overrides for .env defaults. Secret values are stored Fernet-encrypted."""
    __tablename__ = "app_settings"
    key = Column(String, primary_key=True)
    value = Column(String)
    encrypted = Column(Boolean, nullable=False, default=False)
