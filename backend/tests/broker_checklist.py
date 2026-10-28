import os, subprocess, json
from datetime import datetime, timedelta
from tests import _env; _env.setup()  # fresh scratch database + migrations
from app.core.database import SessionLocal, engine
assert str(engine.url).endswith("unsubvault_test"), "NOT scratch DB"
from fastapi import HTTPException
from app.core.crypto import encrypt
from app.models.account import Account, ProviderType
from app.models.audit_event import AuditEvent
from app.models.broker_status import BrokerStatus
import app.services.imap_client as ic
from app.api import privacy
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

B = privacy._CATALOG["brokers"]
check("catalog: unique ids", len({b["id"] for b in B}) == len(B))
check("catalog: every URL is https", all(b["url"].startswith("https://") for b in B))
check("catalog: required fields present", all(all(k in b for k in ("id", "name", "category", "method", "url", "notes", "recheck_months", "sender_domains", "link_check")) for b in B))
check("catalog: known categories only", {b["category"] for b in B} <= {"california", "people_search", "marketing_data", "mail_calls", "tools"})
check("catalog: California DROP is first and points at the official site", B[0]["id"] == "ca-drop" and B[0]["url"].startswith("https://consumer.drop.privacy.ca.gov"))
check("catalog: holds no personal data fields", not any(k in b for b in B for k in ("name_of_user", "address", "phone")))

db = SessionLocal()
res = privacy.brokers(db)
check("fresh: everything not started, none due", all(b["status"] == "not_started" and not b["recheck_due"] for b in res["brokers"]) and res["links_checked_at"])
class R: pass
r = privacy.set_status("spokeo", privacy.StatusIn(status="requested"), None, db)
check("requested: stamps request date", r["status"] == "requested" and r["requested_at"] and not r["confirmed_at"])
r = privacy.set_status("spokeo", privacy.StatusIn(status="confirmed"), None, db)
check("confirmed: stamps done date", r["status"] == "confirmed" and r["confirmed_at"] and not r["recheck_due"])
st = db.query(BrokerStatus).get("spokeo"); st.confirmed_at = datetime.utcnow() - timedelta(days=200); db.commit()
check("re-check due after the broker's interval (6 months)", [b for b in privacy.brokers(db)["brokers"] if b["id"] == "spokeo"][0]["recheck_due"])
r = privacy.set_status("spokeo", privacy.StatusIn(status="relisted"), None, db)
check("came back (relisted) keeps history, is not 'due'", r["status"] == "relisted" and not r["recheck_due"])
r = privacy.set_status("spokeo", privacy.StatusIn(status="not_started"), None, db)
check("reset clears dates", r["status"] == "not_started" and not r["requested_at"] and not r["confirmed_at"])
for bad in (("nope", "requested", 404), ("spokeo", "done!", 400)):
    try: privacy.set_status(bad[0], privacy.StatusIn(status=bad[1]), None, db); check(f"rejects {bad[:2]}", False)
    except HTTPException as e: check(f"rejects {bad[:2]}", e.status_code == bad[2])
check("status changes audited by broker id only", db.query(AuditEvent).filter(AuditEvent.event_type == "broker_status_changed").count() == 4)

# dkim parsing
check("dkim pass domain parsed", ic.dkim_pass_domain("mx.example; spf=pass smtp.mailfrom=a.com; dkim=pass header.d=spokeo.com header.s=x; dmarc=pass") == "spokeo.com")
check("dkim fail/none -> not verified", ic.dkim_pass_domain("dkim=fail header.d=spokeo.com") is None and ic.dkim_pass_domain("") is None)
check("dkim=pass for a DIFFERENT domain is returned as that domain", ic.dkim_pass_domain("dkim=pass header.d=evil.com") == "evil.com")

# mailbox check with a fake server
def hdr(frm, subj, auth): return (f"From: {frm}\r\nSubject: {subj}\r\nDate: Tue, 27 Oct 2026 10:00:00 +0000\r\nAuthentication-Results: {auth}\r\n\r\n").encode()
MSGS = {1: hdr("Spokeo <noreply@mail.spokeo.com>", "Confirm your removal", "mx.example.test; dkim=pass header.d=spokeo.com"),
        2: hdr("Spokeo Support <help@spokeo.com>", "Action required: confirm", "mx.example.test; dkim=fail header.d=spokeo.com"),
        3: hdr("Radaris <x@radaris-support.biz>", "Confirm removal", "mx.example.test; dkim=pass header.d=radaris-support.biz")}
class Fake:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def login(self, *a): pass
    def oauth2_login(self, *a): pass
    def list_folders(self): return [((), "/", "INBOX"), ((b"\\Junk",), "/", "Junk Email")]
    def select_folder(self, n, readonly=False): assert readonly, "mailbox check must be read-only"; self.cur = n
    def search(self, crit):
        d = crit[1]
        if self.cur != "INBOX": return []
        return [1, 2] if d == "spokeo.com" else [3] if d == "radaris-support.biz" else []
    def fetch(self, uids, parts): return {u: {b"BODY[HEADER.FIELDS (FROM SUBJECT DATE AUTHENTICATION-RESULTS)]": MSGS[u]} for u in uids}
ic._IMAPClient = Fake
acct = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="imap.example.test", imap_port=993, imap_username="u", imap_password_encrypted=encrypt("p"))
db.add(acct); db.commit()
orig = privacy.BROKERS["radaris"]["sender_domains"]; privacy.BROKERS["radaris"]["sender_domains"] = ["radaris.com", "radaris-support.biz"]
for b in privacy._CATALOG["brokers"]:
    if b["id"] == "radaris": b["sender_domains"] = ["radaris.com", "radaris-support.biz"]
out = privacy.check_mailbox(privacy.MailCheck(account_id=acct.id, days=45), None, db)
sp = out["by_broker"].get("spokeo", [])
check("finds broker mail and groups it by broker", len(sp) == 2 and out["messages"] == 3)
check("verified only when the provider verified DKIM for that broker's domain", {m["subject"]: m["verified"] for m in sp} == {"Confirm your removal": True, "Action required: confirm": False})
check("result carries no links and no body", all(set(m) == {"folder", "from", "subject", "date", "dkim_domain", "verified"} for ms in out["by_broker"].values() for m in ms))
ev = [json.loads(e.detail) for e in db.query(AuditEvent).filter(AuditEvent.event_type == "broker_mailbox_checked")]
check("audit has counts only (no subjects or senders)", ev == [{"days": 45, "messages": 3, "brokers": len(out["by_broker"])}] and "Confirm" not in json.dumps(ev))
print(f"\n{ok} passed, {fail} failed")
