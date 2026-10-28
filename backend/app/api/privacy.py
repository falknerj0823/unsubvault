import json
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core import app_settings, audit
from app.core.crypto import decrypt, encrypt
from app.core.database import get_db
from app.core.timeutil import iso_utc
from app.models.account import Account
from app.models.broker_status import BrokerStatus
from app.models.registry import LinkCheck, RegistryBroker, RegistrySync
from app.services import linkcheck, registry
from app.services.scanner import ScanError, _client_for, _friendly_imap_error

router = APIRouter()
_CATALOG = json.loads((Path(__file__).resolve().parent.parent / "data" / "brokers.json").read_text())
BROKERS = {b["id"]: b for b in _CATALOG["brokers"]}
STATUSES = ("not_started", "requested", "confirmed", "relisted")
PROFILE_KEY = "privacy_profile"

def _search_domain(b: dict) -> str | None:
    return b["sender_domains"][0] if b["category"] in ("people_search", "marketing_data") and b["sender_domains"] else None

def _row(b: dict, st: BrokerStatus | None, link: LinkCheck | None = None) -> dict:
    status = st.status if st else "not_started"
    due = bool(st and st.status == "confirmed" and st.confirmed_at and
               st.confirmed_at < datetime.utcnow() - timedelta(days=30 * b["recheck_months"]))
    return {**{k: b[k] for k in ("id", "name", "category", "method", "url", "notes", "recheck_months")},
            "search_domain": _search_domain(b),
            "link_state": link.state if link else ("blocked" if b["link_check"] == "blocks_bots" else "ok"),
            "link_note": link.note if link else None, "link_checked_at": iso_utc(link.checked_at) if link else None,
            "link_moved_to": link.final_url if link and link.state == "moved" else None,
            "status": status, "requested_at": iso_utc(st.requested_at) if st else None,
            "confirmed_at": iso_utc(st.confirmed_at) if st else None, "recheck_due": due}

@router.get("/brokers")
def brokers(db: Session = Depends(get_db)):
    states = {s.broker_id: s for s in db.query(BrokerStatus).all()}
    links = {l.broker_id: l for l in db.query(LinkCheck).all()}
    last = linkcheck.last_run(db)
    return {"links_checked_at": iso_utc(last) or _CATALOG["checked_at"], "links_live": last is not None, "links_running": linkcheck.is_running(),
            "brokers": [_row(b, states.get(b["id"]), links.get(b["id"])) for b in _CATALOG["brokers"]]}

class StatusIn(BaseModel):
    status: str

def _apply_status(st: BrokerStatus, status: str):
    now = datetime.utcnow()
    st.status = status
    if status == "requested":
        st.requested_at, st.confirmed_at = now, None
    elif status == "confirmed":
        st.requested_at = st.requested_at or now
        st.confirmed_at = now
    elif status == "not_started":
        st.requested_at = st.confirmed_at = None

@router.put("/brokers/{broker_id}")
def set_status(broker_id: str, body: StatusIn, request: Request, db: Session = Depends(get_db)):
    is_registry = broker_id.startswith("reg:")
    if is_registry:
        if not db.query(RegistryBroker).filter(RegistryBroker.id == broker_id[4:]).first():
            raise HTTPException(404, "Unknown broker")
    elif broker_id not in BROKERS:
        raise HTTPException(404, "Unknown broker")
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    st = db.query(BrokerStatus).filter(BrokerStatus.broker_id == broker_id).first() or BrokerStatus(broker_id=broker_id)
    _apply_status(st, body.status)
    db.add(st); db.commit()
    audit.record("broker_status_changed", request=request, detail={"broker": broker_id, "status": body.status})
    return {"id": broker_id, "status": st.status, "requested_at": iso_utc(st.requested_at), "confirmed_at": iso_utc(st.confirmed_at)} if is_registry \
        else _row(BROKERS[broker_id], st, db.query(LinkCheck).filter(LinkCheck.broker_id == broker_id).first())

# ---------------------------------------------------------------- link health
@router.post("/links/check")
async def check_links(request: Request, background: BackgroundTasks):
    if linkcheck.is_running():
        raise HTTPException(409, "A link check is already running.")
    background.add_task(linkcheck.check_all, _CATALOG["brokers"])
    audit.record("broker_links_check_started", request=request, detail={"links": len(_CATALOG["brokers"])})
    return {"started": True, "links": len(_CATALOG["brokers"])}

# ---------------------------------------------------------------- California registry
def _reg_item(r: RegistryBroker, st: BrokerStatus | None, last_sync_id: int | None) -> dict:
    return {"id": f"reg:{r.id}", "name": r.name, "website": r.website, "website_https": bool(r.website and r.website.lower().startswith("https://")),
            "email": r.email, "optout_text": r.optout_text, "date_added": r.date_added,
            "search_domain": registry.website_host(r.website),
            "is_new": bool(last_sync_id and r.first_seen_sync == last_sync_id), "is_changed": bool(last_sync_id and r.changed_sync == last_sync_id),
            "is_removed": r.removed_sync is not None, "status": st.status if st else "not_started"}

@router.post("/registry/sync")
async def sync_registry(request: Request, db: Session = Depends(get_db)):
    try:
        summary = await registry.sync_now(db)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Could not download the registry ({type(e).__name__}).")
    audit.record("registry_synced", request=request, detail={k: summary[k] for k in ("total", "new", "changed", "removed", "baseline")})
    return summary

@router.get("/registry")
def list_registry(q: str = "", filter: str = Query("all", pattern="^(all|new|changed|removed|tracked)$"),
                  limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    last = db.query(RegistrySync).order_by(RegistrySync.id.desc()).first()
    states = {s.broker_id: s for s in db.query(BrokerStatus).filter(BrokerStatus.broker_id.like("reg:%")).all()}
    query = db.query(RegistryBroker)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        from sqlalchemy import func, or_
        query = query.filter(or_(func.lower(RegistryBroker.name).like(like), func.lower(RegistryBroker.website).like(like)))
    sid = last.id if last else None
    if filter == "new":
        query = query.filter(RegistryBroker.first_seen_sync == sid)
    elif filter == "changed":
        query = query.filter(RegistryBroker.changed_sync == sid)
    elif filter == "removed":
        query = query.filter(RegistryBroker.removed_sync.isnot(None))
    elif filter == "tracked":
        query = query.filter(RegistryBroker.id.in_([k[4:] for k, s in states.items() if s.status != "not_started"]))
    else:
        query = query.filter(RegistryBroker.removed_sync.is_(None))
    total = query.count()
    rows = query.order_by(RegistryBroker.name).offset(offset).limit(limit).all()
    return {"synced": bool(last), "last_sync": {"at": iso_utc(last.at), "total": last.total, "new": last.new, "changed": last.changed,
                                               "removed": last.removed, "baseline": bool(last.baseline)} if last else None,
            "total": total, "has_more": offset + limit < total, "items": [_reg_item(r, states.get(f"reg:{r.id}"), sid) for r in rows]}

# ---------------------------------------------------------------- profile (encrypted at rest, used only to build search links)
class Profile(BaseModel):
    full_name: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=2)
    also_known_as: list[str] = Field(default_factory=list, max_length=5)

def _load_profile() -> dict:
    raw = app_settings.get_internal(PROFILE_KEY)
    empty = {"full_name": "", "city": "", "state": "", "also_known_as": []}
    if not raw:
        return empty
    try:
        return json.loads(decrypt(raw))
    except ValueError:  # SECRET_KEY changed
        return empty

@router.get("/profile")
def get_profile():
    return _load_profile()

@router.put("/profile")
def put_profile(body: Profile, request: Request):
    clean = {"full_name": body.full_name.strip(), "city": body.city.strip(), "state": body.state.strip().upper(),
             "also_known_as": [n.strip()[:120] for n in body.also_known_as if n.strip()][:5]}
    if clean["state"] and not (len(clean["state"]) == 2 and clean["state"].isalpha()):
        raise HTTPException(400, "State must be a two-letter code, like CA.")
    app_settings.set_internal(PROFILE_KEY, encrypt(json.dumps(clean)))
    audit.record("privacy_profile_saved", request=request, detail={"has_name": bool(clean["full_name"]), "has_city": bool(clean["city"]),
                                                                   "has_state": bool(clean["state"]), "other_names": len(clean["also_known_as"])})
    return clean

@router.delete("/profile")
def delete_profile(request: Request):
    app_settings.set_internal(PROFILE_KEY, "")
    audit.record("privacy_profile_deleted", request=request)
    return {"ok": True}

# ---------------------------------------------------------------- mailbox assist
class MailCheck(BaseModel):
    account_id: int
    days: int = 45

@router.post("/check-mailbox")
def check_mailbox(body: MailCheck, request: Request, db: Session = Depends(get_db)):
    """Read-only look for recent mail from the brokers' domains (headers only). Shows whether your mail provider
    verified each sender, so a fake 'confirm your removal' email is easier to spot. Links are never extracted."""
    acct = db.query(Account).filter(Account.id == body.account_id).first()
    if not acct:
        raise HTTPException(404, "No such account")
    domains = sorted({d for b in BROKERS.values() for d in b["sender_domains"]})
    try:
        msgs = _client_for(acct, db).find_mail_from(domains, max(1, min(body.days, 365)))
    except ScanError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, _friendly_imap_error(e))
    grouped: dict[str, list[dict]] = {}
    for m in msgs:
        sender_domain = m["from"].rsplit("@", 1)[-1]
        for b in BROKERS.values():
            match = next((d for d in b["sender_domains"] if sender_domain == d or sender_domain.endswith("." + d)), None)
            if match:
                dk = m["dkim_domain"]
                grouped.setdefault(b["id"], []).append({**m, "verified": bool(dk and (dk == match or dk.endswith("." + match) or match.endswith("." + dk)))})
                break
    audit.record("broker_mailbox_checked", request=request, detail={"days": body.days, "messages": len(msgs), "brokers": len(grouped)})
    return {"days": body.days, "messages": len(msgs), "by_broker": grouped}
