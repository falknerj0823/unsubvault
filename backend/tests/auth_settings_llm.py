import os
from tests import _env; _env.setup()  # fresh scratch database + migrations
from fastapi.testclient import TestClient
from app.core import app_settings, audit, crypto, security
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.app_setting import AppSetting
from app.models.audit_event import AuditEvent
from app.models.llm_config import LLMProfile
from app.api import session as session_api, settings as settings_api
from app.main import app

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

PW = "test-password-123"
db = SessionLocal()

# ---------------------------------------------------------------- crypto
t = crypto.encrypt("hunter2")
check("crypto: round trip", crypto.decrypt(t) == "hunter2")
check("crypto: ciphertext is not the plaintext and differs per call", "hunter2" not in t and crypto.encrypt("hunter2") != t)
try: crypto.decrypt(t[:-4] + "AAAA"); check("crypto: tampered ciphertext is rejected", False)
except ValueError: check("crypto: tampered ciphertext is rejected", True)
original_key = settings.secret_key
settings.secret_key = "a-completely-different-secret-key-0123456789"
try: crypto.decrypt(t); check("crypto: a different SECRET_KEY cannot read old data", False)
except ValueError as e: check("crypto: a different SECRET_KEY cannot read old data", "SECRET_KEY" in str(e))
settings.secret_key = original_key

# ---------------------------------------------------------------- session tokens
security.set_admin_password(PW)
tok = security.make_session_token()
check("token: valid token verifies", security.verify_session_token(tok))
check("token: tampered token fails", not security.verify_session_token(tok[:-3] + ("AAA" if not tok.endswith("AAA") else "BBB")))
check("token: garbage / empty fails", not security.verify_session_token("nonsense") and not security.verify_session_token(None) and not security.verify_session_token(""))
orig_ttl = security.SESSION_TTL; security.SESSION_TTL = -10
expired = security.make_session_token(); security.SESSION_TTL = orig_ttl
check("token: expired token fails", not security.verify_session_token(expired))
stored = app_settings.get_internal("admin_password_hash")
parts = (stored or "").split("$")
check("password is stored as salted scrypt with its cost, never in the clear", len(parts) == 4 and parts[0] == "s2" and parts[1] == "15" and len(parts[2]) == 32 and len(parts[3]) == 128 and PW not in stored)
check("password: new password accepted, wrong one rejected", security.check_admin_password(PW) and not security.check_admin_password("wrong-password"))
v1 = security.make_session_token(); security.set_admin_password("another-password-456")
check("password change signs out every older session", not security.verify_session_token(v1) and security.verify_session_token(security.make_session_token()))
security.set_admin_password(PW)
from fastapi import HTTPException
try: security.require_auth(None); check("require_auth rejects a missing cookie", False)
except HTTPException as e: check("require_auth rejects a missing cookie", e.status_code == 401)

# ---------------------------------------------------------------- every route needs login
client = TestClient(app)
for path in ["/api/accounts/", "/api/scan/runs", "/api/emails/", "/api/emails/counts", "/api/settings/", "/api/settings/app", "/api/settings/llm",
             "/api/unsubscribe/senders", "/api/unsubscribe/keep", "/api/audit/", "/api/privacy/brokers", "/api/privacy/profile", "/api/privacy/registry",
             "/api/spam/candidates", "/api/session/me", "/api/auth/microsoft/login", "/api/auth/microsoft/redirect-uri"]:
    r = client.get(path, follow_redirects=False)
    check(f"unauthenticated GET {path} -> 401", r.status_code == 401, str(r.status_code))
for method, path in [("post", "/api/scan/start"), ("post", "/api/unsubscribe/bulk"), ("put", "/api/settings/app"), ("put", "/api/settings/llm"),
                     ("delete", "/api/settings/data/scan"), ("post", "/api/spam/move"), ("post", "/api/privacy/registry/sync"), ("post", "/api/emails/1/verify")]:
    r = getattr(client, method)(path, json={}) if method != "delete" else client.delete(path)
    check(f"unauthenticated {method.upper()} {path} -> 401", r.status_code == 401, str(r.status_code))
check("health check stays open", client.get("/api/health").json() == {"status": "ok"})

# ---------------------------------------------------------------- login, cookie, logout, rate limit
session_api._failures.clear()
r = client.post("/api/session/login", json={"password": "nope"})
check("login: wrong password -> 401", r.status_code == 401)
r = client.post("/api/session/login", json={"password": PW})
sc = r.headers.get("set-cookie", "").lower()
check("login: right password -> 200 with an HttpOnly, SameSite=Lax cookie", r.status_code == 200 and "httponly" in sc and "samesite=lax" in sc and security.COOKIE_NAME in sc, sc[:120])
check("login: cookie is not 'Secure' on plain-http localhost (it would never be sent)", "secure" not in sc)
check("login: session now works", client.get("/api/session/me").status_code == 200 and client.get("/api/accounts/").status_code == 200)
client.post("/api/session/logout")
check("logout: session is gone", client.get("/api/session/me").status_code == 401)
session_api._failures.clear()
for _ in range(5): client.post("/api/session/login", json={"password": "bad"})
r = client.post("/api/session/login", json={"password": PW})
check("rate limit: after 5 failures even the right password is blocked (429)", r.status_code == 429)
session_api._failures.clear()
events = {e.event_type for e in db.query(AuditEvent).all()}
check("audit: login, failed login and block are recorded", {"login", "login_failed", "login_blocked", "logout"} <= events, str(events))

# ---------------------------------------------------------------- change password
c1, c2 = TestClient(app), TestClient(app)
for c in (c1, c2): assert c.post("/api/session/login", json={"password": PW}).status_code == 200
r = c1.post("/api/session/change-password", json={"current_password": "wrong", "new_password": "brand-new-password"})
check("change password: wrong current password -> 400", r.status_code == 400)
r = c1.post("/api/session/change-password", json={"current_password": PW, "new_password": "short"})
check("change password: too-short new password -> 400", r.status_code == 400)
r = c1.post("/api/session/change-password", json={"current_password": PW, "new_password": "brand-new-password"})
check("change password: success keeps this browser signed in", r.status_code == 200 and c1.get("/api/session/me").status_code == 200)
check("change password: other browsers are signed out", c2.get("/api/session/me").status_code == 401)
c3 = TestClient(app)
check("change password: old password stops working, new one works", c3.post("/api/session/login", json={"password": PW}).status_code == 401 and c3.post("/api/session/login", json={"password": "brand-new-password"}).status_code == 200)
detail = " ".join(e.detail or "" for e in db.query(AuditEvent).all())
check("audit never contains any password that was typed", PW not in detail and "brand-new-password" not in detail and "another-password-456" not in detail)
session_api._failures.clear()
security.set_admin_password(PW)

# ---------------------------------------------------------------- app settings store
app_settings.update({"microsoft_client_secret": "super-secret-value", "scan_batch_size": "75", "dry_run": False, "nonsense_key": "x"})
row = db.query(AppSetting).filter(AppSetting.key == "microsoft_client_secret").one()
check("settings: secrets are encrypted in the database", row.encrypted and row.value.startswith("v2:gAAAA") and "super-secret" not in row.value)
check("settings: values read back with the right types", app_settings.get("microsoft_client_secret") == "super-secret-value" and app_settings.get("scan_batch_size") == 75 and app_settings.get("dry_run") is False)
pub = app_settings.get_public()
check("settings: secrets are reported as 'set', never returned", pub["microsoft_client_secret_set"] is True and "super-secret" not in str(pub) and "microsoft_client_secret" not in pub)
app_settings.update({"microsoft_client_secret": None}); check("settings: None keeps a secret", app_settings.get("microsoft_client_secret") == "super-secret-value")
app_settings.update({"microsoft_client_secret": ""}); check("settings: empty string clears a secret", app_settings.get("microsoft_client_secret") == "")
check("settings: unknown keys are ignored", db.query(AppSetting).filter(AppSetting.key == "nonsense_key").count() == 0)

# ---------------------------------------------------------------- settings API validation
api = TestClient(app); assert api.post("/api/session/login", json={"password": PW}).status_code == 200
put = lambda body: api.put("/api/settings/app", json=body)
check("settings API: javascript: URL rejected", put({"frontend_url": "javascript:alert(1)"}).status_code == 400)
check("settings API: unknown timezone rejected, real one accepted", put({"timezone": "Mars/Olympus"}).status_code == 400 and put({"timezone": "America/Los_Angeles"}).status_code == 200)
check("settings API: Azure Secret ID (a GUID) rejected as a client secret", put({"microsoft_client_secret": "12345678-1234-1234-1234-123456789abc"}).status_code == 400)
check("settings API: out-of-range batch size rejected", put({"scan_batch_size": 0}).status_code == 422 and put({"scan_batch_size": 5000}).status_code == 422)
r = put({"microsoft_client_secret": "a-real-looking~secret-value", "scan_batch_size": 20})
check("settings API: saves, and the response never contains the secret", r.status_code == 200 and "a-real-looking" not in r.text and r.json()["microsoft_client_secret_set"] and r.json()["scan_batch_size"] == 20)

# ---------------------------------------------------------------- LLM profiles
llm = lambda body: api.put("/api/settings/llm", json=body)
r = llm({"provider": "openai_compatible", "model": "m1", "base_url": "http://localhost:1234/v1", "api_key": "sk-test-key-1"})
check("llm: saving a provider makes it active; the key is never returned", r.status_code == 200 and r.json()["active"] == "openai_compatible" and r.json()["profiles"]["openai_compatible"]["api_key_set"] and "sk-test" not in r.text)
check("llm: key is encrypted in the database", db.query(LLMProfile).filter(LLMProfile.provider == "openai_compatible").one().api_key_encrypted.startswith("v2:gAAAA"))
r = llm({"provider": "ollama", "model": "qwen3:8b", "base_url": ""})
check("llm: switching provider keeps the other provider's settings and key", r.json()["active"] == "ollama" and r.json()["profiles"]["openai_compatible"]["api_key_set"] and r.json()["profiles"]["openai_compatible"]["model"] == "m1")
r = llm({"provider": "openai_compatible", "model": "m1", "base_url": "http://localhost:1234/v1"})
check("llm: coming back without re-entering the key keeps it", r.json()["profiles"]["openai_compatible"]["api_key_set"])
r = llm({"provider": "openai_compatible", "model": "m1", "base_url": "http://evil.example/v1"})
check("llm: changing the endpoint without a key clears the saved key (it must not follow to a new server)", not r.json()["profiles"]["openai_compatible"]["api_key_set"])
r = llm({"provider": "openai_compatible", "model": "m1", "base_url": "http://x/v1", "api_key": "sk-two"}); r = llm({"provider": "openai_compatible", "model": "m1", "base_url": "http://x/v1", "api_key": ""})
check("llm: an empty key removes it", not r.json()["profiles"]["openai_compatible"]["api_key_set"])
check("llm: unknown provider rejected", llm({"provider": "skynet", "model": ""}).status_code == 400)
seen = {}
async def fake_complete(system, prompt, cfg=None): seen["cfg"] = cfg; return "ok"
settings_api.complete = fake_complete
llm({"provider": "openai", "model": "", "base_url": "", "api_key": "sk-openai-secret"})
r = api.post("/api/settings/llm/test", json={"provider": "openai_compatible", "model": "x", "base_url": "http://x/v1"})
check("llm test: a saved key for one provider is never sent to another", r.json()["ok"] and seen["cfg"].api_key == "" and seen["cfg"].provider == "openai_compatible", str(seen["cfg"]))
r = api.post("/api/settings/llm/test", json={"provider": "openai", "model": "", "base_url": ""})
check("llm test: the provider's own saved key is used when none is typed", seen["cfg"].api_key == "sk-openai-secret")
async def boom(system, prompt, cfg=None): raise RuntimeError("connection refused")
settings_api.complete = boom
r = api.post("/api/settings/llm/test", json={"provider": "ollama", "model": "x", "base_url": ""})
check("llm test: errors come back as a readable message, not a crash", r.status_code == 200 and r.json()["ok"] is False and "connection refused" in r.json()["error"])

# ---------------------------------------------------------------- audit helpers and API
c = audit._clean({"password": "x", "api_key": "k", "token_value": "t", "api_key_changed": True, "note": "n" * 900, "items": list(range(40)), "n": 3})
check("audit: secret-looking keys are dropped, booleans and numbers kept, text and lists capped", set(c and __import__("json").loads(c)) == {"api_key_changed", "note", "items", "n"} and len(__import__("json").loads(c)["note"]) == 300 and len(__import__("json").loads(c)["items"]) == 20)
audit.SessionLocal = lambda: (_ for _ in ()).throw(RuntimeError("database down"))
try: audit.record("x"); check("audit: a database failure never breaks the action being logged", True)
except Exception: check("audit: a database failure never breaks the action being logged", False)
audit.SessionLocal = SessionLocal
audit.record("test_event_a", success=False, detail={"k": 1}); audit.record("test_event_b")
d = api.get("/api/audit/", params={"event_type": "test_event_a"}).json()
check("audit API: filters by type", [e["type"] for e in d["events"]] == ["test_event_a"])
check("audit API: failures only", all(not e["success"] for e in api.get("/api/audit/", params={"failures_only": True}).json()["events"]))
p1 = api.get("/api/audit/", params={"limit": 3}).json()
p2 = api.get("/api/audit/", params={"limit": 3, "before_id": p1["events"][-1]["id"]}).json()
check("audit API: pages by id with no overlap", p1["has_more"] and not ({e["id"] for e in p1["events"]} & {e["id"] for e in p2["events"]}))
check("audit API: events are newest first with UTC timestamps", p1["events"][0]["id"] > p1["events"][1]["id"] and p1["events"][0]["at"].endswith("Z"))
print(f"\n{ok} passed, {fail} failed")
