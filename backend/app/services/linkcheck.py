"""Is each catalog link still alive? Uses the same SSRF-safe fetcher, sends no personal data, and says honestly
when a site blocks automated checks instead of guessing."""
import asyncio, logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit
import httpx
from sqlalchemy.orm import Session
from app.core import app_settings
from app.core.database import SessionLocal
from app.models.registry import LinkCheck
from app.services.safe_http import UnsafeURL, safe_request

log = logging.getLogger(__name__)
DELAY = 1.0
RECHECK_AFTER = timedelta(days=7)
_running = False

def _norm(url: str) -> tuple[str, str]:
    p = urlsplit(url)
    return (p.hostname or "").removeprefix("www."), p.path.rstrip("/")

def classify(status: int | None, original: str, final: str | None, error: str | None = None) -> tuple[str, str]:
    """-> (state, note). states: ok, moved, blocked, broken"""
    if error:
        return "broken", error
    if status in (403, 429, 503, 520, 521, 522, 523, 524, 999):
        return "blocked", "The site blocks automated checks, so this link could not be verified."
    if status is not None and 200 <= status < 300:
        if final and _norm(final) != _norm(original):
            return "moved", f"Redirects to {urlsplit(final).hostname}{urlsplit(final).path}"
        return "ok", "Loads normally."
    if status in (404, 410):
        return "broken", f"The page is gone (HTTP {status})."
    return "broken", f"The site answered HTTP {status}."

async def check_one(url: str) -> tuple[str, int | None, str | None, str]:
    try:
        status, final = await safe_request("GET", url)
        state, note = classify(status, url, final)
        return state, status, final, note
    except UnsafeURL as e:
        return "broken", None, None, f"Blocked for safety: {e}"
    except httpx.HTTPError as e:
        state, note = classify(None, url, None, f"Could not connect ({type(e).__name__}).")
        return state, None, None, note

async def check_all(catalog: list[dict]) -> dict:
    global _running
    if _running:
        return {"running": True}
    _running = True
    counts = {"ok": 0, "moved": 0, "blocked": 0, "broken": 0}
    try:
        for i, b in enumerate(catalog):
            state, status, final, note = await check_one(b["url"])
            db = SessionLocal()
            try:
                row = db.query(LinkCheck).filter(LinkCheck.broker_id == b["id"]).first() or LinkCheck(broker_id=b["id"])
                row.checked_at, row.state, row.http_status, row.final_url, row.note = datetime.utcnow(), state, status, final if state == "moved" else None, note[:300]
                db.add(row); db.commit()
            finally:
                db.close()
            counts[state] += 1
            if i < len(catalog) - 1:
                await asyncio.sleep(DELAY)
    finally:
        _running = False
    return counts

def is_running() -> bool:
    return _running

def last_run(db: Session) -> datetime | None:
    row = db.query(LinkCheck).order_by(LinkCheck.checked_at.desc()).first()
    return row.checked_at if row else None

async def weekly_loop(catalog: list[dict]):
    """Started at app startup. Only does anything when the user turned on automatic link checks (off by default, because it
    contacts data broker sites from this machine). Re-checks when the last run is older than a week."""
    while True:
        try:
            if not app_settings.get("auto_link_check"):
                await asyncio.sleep(3600)
                continue
            db = SessionLocal()
            try:
                due = (last := last_run(db)) is None or datetime.utcnow() - last > RECHECK_AFTER
            finally:
                db.close()
            if due:
                await check_all(catalog)
        except Exception:
            log.exception("Weekly link check failed")
        await asyncio.sleep(3600)
