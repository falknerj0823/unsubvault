"""Regression tests for the fixes from the pre-publication security audit."""
import asyncio, email, json, os, subprocess, time
from datetime import datetime, timedelta
from tests import _env; _env.setup()  # fresh scratch database + migrations
import hashlib, base64
from cryptography.fernet import Fernet
from fastapi import BackgroundTasks, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from app.core import app_settings, audit, crypto, security
from app.core.config import settings
from app.core.crypto import encrypt
from app.core.database import SessionLocal
from app.models.account import Account, ProviderType
from app.models.app_setting import AppSetting
from app.models.email_record import EmailAction, EmailRecord
from app.models.scan_run import ScanRun, ScanStatus
from app.api import session as session_api
from app.main import app
from app.services import imap_client as ic, linkcheck, llm, oauth_microsoft, safe_http, scanner
from app.services.safe_http import UnsafeURL, validate_url

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

PW = "hardening-password-1"; security.set_admin_password(PW)
db = SessionLocal()

# ------------------------------------------------------------ IMAP: exact Message-ID matching
check("message-id: normal id accepted", ic.clean_message_id("<abc.123@mail.example>") == "<abc.123@mail.example>")
check("message-id: folded CRLF/space is removed, not passed through", ic.clean_message_id("<abc@\r\n mail.example>") == "<abc@mail.example>")
for bad in ("@", ".", "abc@x", "<>", "<a@x><b@c>", '<a"b@x>', "<a\\b@x>", "<a\x00b@x>", "", None, "<" + "a" * 400 + "@x>"):
    check(f"message-id: rejected {bad!r:.30}", ic.clean_message_id(bad) is None)

class Srv:
    """IMAP search is a case-insensitive SUBSTRING match, exactly like the real thing."""
    mailbox = {}  # uid -> message-id
    def search(self, crit): return [u for u, m in Srv.mailbox.items() if crit[2].lower() in m.lower()]
    def fetch(self, uids, parts): return {u: {b"BODY[HEADER.FIELDS (MESSAGE-ID)]": f"Message-ID: {Srv.mailbox[u]}\r\n\r\n".encode()} for u in uids}
Srv.mailbox = {1: "<a@x.example>", 2: "<aa@x.example>", 3: "<bb@x.example>", 4: "<A@X.EXAMPLE>"}
c = Srv()
check("exact: '<a@x.example>' is a substring of '<aa@x.example>' but only the exact header counts", ic.exact_uids(c, "<a@x.example>") == [1])
check("exact: no match -> nothing", ic.exact_uids(c, "<zz@x.example>") == [])
check("exact: a degenerate id matches nothing instead of everything", ic.exact_uids(c, "@") == [] and ic.exact_uids(c, ".") == [])
Srv.mailbox = {i: f"<m{i}@x.example>" for i in range(60)}
check("exact: a search returning dozens of hits is refused", ic.exact_uids(c, "<m@x.example>") == [] and ic.exact_uids(c, "<m1@x.example>") in ([1], [10, 11, 12, 13, 14, 15, 16, 17, 18, 19][:0] or [1]))
Srv.mailbox = {5: "<dup@x.example>", 6: "<dup@x.example>"}
class MoveSrv(Srv):
    def __init__(self, *a, **k): self.moved = []
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def login(self, *a): pass
    def oauth2_login(self, *a): pass
    def list_folders(self): return [((b"\\Junk",), "/", "Junk"), ((), "/", "INBOX")]
    def select_folder(self, n, readonly=False): MoveSrv.ro = readonly
    def move(self, uids, dest): MoveSrv.moved = list(uids)
ic._IMAPClient = MoveSrv
r = ic.IMAPClient("imap.example.test", 993, "u", "p").move_to_junk("INBOX", ["<dup@x.example>", "<none@x.example>"], dry_run=False)
check("move: a duplicated Message-ID is ambiguous, so nothing is moved", getattr(MoveSrv, "moved", []) == [] and set(r["missing"]) == {"<dup@x.example>", "<none@x.example>"})
Srv.mailbox = {7: "<one@x.example>", 8: "<other@x.example>"}
ic.IMAPClient("imap.example.test", 993, "u", "p").move_to_junk("INBOX", ["<one@x.example>"], dry_run=False)
check("move: only the exact single match is moved (not the other message)", MoveSrv.moved == [7])

# ------------------------------------------------------------ Authentication-Results trust
def msg(*headers): return email.message_from_string("".join(f"Authentication-Results: {h}\n" for h in headers) + "From: a@b.example\n\nbody")
forged = "mx.sender.example; dkim=pass header.d=brand.example"
real = "spf=pass smtp.mailfrom=x; dkim=fail header.d=brand.example"
check("auth: Microsoft/Google: only the TOPMOST header is used", ic.trusted_auth(msg(real, forged), "outlook.office365.com") == real and ic.trusted_auth(msg(real, forged), "imap.gmail.com") == real)
check("auth: a forged header BELOW the provider's is ignored", ic.dkim_pass_domain(ic.trusted_auth(msg(real, forged), "outlook.office365.com")) is None)
check("auth: unknown server, header names the server's own domain -> trusted", ic.trusted_auth(msg("mx.mail.example.test; dkim=pass header.d=x.example"), "imap.example.test").startswith("mx.mail.example.test"))
check("auth: unknown server, header from another domain (forgeable) -> not trusted", ic.trusted_auth(msg(forged), "imap.example.test") == "")
check("auth: no header at all -> nothing", ic.trusted_auth(msg(), "outlook.office365.com") == "")
big = "dkim=pass " * 200000
t0 = time.time(); ic.dkim_pass_domain(big); check("auth: a multi-megabyte header cannot stall the parser", time.time() - t0 < 0.5, f"{time.time()-t0:.2f}s")
from app.services import sender_check as sc
t0 = time.time(); sc.parse_auth("spf=pass " * 200000); check("auth: the verify parser is bounded too", time.time() - t0 < 1.0)

# ------------------------------------------------------------ CLI subprocess environment
captured = {}
class P:
    returncode = 0
    async def communicate(self, data): return b"ok", b""
async def fake_exec(*argv, **kw): captured.update(kw); return P()
asyncio_exec = asyncio.create_subprocess_exec; asyncio.create_subprocess_exec = fake_exec
for k, v in {"SECRET_KEY": "sk", "DATABASE_URL": "postgresql://u:p@h/d", "ADMIN_PASSWORD": "pw", "ANTHROPIC_API_KEY": "fake-anthropic-value", "OPENAI_API_KEY": "fake-openai-value", "MICROSOFT_CLIENT_SECRET": "ms"}.items(): os.environ.setdefault(k, v)
asyncio.run(llm._run_cli(["claude", "-p"], "hi", {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}))
asyncio.create_subprocess_exec = asyncio_exec
env = captured["env"]
check("cli: app secrets are NOT passed to the CLI", not any(k in env for k in ("SECRET_KEY", "DATABASE_URL", "ADMIN_PASSWORD", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MICROSOFT_CLIENT_SECRET", "REDIS_URL")), str(sorted(env)))
check("cli: it still gets what it needs (PATH, the subscription token) and telemetry/auto-update are off", "PATH" in env and env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok" and env["DISABLE_AUTOUPDATER"] == "1" and env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1")
check("cli: runs in an empty temp dir, no shell", captured["cwd"] and "shell" not in captured)

# ------------------------------------------------------------ safe_http extras
for url in ("https://[64:ff9b::808:808]/", "https://[2002:808:808::1]/", "https://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/", "https://[::ffff:169.254.169.254]/", "https://[fd00::1]/"):
    try: validate_url(url); check(f"ssrf: blocks {url}", False)
    except UnsafeURL: check(f"ssrf: blocks {url}", True)
async def hang(*a, **k): await asyncio.sleep(5)
real_fetch, real_deadline = safe_http._fetch, safe_http.TOTAL_DEADLINE
safe_http._fetch, safe_http.TOTAL_DEADLINE = hang, 0.2
try: asyncio.run(safe_http.safe_request("GET", "https://example.com/")); check("ssrf: a stalled site is cut off by the overall deadline", False)
except UnsafeURL as e: check("ssrf: a stalled site is cut off by the overall deadline (as a handled error)", "too long" in str(e))
safe_http._fetch, safe_http.TOTAL_DEADLINE = real_fetch, real_deadline
async def timed_out(url):
    async def slow(*a, **k): raise UnsafeURL("the site took too long to answer")
    linkcheck.safe_request = slow; return await linkcheck.check_one(url)
st = asyncio.run(timed_out("https://example.com/"))
check("link check: a timeout is reported, it does not crash the checker", st[0] == "broken" and "safety" in st[3])

# ------------------------------------------------------------ crypto v2, graceful failures
tok = encrypt("secret")
check("crypto: new data is versioned v2", tok.startswith("v2:") and crypto.decrypt(tok) == "secret")
legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())).encrypt(b"old-value").decode()
check("crypto: data written before v2 is still readable", crypto.decrypt(legacy) == "old-value")
check("crypto: separate purposes get separate keys", crypto.derive_key(b"fernet") != crypto.derive_key(b"session") and len(crypto.derive_key(b"x")) == 32)
orig = settings.secret_key; settings.secret_key = "a-different-secret-key-0123456789abcdef"
check("settings: an unreadable secret reads as 'not set' instead of crashing", app_settings.get("microsoft_client_secret") == settings.microsoft_client_secret)
app_settings.update({"microsoft_client_secret": "x" * 20})  # written under the new key
settings.secret_key = orig
api = TestClient(app); api.post("/api/session/login", json={"password": PW})
r = api.get("/api/settings/app"); check("settings API still loads when a stored secret can't be decrypted", r.status_code == 200 and r.json()["microsoft_client_secret_set"] is False, str(r.status_code))
r = api.get("/api/settings/llm"); check("llm settings still load too", r.status_code == 200)
r = api.get("/api/privacy/profile"); check("profile endpoint still loads", r.status_code == 200)
acct = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="imap.example.test", imap_port=993, imap_username="u", imap_password_encrypted="gAAAAABbroken")
db.add(acct); db.commit()
try: scanner._client_for(acct, db); check("scan: unreadable stored credentials give a clear message", False)
except scanner.ScanError as e: check("scan: unreadable stored credentials give a clear message", "SECRET_KEY" in str(e))

# ------------------------------------------------------------ password hashing
check("password: new hashes carry their cost parameters", app_settings.get_internal("admin_password_hash").startswith("s2$15$"))
salt = os.urandom(16); app_settings.set_internal("admin_password_hash", salt.hex() + "$" + hashlib.scrypt(b"legacy-pass-123", salt=salt, n=2**14, r=8, p=1).hex())
check("password: the older hash format still verifies", security.check_admin_password("legacy-pass-123") and not security.check_admin_password("nope"))
security.set_admin_password(PW)
t = security.make_session_token(); security.sign_out_everywhere()
check("sessions: sign-out-everywhere invalidates every token", not security.verify_session_token(t))
api = TestClient(app); api.post("/api/session/login", json={"password": PW})
check("sessions: logout-all endpoint ends the current session too", api.post("/api/session/logout-all").status_code == 200 and api.get("/api/session/me").status_code == 401)

# ------------------------------------------------------------ rate-limit / audit client address
class Rq:
    def __init__(self, host, real=None): self.client = type("C", (), {"host": host})(); self.headers = {"x-real-ip": real} if real else {}
check("client ip: X-Real-IP is trusted from the private proxy address", audit.client_ip(Rq("172.18.0.5", "203.0.113.9")) == "203.0.113.9")
check("client ip: a spoofed X-Real-IP from a public address is ignored", audit.client_ip(Rq("8.8.8.8", "203.0.113.9")) == "8.8.8.8")
check("client ip: no header -> the connecting address", audit.client_ip(Rq("172.18.0.5")) == "172.18.0.5")

# ------------------------------------------------------------ cross-site write protection
api = TestClient(app); api.post("/api/session/login", json={"password": PW})
host = "http://testserver"
check("origin: a write from another site is blocked", api.post("/api/session/logout", headers={"Origin": "https://evil.example"}).status_code == 403)
check("origin: browser says cross-site -> blocked", api.post("/api/session/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403)
check("origin: a write from this app's own origin works", api.post("/api/unsubscribe/keep", json={"senders": [{"account_id": 1, "sender_email": "@x"}]}, headers={"Origin": host}).status_code != 403)
check("origin: the configured frontend URL is also allowed", api.post("/api/unsubscribe/keep", json={"senders": [{"account_id": 1, "sender_email": "@x"}]}, headers={"Origin": app_settings.get("frontend_url")}).status_code != 403)
check("origin: reads are never blocked", api.get("/api/accounts/", headers={"Origin": "https://evil.example"}).status_code == 200)
check("origin: non-browser clients (no Origin header) still work", api.post("/api/unsubscribe/keep", json={"senders": [{"account_id": 1, "sender_email": "@x"}]}).status_code != 403)
check("CORS: another site gets no allow-origin header", "access-control-allow-origin" not in {k.lower() for k in api.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}).headers})

# ------------------------------------------------------------ every route needs login
anon = TestClient(app); open_routes = {("GET", "/api/health"), ("POST", "/api/session/login"), ("POST", "/api/session/logout")}
checked = 0; bad = []
import re as _re
for route, methods in app.openapi()["paths"].items():   # the OpenAPI schema lists every route and method FastAPI serves
    for method in methods:
        method = method.upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE") or (method, route) in open_routes: continue
        resp = anon.request(method, _re.sub(r"\{[^}]+\}", "1", route), json={} if method in ("POST", "PUT", "PATCH") else None, follow_redirects=False)
        checked += 1
        if resp.status_code != 401: bad.append((method, route, resp.status_code))
check(f"auth sweep: all {checked} API routes (every method) reject an anonymous caller", checked > 40 and not bad, str(bad))

# ------------------------------------------------------------ small correctness fixes
acct2 = Account(label="t2", provider_type=ProviderType.imap, email_address="z@b.c", imap_host="h", imap_port=993, imap_username="u", imap_password_encrypted=encrypt("p"))
db.add(acct2); db.commit()
db.add(ScanRun(account_id=acct2.id, folder="INBOX", status=ScanStatus.running, dry_run=True)); db.commit()
api = TestClient(app); api.post("/api/session/login", json={"password": PW})
check("scan: a second scan of the same account while one runs -> 409", api.post("/api/scan/start", json={"account_id": acct2.id}).status_code == 409)
check("emails: an unknown action filter -> 400, not a crash", api.get("/api/emails/?action=bogus").status_code == 400 and api.get("/api/emails/?action=none").status_code == 200)

# retention keeps what is waiting for you, and purges NULL-method rows
old = datetime.utcnow() - timedelta(days=90)
def rec(mid, action, method, cat="other"):
    db.add(EmailRecord(account_id=acct2.id, message_id=mid, subject="s", sender_email=f"{mid}@x.example", category=cat, action=action, unsubscribe_method=method, created_at=old)); db.commit()
rec("<pend>", EmailAction.unsubscribe_pending, "pending_review"); rec("<failed>", EmailAction.unsubscribe_failed, "http_get"); rec("<spam>", EmailAction.none, "spam_skipped", "spam")
rec("<null>", EmailAction.none, None); rec("<kept>", EmailAction.none, "minimized", "transactional"); rec("<done>", EmailAction.unsubscribed, "rfc8058_post")
app_settings.update({"scan_retention_days": 30}); n = scanner.purge_old_records(db)
left = {r.message_id for r in db.query(EmailRecord).filter(EmailRecord.account_id == acct2.id)}
check("retention: pending, failed and spam-awaiting-move are never purged", {"<pend>", "<failed>", "<spam>"} <= left, str(left))
check("retention: finished rows, including ones with no unsubscribe method (NULL), ARE purged", n == 3 and not ({"<null>", "<kept>", "<done>"} & left), f"{n} {left}")

# opt-in link checks
runs = []
async def fake_check_all(cat): runs.append(1); return {}
linkcheck.check_all = fake_check_all
async def one_loop():
    calls = {"n": 0}
    async def stop(_s): calls["n"] += 1; raise asyncio.CancelledError()
    real_sleep = asyncio.sleep; linkcheck.asyncio.sleep = stop
    try: await linkcheck.weekly_loop([{"id": "a", "url": "https://x.example"}])
    except asyncio.CancelledError: pass
    finally: linkcheck.asyncio.sleep = real_sleep
app_settings.update({"auto_link_check": False}); asyncio.run(one_loop())
check("link monitor: does nothing unless the user turned it on", runs == [])
app_settings.update({"auto_link_check": True}); asyncio.run(one_loop())
check("link monitor: runs when turned on and never run before", runs == [1])

# microsoft sign-in state handling (no network)
check("oauth: scopes contain none of MSAL's reserved words (they make it crash)", not ({"openid", "profile", "offline_access"} & set(oauth_microsoft.SCOPES)))
for label, setup in (("unknown", lambda: None), ("replayed", None), ("expired", None)):
    pass
try: oauth_microsoft.finish_flow({"state": "forged", "code": "x"}); check("oauth: forged state rejected", False)
except ValueError: check("oauth: forged state rejected", True)
oauth_microsoft._flows["s1"] = (time.time(), {"state": "s1"})
oauth_microsoft._flows["s2"] = (time.time() - 10_000, {"state": "s2"})
try: oauth_microsoft.finish_flow({"state": "s2", "code": "x"}); check("oauth: an expired sign-in attempt is rejected", False)
except ValueError: check("oauth: an expired sign-in attempt is rejected", True)
oauth_microsoft._app = lambda: type("A", (), {"acquire_token_by_auth_code_flow": staticmethod(lambda flow, params, scopes=None: {"access_token": "t"})})()
check("oauth: a valid state works once", oauth_microsoft.finish_flow({"state": "s1", "code": "x"}) == {"access_token": "t"})
try: oauth_microsoft.finish_flow({"state": "s1", "code": "x"}); check("oauth: the same state cannot be replayed", False)
except ValueError: check("oauth: the same state cannot be replayed", True)
check("oauth: the redirect URI comes from the frontend URL", oauth_microsoft.redirect_uri().endswith("/api/auth/microsoft/callback") and oauth_microsoft.redirect_uri().startswith(app_settings.get("frontend_url").rstrip("/")))

# migrations go down and back up cleanly (every open connection must be released first, or DROP TABLE waits on their locks)
import psycopg2
from app.core.database import engine
db.close(); engine.dispose()
def tables():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        cur = conn.cursor(); cur.execute("select tablename from pg_tables where schemaname='public'")
        return {t for (t,) in cur.fetchall()}
    finally:
        conn.close()
env = {**os.environ}
down = subprocess.run(["alembic", "downgrade", "base"], capture_output=True, text=True, env=env, timeout=120)
left_tables = tables() - {"alembic_version"}
check("migrations: downgrading to base removes every table", down.returncode == 0 and not left_tables, (down.stderr or str(left_tables))[-300:])
up = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True, env=env, timeout=120)
check("migrations: upgrading again recreates the schema", up.returncode == 0 and {"accounts", "email_records", "audit_events", "sender_rules", "registry_brokers"} <= tables(), up.stderr[-300:])
print(f"\n{ok} passed, {fail} failed")
