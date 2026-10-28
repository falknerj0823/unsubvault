from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.sql import func
import enum
from app.core.database import Base

class ProviderType(enum.Enum):
    microsoft = "microsoft"
    google = "google"
    imap = "imap"

class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    label = Column(String, nullable=False)
    provider_type = Column(Enum(ProviderType), nullable=False)
    email_address = Column(String)
    access_token = Column(String)
    refresh_token = Column(String)
    token_expires_at = Column(DateTime)
    imap_host = Column(String)
    imap_port = Column(Integer)
    imap_username = Column(String)
    imap_password_encrypted = Column(String)
    created_at = Column(DateTime, server_default=func.now())
