import os, subprocess, json, asyncio
from datetime import datetime, timedelta
from tests import _env; _env.setup()  # fresh scratch database + migrations
from app.core.database import SessionLocal, engine
assert str(engine.url).endswith("unsubvault_test"), "NOT scratch DB"
import httpx
from fastapi import HTTPException
from app.api import privacy
from app.core import app_settings
from app.models.audit_event import AuditEvent
from app.models.registry import LinkCheck, RegistryBroker, RegistrySync
from app.services import linkcheck, registry, safe_http
from app.services.safe_http import UnsafeURL
ok = fail = skip = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

HEAD = "Data Broker Name,Email Address,Website URL,Physical Address,How a consumer may opt out of sale or submit requests under the CCPA,Additional,Date Added\n"
def csvb(rows, bom=True):
    body = HEAD + "".join(f'"{n}","{e}","{w}","addr","{o}","x","{d}"\n' for n, e, w, o, d in rows)
    return (("﻿" if bom else "") + body).encode()
R = lambda n, w="https://a.example", o="Use the form, then confirm by email.", e="privacy [at] a.example", d="1/1/2025": (n, e, w, o, d)

# ---- parsing
rows = registry.parse(csvb([R("Alpha Data, Inc."), R("Beta\x00 Co", o='Multi\nline, with ""quotes""'), R("alpha data, inc.", w="https://alpha2.example"), ("", "x", "y", "z", "d")]))
by = {r["name"]: r for r in rows}
check("parse: BOM handled, blank names skipped, same name (any case) collapses to the last row", len(rows) == 2 and by["alpha data, inc."]["website"] == "https://alpha2.example")
check("parse: control characters removed from text", "\x00" not in json.dumps(rows) and "Beta Co" in by)
check("parse: obfuscated email '[at]' is normalised", by["alpha data, inc."]["email"] == "privacy@a.example")
check("parse: quotes and newlines survive in opt-out text", 'with "quotes"' in by["Beta Co"]["optout_text"] and "\n" in by["Beta Co"]["optout_text"])
check("parse: very long text is capped", len(registry.parse(csvb([R("Long", o="x" * 9000)]))[0]["optout_text"]) == registry.MAX_TEXT)

# ---- diffing
db = SessionLocal()
base_rows = registry.parse(csvb([R(f"Broker {i}", w=f"https://b{i}.example") for i in range(60)]))
s1 = registry.apply(db, base_rows)
check("first sync is a baseline: nothing is 'new'", s1["baseline"] and s1["new"] == 0 and s1["total"] == 60 and db.query(RegistryBroker).filter(RegistryBroker.first_seen_sync == 0).count() == 60)
rows2 = registry.parse(csvb([R(f"Broker {i}", w=("https://moved.example" if i == 3 else f"https://b{i}.example")) for i in range(60) if i != 7] + [R("Brand New Co", w="https://new.example")]))
s2 = registry.apply(db, rows2)
check("second sync: 1 new, 1 changed, 1 removed", (s2["new"], s2["changed"], s2["removed"]) == (1, 1, 1) and not s2["baseline"], str(s2))
lst = lambda **k: privacy.list_registry(q=k.get("q", ""), filter=k.get("filter", "all"), limit=50, offset=0, db=db)
check("filter new/changed/removed", [i["name"] for i in lst(filter="new")["items"]] == ["Brand New Co"] and [i["name"] for i in lst(filter="changed")["items"]] == ["Broker 3"] and [i["name"] for i in lst(filter="removed")["items"]] == ["Broker 7"])
check("default list hides removed brokers", "Broker 7" not in [i["name"] for i in lst()["items"]])
check("search by name and by website", [i["name"] for i in lst(q="brand new")["items"]] == ["Brand New Co"] and [i["name"] for i in lst(q="moved.example")["items"]] == ["Broker 3"])
s3 = registry.apply(db, registry.parse(csvb([R(f"Broker {i}", w=("https://moved.example" if i == 3 else f"https://b{i}.example")) for i in range(60)] + [R("Brand New Co", w="https://new.example")])))
check("a broker that re-registers comes back (removed flag cleared), old new/changed flags age out", s3["removed"] == 0 and [i["name"] for i in lst(q="Broker 7")["items"]] == ["Broker 7"] and lst(filter="new")["items"] == [])
check("only https websites are offered as links", all(i["website_https"] == i["website"].startswith("https://") for i in lst()["items"]))

# ---- sync_now guards
async def fake_get(status, data):
    async def f(url, max_bytes=0): return status, data
    return f
async def guards():
    registry.safe_get_bytes = await fake_get(200, csvb([R("Only One")]))
    db.query(RegistrySync).update({"at": datetime.utcnow() - timedelta(hours=1)}); db.commit()
    try: await registry.sync_now(db); check("truncated file is refused (would otherwise mark everything removed)", False)
    except ValueError as e: check("truncated file is refused (would otherwise mark everything removed)", "looked wrong" in str(e))
    registry.safe_get_bytes = await fake_get(503, b"")
    try: await registry.sync_now(db); check("HTTP error is reported", False)
    except ValueError as e: check("HTTP error is reported", "503" in str(e))
    db.query(RegistrySync).update({"at": datetime.utcnow()}); db.commit()
    try: await registry.sync_now(db); check("syncing twice within 10 minutes is refused", False)
    except ValueError as e: check("syncing twice within 10 minutes is refused", "few minutes" in str(e))
asyncio.run(guards())
async def retry():
    calls = []
    async def flaky(url, max_bytes=0):
        calls.append(1); return (503, b"") if len(calls) == 1 else (200, csvb([R(f"Broker {i}") for i in range(60)]))
    registry.safe_get_bytes = flaky; registry.RETRY_WAIT = 0
    db.query(RegistrySync).update({"at": datetime.utcnow() - timedelta(hours=1)}); db.commit()
    res = await registry.sync_now(db)
    check("a 503 from the state's site is retried once, then succeeds", len(calls) == 2 and res["total"] == 60)
asyncio.run(retry())

# ---- tracking registry brokers
rid = "reg:" + db.query(RegistryBroker).filter(RegistryBroker.name == "Broker 3").first().id
r = privacy.set_status(rid, privacy.StatusIn(status="requested"), None, db)
check("registry brokers can be tracked like the checklist", r["status"] == "requested" and lst(filter="tracked")["items"][0]["name"] == "Broker 3")
try: privacy.set_status("reg:doesnotexist", privacy.StatusIn(status="requested"), None, db); check("unknown registry id rejected", False)
except HTTPException as e: check("unknown registry id rejected", e.status_code == 404)

# ---- downloader caps and redirect safety (fake server)
class FakeResp:
    def __init__(self, status, loc=None, chunks=()): self.status_code, self.headers, self._c = status, ({"location": loc} if loc else {}), chunks
    async def aiter_bytes(self):
        for c in self._c: yield c
    async def aclose(self): pass
def fake_client(script):
    seen = []
    class C:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def build_request(self, method, url, **kw): seen.append((method, url)); return (method, url)
        async def send(self, req, stream=False): return script[len(seen) - 1]
    return C, seen
real = safe_http.httpx.AsyncClient
async def dl():
    safe_http.httpx.AsyncClient, _ = fake_client([FakeResp(200, chunks=[b"x" * 600, b"y" * 600])])
    try: await safe_http.safe_get_bytes("https://example.com/big", max_bytes=1000); check("oversized response is cut off", False)
    except UnsafeURL: check("oversized response is cut off", True)
    safe_http.httpx.AsyncClient, _ = fake_client([FakeResp(200, chunks=[b"hello"])])
    st, body = await safe_http.safe_get_bytes("https://example.com/ok", max_bytes=1000)
    check("small response returned in full", (st, body) == (200, b"hello"))
    safe_http.httpx.AsyncClient, seen = fake_client([FakeResp(302, "https://169.254.169.254/x")])
    try: await safe_http.safe_get_bytes("https://example.com/r"); check("redirect to a private address is blocked while downloading", False)
    except UnsafeURL: check("redirect to a private address is blocked while downloading", len(seen) == 1)
    safe_http.httpx.AsyncClient = real
asyncio.run(dl())
async def real_dl():
    global skip
    if os.environ.get('UNSUBVAULT_OFFLINE'):
        print('SKIP real registry download (offline mode)'); skip += 1; return
    try:
        st, data = await safe_http.safe_get_bytes(registry.REGISTRY_URL, max_bytes=5_000_000)
        parsed = registry.parse(data)
        check("REAL download of California's registry works through the pinned-IP TLS path", st == 200 and len(parsed) > 300, f"{st} {len(parsed)}")
        check("real registry rows parse into brokers with names and ids", all(b["name"] and len(b["id"]) == 12 for b in parsed))
        db2 = SessionLocal(); db2.query(RegistryBroker).delete(); db2.query(RegistrySync).delete(); db2.commit()
        real_sync = registry.apply(db2, parsed)
        check("REAL end-to-end sync stores the whole registry as a baseline", real_sync["baseline"] and real_sync["total"] == len(parsed) and db2.query(RegistryBroker).count() == len(parsed))
    except httpx.HTTPError as e:
        print("SKIP real download:", type(e).__name__); skip += 1
asyncio.run(real_dl())

# ---- link classification and checking
C = linkcheck.classify
check("classify ok", C(200, "https://a.com/x", "https://a.com/x")[0] == "ok" and C(200, "https://a.com/x", "https://www.a.com/x/")[0] == "ok")
check("classify moved (different path or host)", C(200, "https://a.com/x", "https://a.com/y")[0] == "moved" and C(200, "https://a.com/x", "https://b.com/x")[0] == "moved")
check("classify blocked for bot protection codes", all(C(s, "https://a.com", "https://a.com")[0] == "blocked" for s in (403, 429, 503)))
check("classify broken for gone pages and server errors", C(404, "https://a.com", None)[0] == "broken" and C(410, "https://a.com", None)[0] == "broken" and C(500, "https://a.com", None)[0] == "broken")
async def lc():
    results = {"https://ok.example/": (200, "https://ok.example/"), "https://moved.example/a": (200, "https://moved.example/b"), "https://block.example/": (403, "https://block.example/"),
               "https://gone.example/": (404, "https://gone.example/")}
    async def fake(method, url, form=None):
        if url == "https://boom.example/": raise httpx.ConnectTimeout("t")
        if url == "https://evil.example/": raise UnsafeURL("evil.example points at a non-public address")
        return results[url]
    linkcheck.safe_request = fake; linkcheck.DELAY = 0
    cat = [{"id": "a", "url": "https://ok.example/"}, {"id": "b", "url": "https://moved.example/a"}, {"id": "c", "url": "https://block.example/"},
           {"id": "d", "url": "https://gone.example/"}, {"id": "e", "url": "https://boom.example/"}, {"id": "f", "url": "https://evil.example/"}]
    counts = await linkcheck.check_all(cat)
    check("check_all classifies every link and stores the result", counts == {"ok": 1, "moved": 1, "blocked": 1, "broken": 3}, str(counts))
    rows = {r.broker_id: r for r in SessionLocal().query(LinkCheck).all()}
    check("moved link remembers its new address; others do not", rows["b"].final_url == "https://moved.example/b" and rows["a"].final_url is None)
    check("unsafe link is reported as blocked for safety, connection errors as broken", "safety" in rows["f"].note and rows["e"].state == "broken")
    linkcheck._running = True
    check("a second check while one is running does nothing", (await linkcheck.check_all(cat)) == {"running": True}); linkcheck._running = False
asyncio.run(lc())
sess = SessionLocal(); sess.query(LinkCheck).filter(LinkCheck.broker_id == "spokeo").delete()
sess.add(LinkCheck(broker_id="spokeo", checked_at=datetime.utcnow(), state="moved", http_status=200, final_url="https://www.spokeo.com/new-optout", note="Redirects")); sess.commit()
sp = [b for b in privacy.brokers(sess)["brokers"] if b["id"] == "spokeo"][0]
check("brokers endpoint shows live link state and where it moved", sp["link_state"] == "moved" and sp["link_moved_to"].endswith("/new-optout") and privacy.brokers(sess)["links_live"])
check("search domain only for people-search and marketing brokers", sp["search_domain"] == "spokeo.com" and [b for b in privacy.brokers(sess)["brokers"] if b["id"] == "donotcall"][0]["search_domain"] is None)

# ---- profile
class Rq: pass
p = privacy.put_profile(privacy.Profile(full_name="  Jane Q Public ", city="Springfield", state="ca", also_known_as=["J Public", " ", "Jane Smith"]), None)
check("profile normalised (trimmed, state upper-cased, blanks dropped)", p == {"full_name": "Jane Q Public", "city": "Springfield", "state": "CA", "also_known_as": ["J Public", "Jane Smith"]})
raw = app_settings.get_internal(privacy.PROFILE_KEY)
check("profile is ENCRYPTED at rest (no name or city in the stored value)", raw and "Jane" not in raw and "Springfield" not in raw and raw.startswith("v2:gAAAA"))
check("profile round-trips", privacy.get_profile()["full_name"] == "Jane Q Public")
try: privacy.put_profile(privacy.Profile(full_name="x", state="California"), None)
except Exception as e: check("bad state rejected", True)
else: check("bad state rejected", False)
try: privacy.put_profile(privacy.Profile(full_name="x", state="1!"), None); check("non-letter state rejected", False)
except HTTPException as e: check("non-letter state rejected", e.status_code == 400)
ev = " ".join((e.detail or "") for e in sess.query(AuditEvent).filter(AuditEvent.event_type == "privacy_profile_saved"))
check("audit records only which fields were filled, never values", "Jane" not in ev and "Springfield" not in ev and '"has_name": true' in ev)
privacy.delete_profile(None)
check("profile can be deleted", privacy.get_profile()["full_name"] == "" and not app_settings.get_internal(privacy.PROFILE_KEY))
print(f"\n{ok} passed, {fail} failed, {skip} skipped (network)")
