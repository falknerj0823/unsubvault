from fastapi import APIRouter, Depends, HTTPException, Request
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core import app_settings, audit
from app.core.crypto import encrypt
from app.core.database import get_db
from app.models.llm_config import LLMProfile
from app.services.llm import PROVIDERS, DEFAULT_MODELS, LLMSettings, complete, list_models, load_llm_settings, load_profiles

router = APIRouter()
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

class LLMConfigIn(BaseModel):
    provider: str
    model: str = ""
    base_url: str = ""
    api_key: str | None = None  # None = keep stored key, "" = clear it

def _public() -> dict:
    active = load_llm_settings()
    profiles = {name: {"model": p.model, "base_url": p.base_url, "api_key_set": bool(p.api_key)}
                for name, p in load_profiles().items()}
    profiles.setdefault(active.provider, {"model": active.model, "base_url": active.base_url, "api_key_set": bool(active.api_key)})
    return {"active": active.provider, "profiles": profiles, "providers": PROVIDERS, "default_models": DEFAULT_MODELS}

@router.get("/")
def get_settings():
    return {"llm_provider": load_llm_settings().provider, "dry_run": app_settings.get("dry_run"),
            "scan_batch_size": app_settings.get("scan_batch_size"), "frontend_url": app_settings.get("frontend_url"),
            "scan_retention_days": app_settings.get("scan_retention_days"), "auto_verify": app_settings.get("auto_verify"), "auto_link_check": app_settings.get("auto_link_check"),
            "timezone": app_settings.get("timezone")}

class AppSettingsIn(BaseModel):
    dry_run: bool | None = None
    scan_batch_size: int | None = Field(default=None, ge=1, le=1000)
    frontend_url: str | None = None
    timezone: str | None = None  # IANA name; empty = use the browser's
    scan_retention_days: int | None = Field(default=None, ge=0, le=3650)  # 0 = keep forever
    auto_verify: bool | None = None
    auto_link_check: bool | None = None
    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None  # None = keep, "" = clear
    microsoft_tenant: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None

@router.get("/app")
def get_app_settings():
    return app_settings.get_public()

@router.put("/app")
def put_app_settings(body: AppSettingsIn, request: Request):
    values = body.model_dump()
    url = values.get("frontend_url")
    if url is not None and not url.startswith(("http://", "https://")):
        raise HTTPException(400, "frontend_url must start with http:// or https://")
    tz = values.get("timezone")
    if tz:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(400, f"'{tz}' is not a known timezone (use a name like America/Los_Angeles)")
    secret = values.get("microsoft_client_secret")
    if secret and _GUID.match(secret.strip()):
        raise HTTPException(400, "That looks like the Azure Secret ID (a GUID). Copy the secret's Value column instead; "
                                 "if you didn't copy it when it was created, make a new secret.")
    app_settings.update(values)
    changed = [k for k, v in values.items() if v is not None]
    audit.record("settings_changed", request=request, detail={
        "fields": changed, **{k: values[k] for k in ("dry_run", "scan_batch_size", "frontend_url", "timezone", "scan_retention_days", "auto_verify", "auto_link_check") if values.get(k) is not None}})
    return app_settings.get_public()

@router.get("/llm")
def get_llm():
    return _public()

@router.put("/llm")
def put_llm(body: LLMConfigIn, request: Request, db: Session = Depends(get_db)):
    """Save this provider's profile and make it the active one. Other providers' profiles are untouched."""
    if body.provider not in PROVIDERS:
        raise HTTPException(400, f"provider must be one of {PROVIDERS}")
    row = db.query(LLMProfile).filter(LLMProfile.provider == body.provider).first() or LLMProfile(provider=body.provider)
    url = body.base_url.strip()
    if (row.base_url or "") != url and body.api_key is None:
        row.api_key_encrypted = None  # a saved key must never follow a changed endpoint
    row.model, row.base_url = body.model.strip(), url
    if body.api_key is not None:
        row.api_key_encrypted = encrypt(body.api_key) if body.api_key else None
    db.add(row); db.commit()
    app_settings.set_internal("llm_active_provider", body.provider)
    audit.record("llm_config_changed", request=request, detail={
        "provider": body.provider, "model": body.model.strip(), "base_url": url,
        "api_key_changed": body.api_key is not None and body.api_key != "", "api_key_removed": body.api_key == ""})
    return _public()

def _resolve(body: LLMConfigIn) -> LLMSettings:
    """Form values without saving; a blank key reuses the stored one only for the same provider+URL."""
    stored = load_profiles().get(body.provider)
    if stored is None:
        active = load_llm_settings()  # may be the .env fallback
        stored = active if active.provider == body.provider else None
    same_target = stored is not None and stored.base_url == body.base_url.strip()
    key = body.api_key if body.api_key is not None else (stored.api_key if same_target else "")
    return LLMSettings(body.provider, body.model.strip(), body.base_url.strip(), key)

@router.post("/llm/models")
async def llm_models(body: LLMConfigIn):
    try:
        return {"ok": True, "models": await list_models(_resolve(body))}
    except Exception as e:
        return {"ok": False, "models": [], "error": str(e)[:300]}

@router.post("/llm/test")
async def test_llm(body: LLMConfigIn, request: Request):
    try:
        reply = await complete("Reply with exactly: ok", "ping", _resolve(body))
        audit.record("llm_test", request=request, detail={"provider": body.provider, "model": body.model})
        return {"ok": True, "reply": reply.strip()[:200]}
    except Exception as e:
        audit.record("llm_test", success=False, request=request, detail={"provider": body.provider, "model": body.model, "error": str(e)[:200]})
        return {"ok": False, "error": str(e)[:500]}


@router.delete("/data/scan")
def delete_scan_data(request: Request, db: Session = Depends(get_db)):
    """Wipe stored scan results and history. Accounts, settings, safe-sender rules and the audit log are kept."""
    from app.models.email_record import EmailRecord
    from app.models.scan_run import ScanRun
    from app.models.unsub_job import UnsubJob
    emails = db.query(EmailRecord).delete(synchronize_session=False)
    runs = db.query(ScanRun).delete(synchronize_session=False)
    jobs = db.query(UnsubJob).filter(UnsubJob.status.notin_(["pending", "running"])).delete(synchronize_session=False)
    db.commit()
    audit.record("scan_data_deleted", request=request, detail={"emails": emails, "scans": runs, "unsubscribe_runs": jobs})
    return {"emails": emails, "scans": runs, "unsubscribe_runs": jobs}
