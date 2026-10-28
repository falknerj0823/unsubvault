from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class BrokerStatus(Base):
    """Which data brokers you have handled. Holds no personal details, only broker ids, status and dates."""
    __tablename__ = "broker_status"
    broker_id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="not_started")  # not_started | requested | confirmed | relisted
    requested_at = Column(DateTime)
    confirmed_at = Column(DateTime)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
