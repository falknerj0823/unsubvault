import os, subprocess, asyncio, json
from tests import _env; _env.setup()  # fresh scratch database + migrations
from app.core.database import SessionLocal, engine
assert str(engine.url).endswith("unsubvault_test"), "NOT scratch DB"
import httpx
from fastapi import BackgroundTasks, HTTPException
from app.api.unsubscribe import start_job
from app.models.audit_event import AuditEvent
from app.models.email_record import EmailAction, EmailRecord
from app.models.account import Account, ProviderType
from app.models.unsub_job import UnsubJob
from app.models.scan_run import ScanRun  # noqa: registers table for FK
from app.services import bulk_unsub, safe_http, unsubscriber
from app.services.safe_http import UnsafeURL, validate_url, safe_request

ok = fail = skip = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

# ---- A. SSRF guard: every one of these must be refused
BAD = ["http://example.com/u", "https://127.0.0.1/x", "https://[::1]/", "https://169.254.169.254/latest/meta-data/", "https://10.0.0.5/",
       "https://192.168.1.1/", "https://172.17.0.1/", "https://localhost/", "https://db/", "https://redis/", "https://host.docker.internal/",
       "https://user:pw@example.com/", "https://example.com:8443/", "https://example.com:22/", "https://[::ffff:10.0.0.1]/", "https://0.0.0.0/",
       "https://100.64.0.1/", "ftp://example.com/", "https:///nohost", "https://2130706433/", "https://0x7f000001/", "javascript:alert(1)", "file:///etc/passwd"]
for u in BAD:
    try: validate_url(u); check(f"blocks {u}", False, "was allowed!")
    except UnsafeURL: check(f"blocks {u}", True)
    except Exception as e: check(f"blocks {u}", False, f"{type(e).__name__}")
try: h, p, ips = validate_url("https://example.com/unsub?t=1"); check("allows a normal public https URL", p == 443 and ips)
except Exception as e: check("allows a normal public https URL", False, str(e))

# ---- B. real network through the guard (skipped if offline)
async def net():
    global skip
    if os.environ.get('UNSUBVAULT_OFFLINE'):
        print('SKIP real network checks (offline mode)'); skip += 1
    else:
        await net_real()
    await net_fake()

async def net_real():
    global skip
    try: st, fin = await safe_request("GET", "https://example.com/"); check("real GET via pinned IP works (TLS verified against hostname)", st == 200, str(st))
    except httpx.HTTPError as e: print("SKIP real GET:", type(e).__name__); skip += 1
    for host, label in (("expired.badssl.com", "expired cert"), ("wrong.host.badssl.com", "wrong-host cert"), ("self-signed.badssl.com", "self-signed cert")):
        try: await safe_request("GET", f"https://{host}/"); check(f"refuses {label} (verification still on with IP pinning)", False, "request succeeded")
        except httpx.ConnectError: check(f"refuses {label} (verification still on with IP pinning)", True)
        except Exception as e: print("SKIP", label, type(e).__name__); skip += 1

async def net_fake():
    global skip
    # deterministic redirect tests: a fake server that answers with redirects (validation still runs for real)
    class FakeResp:
        def __init__(self, status, loc): self.status_code, self.headers = status, ({"location": loc} if loc else {})
        async def aclose(self): pass
    def fake_client(script):
        seen = []
        class C:
            def __init__(self, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            def build_request(self, method, url, **kw): seen.append((method, url, kw.get("extensions"))); return (method, url)
            async def send(self, req, stream=False): return FakeResp(*script[len(seen) - 1])
        return C, seen
    real = safe_http.httpx.AsyncClient
    for label, target in (("cloud metadata IP", "https://169.254.169.254/latest/meta-data/"), ("loopback", "https://127.0.0.1/"),
                          ("internal docker host", "https://db/"), ("plain http", "http://example.com/x"), ("other port", "https://example.com:8443/")):
        safe_http.httpx.AsyncClient, seen = fake_client([(302, target)])
        try: await safe_request("GET", "https://example.com/start"); check(f"redirect to {label} is blocked", False, "followed it")
        except UnsafeURL: check(f"redirect to {label} is blocked", len(seen) == 1)
    safe_http.httpx.AsyncClient, seen = fake_client([(302, "/next"), (200, None)])
    st, fin = await safe_request("GET", "https://example.com/start")
    check("relative redirect to a public host is followed (2 hops)", st == 200 and fin == "https://example.com/next" and len(seen) == 2)
    check("connection is pinned to a public IP with SNI = hostname", seen[0][1].startswith("https://") and "example.com" not in seen[0][1].split("/")[2] and seen[0][2] == {"sni_hostname": "example.com"}, str(seen[0]))
    safe_http.httpx.AsyncClient, seen = fake_client([(302, "/loop")] * 20)
    try: await safe_request("GET", "https://example.com/start"); check("redirect loop is cut off", False)
    except UnsafeURL: check("redirect loop is cut off", len(seen) <= 6)
    safe_http.httpx.AsyncClient, seen = fake_client([(302, "/done"), (200, None)])
    await safe_request("POST", "https://example.com/u", {"List-Unsubscribe": "One-Click"})
    check("POST followed by 302 becomes GET without the form", seen[1][0] == "GET")
    safe_http.httpx.AsyncClient = real
asyncio.run(net())

# ---- C. unsubscribe outcomes (network faked)
calls = []
def fake(status=200, raises=None):
    async def f(method, url, form=None):
        calls.append((method, url, form))
        if raises: raise raises
        return status, url
    return f
async def outcomes():
    U = "https://s.example/u?t=SECRETTOKEN"
    unsubscriber.safe_request = fake(200); r = await unsubscriber.unsubscribe(U, None, True, dry_run=False)
    check("one-click 200 -> confirmed via POST", r.status == "confirmed" and calls[-1][0] == "POST" and calls[-1][2] == {"List-Unsubscribe": "One-Click"})
    r = await unsubscriber.unsubscribe(U, None, False, dry_run=False)
    check("plain link 200 -> sent_unverified via GET", r.status == "sent_unverified" and calls[-1][0] == "GET")
    unsubscriber.safe_request = fake(500); r = await unsubscriber.unsubscribe(U, None, True, dry_run=False)
    check("HTTP 500 -> failed with reason", r.status == "failed" and "500" in r.error)
    unsubscriber.safe_request = fake(raises=UnsafeURL("x points at a non-public address")); r = await unsubscriber.unsubscribe(U, None, True, dry_run=False)
    check("blocked URL -> failed, 'Blocked for safety'", r.status == "failed" and "Blocked for safety" in r.error)
    unsubscriber.safe_request = fake(raises=httpx.ConnectTimeout("t")); r = await unsubscriber.unsubscribe(U, None, True, dry_run=False)
    check("network error -> failed, no crash", r.status == "failed")
    n = len(calls); r = await unsubscriber.unsubscribe(U, None, True, dry_run=True)
    check("dry-run sends nothing", r.status == "dry_run" and len(calls) == n)
    r = await unsubscriber.unsubscribe(None, "mailto:u@s.example", False, dry_run=False)
    check("mailto only -> manual, nothing sent", r.status == "manual" and r.method == "mailto" and len(calls) == n)
    r = await unsubscriber.unsubscribe(None, None, False, dry_run=False)
    check("no link -> manual", r.status == "manual")
asyncio.run(outcomes())
check("plain http links are never picked", unsubscriber.pick_target("<http://a.example/u>") == (None, None))
check("https preferred over http, mailto kept", unsubscriber.pick_target("<http://a.example/u>, <https://b.example/u>, <mailto:x@y.z>") == ("https://b.example/u", "mailto:x@y.z"))

# ---- D. bulk job
db = SessionLocal()
acct = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="h", imap_port=993, imap_username="a@b.c", imap_password_encrypted="x")
db.add(acct); db.commit()
def rec(i, sender, url, oc=False, conf=.9):
    db.add(EmailRecord(account_id=acct.id, message_id=f"<{i}>", subject=f"subj{i}", sender_name=sender, sender_email=sender,
        confidence=conf, category="newsletter", action=EmailAction.unsubscribe_pending, unsubscribe_url=url, unsubscribe_one_click=oc))
for i in range(3): rec(i, "a@one.example", "https://one.example/u?t=SECRETTOKEN", oc=True)
for i in range(3, 5): rec(i, "b@web.example", "https://web.example/u?t=SECRETTOKEN2")
rec(5, "c@mail.example", "mailto:u@mail.example")
rec(6, "d@insecure.example", "http://insecure.example/u")
db.commit()
g = {x["sender_email"]: x for x in bulk_unsub.sender_groups(db)}
check("groups by sender with counts", g["a@one.example"]["email_count"] == 3 and g["b@web.example"]["email_count"] == 2 and len(g) == 4)
check("method labels", (g["a@one.example"]["method"], g["b@web.example"]["method"], g["c@mail.example"]["method"]) == ("one_click", "web_link", "mailto"))
check("http-only sender has no automatic method", g["d@insecure.example"]["method"] == "none" and g["d@insecure.example"]["target"] is None)

bulk_unsub.DELAY_BETWEEN_SENDERS = 0
sel = [(acct.id, s) for s in g]
# server-side dry-run is ON by default (.env DRY_RUN=true): a request asking for live must be forced to dry-run
job = start_job(db, BackgroundTasks(), None, sel, dry_run_requested=False)
check("server dry-run forces dry-run even if request says live", job.dry_run is True)
try: start_job(db, BackgroundTasks(), None, sel, True); check("second job refused while one is pending", False)
except HTTPException as e: check("second job refused while one is pending", e.status_code == 409)
calls.clear(); unsubscriber.safe_request = fake(200)
bulk_unsub.run_job(job.id); db.expire_all(); job = db.get(UnsubJob, job.id)
check("dry-run job: completes, 2 simulated + 2 manual, NO network calls", job.status == "complete" and job.simulated == 2 and job.manual == 2 and len(calls) == 0, f"{job.status} sim={job.simulated} manual={job.manual} calls={len(calls)}")
check("dry-run leaves emails pending", db.query(EmailRecord).filter(EmailRecord.action == EmailAction.unsubscribe_pending).count() == 7)

live = UnsubJob(status="pending", dry_run=False, selection=json.dumps([[acct.id, s] for s in g]), total=4); db.add(live); db.commit()
calls.clear(); bulk_unsub.run_job(live.id); db.expire_all(); live = db.get(UnsubJob, live.id)
check("live job completes", live.status == "complete" and live.done == 4, f"{live.status} {live.done} {live.error}")
check("exactly 2 requests sent (one-click POST, web GET); mailto/http-only sent nothing", sorted(c[0] for c in calls) == ["GET", "POST"], str(calls))
check("counters: 1 confirmed, 1 unverified, 2 manual, 0 failed", (live.confirmed, live.unverified, live.manual, live.failed) == (1, 1, 2, 0), str((live.confirmed, live.unverified, live.manual, live.failed)))
st = lambda s: {r.action.value for r in db.query(EmailRecord).filter(EmailRecord.sender_email == s)}
check("all 3 emails from the one-click sender marked unsubscribed", st("a@one.example") == {"unsubscribed"})
check("web-link sender marked unsubscribed, result = sent_unverified", st("b@web.example") == {"unsubscribed"} and db.query(EmailRecord).filter(EmailRecord.sender_email == "b@web.example").first().unsubscribe_result == "sent_unverified")
check("mailto-only and http-only senders stay pending for manual action", st("c@mail.example") == {"unsubscribe_pending"} and st("d@insecure.example") == {"unsubscribe_pending"})
unsubscriber.safe_request = fake(500)
for r in db.query(EmailRecord).filter(EmailRecord.sender_email == "a@one.example"): r.action = EmailAction.unsubscribe_pending
db.commit()
f = UnsubJob(status="pending", dry_run=False, selection=json.dumps([[acct.id, "a@one.example"]]), total=1); db.add(f); db.commit()
bulk_unsub.run_job(f.id); db.expire_all()
check("server refusal marks emails unsubscribe_failed with reason", st("a@one.example") == {"unsubscribe_failed"} and db.get(UnsubJob, f.id).failed == 1)
rows = [(e.event_type, e.detail or "") for e in db.query(AuditEvent).all()]
check("audit has per-sender attempts and job summaries", {"unsubscribe_attempt", "bulk_unsubscribe_completed", "bulk_unsubscribe_started"} <= {t for t, _ in rows})
check("audit never contains unsubscribe URL tokens", not any("SECRETTOKEN" in d or "one.example/u" in d for _, d in rows))
print(f"\n{ok} passed, {fail} failed, {skip} skipped (network)")
