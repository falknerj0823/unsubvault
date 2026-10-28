from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func
from app.core.database import Base

class RegistryBroker(Base):
    """A data broker from California's public registry. Text fields are untrusted: show them as plain text."""
    __tablename__ = "registry_brokers"
    id = Column(String, primary_key=True)  # sha1(lowercased name)[:12]
    name = Column(String, nullable=False)
    website = Column(String)
    email = Column(String)
    optout_text = Column(Text)
    date_added = Column(String)
    fingerprint = Column(String, nullable=False)
    first_seen_sync = Column(Integer, nullable=False, default=0)  # 0 = present at the first (baseline) sync
    changed_sync = Column(Integer)
    removed_sync = Column(Integer)
    first_seen_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime)

class RegistrySync(Base):
    __tablename__ = "registry_syncs"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, server_default=func.now())
    total = Column(Integer, default=0)
    new = Column(Integer, default=0)
    changed = Column(Integer, default=0)
    removed = Column(Integer, default=0)
    baseline = Column(Integer, default=0)  # 1 for the first sync: nothing is "new" yet

class LinkCheck(Base):
    __tablename__ = "link_checks"
    broker_id = Column(String, primary_key=True)
    checked_at = Column(DateTime, nullable=False)
    state = Column(String, nullable=False)  # ok | moved | blocked | broken
    http_status = Column(Integer)
    final_url = Column(String)
    note = Column(String)
