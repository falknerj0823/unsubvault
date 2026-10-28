import os, subprocess, asyncio, email
from datetime import datetime, timedelta
from tests import _env; _env.setup()  # fresh scratch database + migrations
from app.core.database import SessionLocal, engine
assert str(engine.url).endswith("unsubvault_test"), "NOT on scratch DB, abort"
from app.core.crypto import encrypt
from app.models.account import Account, ProviderType
from app.models.email_record import EmailRecord
from app.models.scan_run import ScanRun, ScanStatus
from app.models.audit_event import AuditEvent
from app.services import scanner
from app.services.imap_client import IMAPClient, RawEmail

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += cond; fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

# ---- A. MIME parsing
c = IMAPClient("h")
html_only = email.message_from_bytes(b"From: =?utf-8?q?Caf=C3=A9?= <news@shop.example>\r\nSubject: =?utf-8?B?SGVsbG8g8J+RiyBzYWxl?=\r\nDate: Tue, 28 Oct 2026 10:00:00 -0700\r\nList-Unsubscribe: <https://shop.example/u/1>, <mailto:u@shop.example>\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><body><h1>Big  SALE</h1><p>50% off</p></body></html>")
r = c._parse(1, html_only)
check("html-only body becomes text snippet", r.snippet == "Big SALE 50% off", r.snippet)
check("encoded subject decoded", r.subject.startswith("Hello") and "sale" in r.subject, r.subject)
check("sender name decoded", r.sender_name == "Café" and r.sender_email == "news@shop.example", r.sender_name)
check("Date parsed to naive UTC", r.received_at == datetime(2026, 10, 28, 17, 0), str(r.received_at))
check("List-Unsubscribe kept", "https://shop.example/u/1" in r.list_unsubscribe)
bad = email.message_from_bytes(b"From: x@y.z\r\nSubject: =?bogus-charset?q?hi?=\r\nContent-Type: text/plain; charset=bogus\r\nContent-Transfer-Encoding: base64\r\n\r\naGVsbG8gd29ybGQ=\r\n")
r = c._parse(2, bad)
check("unknown charsets do not crash", r.snippet == "hello world" and r.received_at is None, repr(r.snippet))
empty = email.message_from_bytes(b"From: x@y.z\r\nSubject: s\r\nContent-Type: multipart/mixed; boundary=b\r\n\r\n--b\r\nContent-Type: application/pdf\r\n\r\nxx\r\n--b--\r\n")
check("no text part gives empty snippet, no crash", c._parse(3, empty).snippet == "")

# ---- B. scanner
db = SessionLocal()
imap = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="imap.example.com",
               imap_port=993, imap_username="a@b.c", imap_password_encrypted=encrypt("pw"))
db.add(imap); db.commit()
def mk(i, hdr=True, sub="s"): return RawEmail(uid=i, message_id=f"<m{i}@x>", subject=f"{sub}{i}", sender_name="N", sender_email=f"n{i}@x.com",
        received_at=None, list_unsubscribe="<https://x.com/u>, <mailto:u@x.com>" if hdr else None, snippet="body")
EM = [mk(1), mk(2, hdr=False), mk(3), mk(4)]
IMAPClient.fetch_emails = lambda self, folder, limit: iter(EM[:limit])
calls = []
async def fake_classify(subject, sender, snippet=""):
    calls.append(subject)
    if subject == "s4": return {"is_newsletter": False, "is_promotional": False, "confidence": .9, "category": "personal", "reason": "friend"}
    return {"is_newsletter": subject == "s1", "is_promotional": subject == "s3", "confidence": .91, "category": "newsletter", "reason": "bulk"}
scanner.classify_email = fake_classify
def run(account_id, batch=None):
    r = ScanRun(account_id=account_id, folder="INBOX", dry_run=True, status=ScanStatus.pending, batch_size=batch); db.add(r); db.commit()
    scanner.run_scan(r.id); db.expire_all(); return db.query(ScanRun).get(r.id)

r1 = run(imap.id)
recs = {"s" + x.message_id[2:-3]: x for x in db.query(EmailRecord).all()}  # subjects are not stored for receipts/personal mail
check("run 1 completes", r1.status == ScanStatus.complete, f"{r1.status} {r1.error}")
check("scanned all 4, stored only mail WITH List-Unsubscribe (3)", r1.emails_scanned == 4 and len(recs) == 3, f"{r1.emails_scanned} {len(recs)}")
check("LLM never saw the header-less email", "s2" not in calls and len(calls) == 3, str(calls))
check("newsletter/promo marked pending review", recs["s1"].action.value == "unsubscribe_pending" and recs["s3"].action.value == "unsubscribe_pending")
check("non-newsletter stored but not pending", recs["s4"].action.value == "none")
check("unsubscribe link kept (https preferred over mailto)", recs["s1"].unsubscribe_url == "https://x.com/u", str(recs["s1"].unsubscribe_url))
check("history counters: 3 new, 1 had no link", (r1.emails_found, r1.emails_known, r1.emails_no_link) == (3, 0, 1), str((r1.emails_found, r1.emails_known, r1.emails_no_link)))
r2 = run(imap.id); n = db.query(EmailRecord).count()
check("re-scan counters: 0 new, 3 already seen", (r2.emails_found, r2.emails_known, r2.emails_no_link) == (0, 3, 1), str((r2.emails_found, r2.emails_known, r2.emails_no_link)))
r2b = run(imap.id, batch=2)
check("batch size on the run is honored (looked at 2, not 4)", r2b.emails_scanned == 2, str(r2b.emails_scanned)); calls_after = len(calls)
check("re-scan adds no duplicates and makes no new LLM calls", n == 3 and calls_after == 3 and r2.status == ScanStatus.complete, f"{n} {calls_after}")

async def failing(subject, sender, snippet=""): calls.append("x"); return {"is_newsletter": False, "is_promotional": False, "confidence": 0, "category": "other", "reason": "boom", "error": "connection refused"}
scanner.classify_email = failing
EM[:] = [mk(i, sub="n") for i in range(10, 16)]; before = len(calls)
r3 = run(imap.id)
check("LLM down: scan stops after 3 failures, marked failed with reason", r3.status == ScanStatus.failed and r3.emails_failed == 3 and "LLM" in (r3.error or "") and len(calls) - before == 3, f"{r3.status} {r3.emails_failed} {r3.error}")

def boom(self, folder, limit): raise Exception("[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
IMAPClient.fetch_emails = boom
r4 = run(imap.id)
check("bad IMAP login gives friendly message", r4.status == ScanStatus.failed and "rejected the login" in r4.error, str(r4.error))
ms = Account(label="m", provider_type=ProviderType.microsoft, email_address="m@o.c", imap_host="outlook.office365.com", imap_port=993,
             imap_username="m@o.c", access_token=encrypt("old"), refresh_token=encrypt("r"), token_expires_at=datetime.utcnow() - timedelta(hours=1))
ms2 = Account(label="m2", provider_type=ProviderType.microsoft, email_address="m2@o.c", imap_host="outlook.office365.com", imap_port=993,
              imap_username="m2@o.c", access_token=encrypt("old"), token_expires_at=datetime.utcnow() - timedelta(hours=1))
db.add_all([ms, ms2]); db.commit()
r5 = run(ms.id); r6 = run(ms2.id)
check("expired Microsoft token + no client secret -> clear message", r5.status == ScanStatus.failed and "client secret is missing" in r5.error, str(r5.error))
check("expired token + no refresh token -> clear message", r6.status == ScanStatus.failed and "connect it again" in r6.error, str(r6.error))
types = {t for (t,) in db.query(AuditEvent.event_type).all()}
check("audit has scan_completed and scan_failed", {"scan_completed", "scan_failed"} <= types, str(types))
leak = db.query(AuditEvent).filter(AuditEvent.detail.ilike("%pw%")).count()
check("no secret in scan audit events", leak == 0)
print(f"\n{ok} passed, {fail} failed")
