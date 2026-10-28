import base64, hashlib
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from app.core.config import settings

_V2 = "v2:"

def derive_key(label: bytes) -> bytes:
    """A separate 32-byte key per purpose (encryption, session signing) from SECRET_KEY, so one is never reused for the other."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"unsubvault-v2", info=label).derive(settings.secret_key.encode())

def _fernet_v2() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(derive_key(b"fernet")))

def _fernet_v1() -> Fernet:  # data written before v2 used SHA-256(SECRET_KEY) directly; still readable
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()))

def encrypt(value: str) -> str:
    return _V2 + _fernet_v2().encrypt(value.encode()).decode()

def decrypt(token: str) -> str:
    try:
        if token.startswith(_V2):
            return _fernet_v2().decrypt(token[len(_V2):].encode()).decode()
        return _fernet_v1().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("Cannot decrypt stored secret: SECRET_KEY changed or data is corrupt")
