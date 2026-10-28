"""Runtime-editable settings: DB value wins, .env value is the default."""
from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.database import SessionLocal
from app.models.app_setting import AppSetting

# key -> (type, is_secret)
FIELDS: dict[str, tuple[type, bool]] = {
    "dry_run": (bool, False),
    "scan_batch_size": (int, False),
    "frontend_url": (str, False),
    "timezone": (str, False),
    "scan_retention_days": (int, False),
    "auto_verify": (bool, False),
    "auto_link_check": (bool, False),
    "microsoft_client_id": (str, False),
    "microsoft_client_secret": (str, True),
    "microsoft_tenant": (str, False),
    "google_client_id": (str, False),
    "google_client_secret": (str, True),
}

def _parse(raw: str, typ: type):
    if typ is bool:
        return raw == "true"
    return typ(raw)

def get(key: str):
    typ, _ = FIELDS[key]
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row is not None and row.value is not None:
            try:
                return _parse(decrypt(row.value) if row.encrypted else row.value, typ)
            except ValueError:
                pass  # SECRET_KEY changed: fall back to the default so the page still loads and the value can be re-entered
    finally:
        db.close()
    return getattr(settings, key)

def get_public() -> dict:
    """Everything the UI may see: secrets are reported as '<key>_set' booleans, never returned."""
    out: dict = {}
    for key, (_, secret) in FIELDS.items():
        value = get(key)
        if secret:
            out[f"{key}_set"] = bool(value)
        else:
            out[key] = value
    return out

def update(values: dict) -> None:
    """Secrets: None = keep stored value, '' = clear it. Non-secrets: None = keep."""
    db = SessionLocal()
    try:
        for key, value in values.items():
            if key not in FIELDS or value is None:
                continue
            typ, secret = FIELDS[key]
            row = db.query(AppSetting).filter(AppSetting.key == key).first() or AppSetting(key=key)
            if secret and value == "":
                row.value, row.encrypted = None, False
            else:
                text = ("true" if value else "false") if typ is bool else str(typ(value)).strip()
                row.value, row.encrypted = (encrypt(text) if secret else text), secret
            db.add(row)
        db.commit()
    finally:
        db.close()

def get_internal(key: str) -> str | None:
    """Unexposed bookkeeping values (password hash, session version)."""
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        return row.value if row else None
    finally:
        db.close()

def set_internal(key: str, value: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first() or AppSetting(key=key, encrypted=False)
        row.value = value
        db.add(row); db.commit()
    finally:
        db.close()
