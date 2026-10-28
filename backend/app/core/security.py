import base64, hashlib, hmac, logging, os, time
from fastapi import Cookie, HTTPException
from app.core import app_settings
from app.core.crypto import derive_key
from app.core.config import settings

log = logging.getLogger(__name__)
COOKIE_NAME = "unsubvault_session"
SESSION_TTL = 60 * 60 * 24 * 7
MIN_PASSWORD_LEN = 8

def _sign(payload: str) -> str:
    return hmac.new(derive_key(b"session"), payload.encode(), hashlib.sha256).hexdigest()

def _session_version() -> str:
    return app_settings.get_internal("session_version") or "0"

def make_session_token() -> str:
    payload = f"{int(time.time()) + SESSION_TTL}:{_session_version()}"
    return base64.urlsafe_b64encode(f"{payload}.{_sign(payload)}".encode()).decode()

def verify_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        payload, sig = base64.urlsafe_b64decode(token.encode()).decode().rsplit(".", 1)
        expires, version = payload.split(":", 1)
        return (hmac.compare_digest(sig, _sign(payload)) and int(expires) > time.time()
                and hmac.compare_digest(version, _session_version()))
    except Exception:
        return False

SCRYPT_LOG_N = 15  # N = 2**15 (about 32 MB of memory per login attempt)

def _hash_password(password: str, salt: bytes, log_n: int = SCRYPT_LOG_N) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** log_n, r=8, p=1, maxmem=128 * 1024 * 1024).hex()

def check_admin_password(candidate: str) -> bool:
    """A password set from the UI (hashed in the DB) overrides ADMIN_PASSWORD from .env.
    Stored formats: 's2$<log_n>$<salt>$<hash>' (current) and '<salt>$<hash>' (older, N=2**14)."""
    stored = app_settings.get_internal("admin_password_hash")
    if stored:
        parts = stored.split("$")
        if parts[0] == "s2" and len(parts) == 4:
            log_n, salt_hex, hash_hex = int(parts[1]), parts[2], parts[3]
        else:
            log_n, (salt_hex, hash_hex) = 14, stored.split("$", 1)
        return hmac.compare_digest(_hash_password(candidate, bytes.fromhex(salt_hex), log_n), hash_hex)
    return hmac.compare_digest(candidate.encode(), settings.admin_password.encode())

def set_admin_password(new_password: str) -> None:
    """Store the new hash and bump the session version, which logs out every other session."""
    salt = os.urandom(16)
    app_settings.set_internal("admin_password_hash", f"s2${SCRYPT_LOG_N}${salt.hex()}${_hash_password(new_password, salt)}")
    sign_out_everywhere()

def sign_out_everywhere() -> None:
    app_settings.set_internal("session_version", str(int(_session_version()) + 1))

def require_auth(unsubvault_session: str | None = Cookie(default=None)):
    if not verify_session_token(unsubvault_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

def validate_startup_config():
    if "unsubvault_dev" in settings.database_url or "change_me" in settings.database_url:
        log.warning("The database is using a default development password. Set a strong POSTGRES_PASSWORD in .env before exposing this app.")
    if settings.secret_key in ("", "changeme", "change_me_to_random_32_chars") or len(settings.secret_key) < 32:
        raise RuntimeError("SECRET_KEY must be set to a random string of at least 32 characters (openssl rand -hex 32)")
    if not app_settings.get_internal("admin_password_hash") and len(settings.admin_password) < MIN_PASSWORD_LEN:
        raise RuntimeError("ADMIN_PASSWORD must be set in .env (at least 8 characters)")
