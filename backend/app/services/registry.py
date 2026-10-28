"""Sync California's public data broker registry. Everything in it is untrusted text supplied by the brokers."""
import asyncio, csv, hashlib, io, re
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from sqlalchemy.orm import Session
from app.models.registry import RegistryBroker, RegistrySync
from app.services.safe_http import UnsafeURL, safe_get_bytes

REGISTRY_URL = "https://cppa.ca.gov/data_broker_registry/complete-reg-data-brokers.csv"
MIN_SYNC_INTERVAL = timedelta(minutes=10)
RETRY_WAIT = 8
MAX_TEXT = 3000
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def _clean(value: str | None, limit: int = MAX_TEXT) -> str:
    return _CTRL.sub("", (value or "")).strip()[:limit]

def _col(row: dict, *needles: str) -> str:
    for k, v in row.items():
        if all(n in (k or "").lower() for n in needles):
            return v or ""
    return ""

def broker_id(name: str) -> str:
    return hashlib.sha1(name.strip().lower().encode()).hexdigest()[:12]

def parse(data: bytes) -> list[dict]:
    """CSV bytes -> unique brokers (the last row wins when a name repeats)."""
    text = data.decode("utf-8-sig", errors="replace")
    out: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        name = _clean(_col(row, "broker", "name"), 200)
        if not name:
            continue
        email = _clean(_col(row, "email"), 200).replace(" [at] ", "@").replace("[at]", "@")
        out[broker_id(name)] = {"id": broker_id(name), "name": name, "website": _clean(_col(row, "website"), 300),
                                "email": email, "optout_text": _clean(_col(row, "consumer", "opt out")),
                                "date_added": _clean(_col(row, "date added"), 40)}
    for b in out.values():
        b["fingerprint"] = hashlib.sha1("|".join((b["website"], b["email"], b["optout_text"])).encode()).hexdigest()
    return list(out.values())

def apply(db: Session, brokers: list[dict]) -> dict:
    """Upsert and diff against what is stored. The first sync is a baseline: nothing counts as new."""
    last = db.query(RegistrySync).order_by(RegistrySync.id.desc()).first()
    sync = RegistrySync(total=len(brokers), baseline=0 if last else 1)
    db.add(sync); db.flush()
    now = datetime.utcnow()
    existing = {b.id: b for b in db.query(RegistryBroker).all()}
    new = changed = 0
    seen = set()
    for b in brokers:
        seen.add(b["id"])
        row = existing.get(b["id"])
        if row is None:
            db.add(RegistryBroker(first_seen_sync=0 if sync.baseline else sync.id, last_seen_at=now, **b))
            new += 0 if sync.baseline else 1
            continue
        if row.fingerprint != b["fingerprint"]:
            row.website, row.email, row.optout_text, row.fingerprint = b["website"], b["email"], b["optout_text"], b["fingerprint"]
            row.changed_sync = sync.id
            changed += 1
        row.name, row.date_added, row.last_seen_at, row.removed_sync = b["name"], b["date_added"], now, None
    removed = 0
    for rid, row in existing.items():
        if rid not in seen and row.removed_sync is None:
            row.removed_sync = sync.id
            removed += 1
    sync.new, sync.changed, sync.removed = new, changed, removed
    db.commit()
    return {"id": sync.id, "total": len(brokers), "new": new, "changed": changed, "removed": removed, "baseline": bool(sync.baseline)}

async def sync_now(db: Session) -> dict:
    last = db.query(RegistrySync).order_by(RegistrySync.id.desc()).first()
    if last and last.at and datetime.utcnow() - last.at < MIN_SYNC_INTERVAL:
        raise ValueError("The registry was synced a few minutes ago. Try again later.")
    try:
        status, data = await safe_get_bytes(REGISTRY_URL, max_bytes=5_000_000)
        if status in (429, 503):  # the state's site throttles quick repeat requests: wait once, then try again
            await asyncio.sleep(RETRY_WAIT)
            status, data = await safe_get_bytes(REGISTRY_URL, max_bytes=5_000_000)
    except UnsafeURL as e:
        raise ValueError(f"Blocked for safety: {e}")
    if status != 200 or not data:
        raise ValueError(f"The registry site answered HTTP {status}.")
    brokers = parse(data)
    if len(brokers) < 50:  # a truncated or changed file must not mark everything as removed
        raise ValueError(f"The registry file looked wrong ({len(brokers)} brokers), so nothing was changed.")
    return apply(db, brokers)

def website_host(website: str | None) -> str | None:
    try:
        return (urlsplit(website or "").hostname or "").removeprefix("www.") or None
    except ValueError:
        return None
