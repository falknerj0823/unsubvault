import asyncio, json, os
from datetime import datetime, timedelta
from tests import _env; _env.setup()  # fresh scratch database + migrations
from fastapi import HTTPException
from app.core import app_settings
from app.core.crypto import encrypt
from app.core.database import SessionLocal
from app.models.account import Account, ProviderType
from app.models.audit_event import AuditEvent
from app.models.email_record import EmailAction, EmailRecord
from app.models.scan_run import ScanRun, ScanStatus
from app.models.sender_check import SenderCheck
from app.models.sender_rule import SenderRule
from app.api import emails as emails_api, unsubscribe as unsub_api
from app.services import bulk_unsub, scanner, sender_check as sc
from app.services.domains import brand_mismatch
from app.services.imap_client import IMAPClient, RawEmail

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

# ---- brand/domain mismatch heuristic
for name, addr, want in [("Orbit Rewards", "orbitrewards@points-mail.example", True), ("The AcmeVPN team", "no-reply@mail.acmevpn.example", False),
        ("Widgetco | Free Offers", "specials@e.widgetco.example", False), ("BigBank Life Insurance Company", "offers@mail.bigbank.example", False),
        ("Pat Example", "inmail-hit-reply@jobsboard.example", False), ("Credit Site", "mail@mail.creditsite.example", False),
        ("Travelco.com", "mail@eg.travelco.example", False), ("PayPal Support", "service@paypa1-secure.net", True),
        ("Netflix Billing", "billing@account-verify.ru", True), ("", "x@y.com", False), ("Payco", "@payco.example", False),
        ("DesignTool Studio", "designtool@designtoolcommunications.example", False), ("DIGEST", "dan@digestnewsletter.example", False)]:
    check(f"brand_mismatch({name!r}, {addr}) is {want}", brand_mismatch(name, addr) is want)

from app.services.domains import brand_tokens
check("brand tokens drop generic words (so 'rewards' does not match unrelated stores)", brand_tokens('Orbit Rewards') == ['orbit'] and brand_tokens('The AcmeVPN team') == ['acmevpn'] and brand_tokens('Offers | Deals') == [])

# ---- parsers
check("SPF: -all parsed as fail policy", sc.parse_spf(["v=spf1 include:x.com ip4:1.2.3.4 -all"]) == {"present": True, "policy": "fail"})
check("SPF: absent and softfail", sc.parse_spf(["something else"]) == {"present": False, "policy": None} and sc.parse_spf(["v=spf1 ~all"])["policy"] == "softfail")
check("DMARC: policy read", sc.parse_dmarc(["v=DMARC1; p=Reject; rua=mailto:x@y.z"]) == {"present": True, "policy": "reject"} and not sc.parse_dmarc([])["present"])
a = sc.parse_auth("mx.example; spf=pass smtp.mailfrom=a.com; dkim=pass header.d=points-mail.example header.s=k; dmarc=pass action=none")
check("Authentication-Results parsed (spf/dkim/dmarc/domain)", a == {"spf": "pass", "dkim": "pass", "dmarc": "pass", "dkim_domain": "points-mail.example"}, str(a))
check("failed DKIM gives no verified domain", sc.parse_auth("dkim=fail header.d=x.com")["dkim_domain"] is None)
check("RDAP registration date parsed", sc.parse_rdap_age(json.dumps({"events": [{"eventAction": "last changed", "eventDate": "2024-01-01T00:00:00Z"}, {"eventAction": "registration", "eventDate": "2014-01-27T13:30:48Z"}]}).encode()) == datetime(2014, 1, 27, 13, 30, 48))
check("RDAP junk is ignored, not fatal", sc.parse_rdap_age(b"not json") is None and sc.parse_rdap_age(b"{}") is None)

# ---- domain facts are cached
db = SessionLocal()
calls = {"dns": 0, "rdap": 0}
def fake_dns(name, rtype): calls["dns"] += 1; return ['10 inbound.exacttarget.com.'] if rtype == "MX" else []
def fake_txt(name): calls["dns"] += 1; return ["v=DMARC1; p=reject"] if name.startswith("_dmarc") else ["v=spf1 include:x -all"]
async def fake_reg(domain): calls["rdap"] += 1; return datetime.utcnow() - timedelta(days=4400)
sc._dns, sc._txt, sc.registration_date = fake_dns, fake_txt, fake_reg
f1 = asyncio.run(sc.domain_facts(db, "mail.points-mail.example"))
check("domain facts gathered for the registrable domain", f1["domain"] == "points-mail.example" and f1["spf"]["policy"] == "fail" and f1["dmarc"]["policy"] == "reject" and f1["age_days"] > 4000 and f1["mx"] == ["inbound.exacttarget.com"])
n = dict(calls); f2 = asyncio.run(sc.domain_facts(db, "points-mail.example"))
check("second lookup is served from the cache (no DNS/RDAP)", calls == n and f2 == f1)
db.query(SenderCheck).update({"checked_at": datetime.utcnow() - timedelta(days=40)}); db.commit()
asyncio.run(sc.domain_facts(db, "points-mail.example"))
check("cache expires after 30 days", calls["rdap"] == 2)

# ---- verdicts
good = {"domain": "points-mail.example", "spf": {"present": True, "policy": "fail"}, "dmarc": {"present": True, "policy": "reject"}, "age_days": 4400, "registered": "2014-01-27"}
r = sc.evaluate("points-mail.example", "Orbit Rewards", "orbitrewards@points-mail.example", good, {"spf": "pass", "dkim": "pass", "dmarc": "pass", "dkim_domain": "points-mail.example"},
                [{"domain": "points-mail.example", "dkim_domain": "points-mail.example", "count": 2}, {"domain": "skyair.example", "dkim_domain": "skyair.example", "count": 20}])
check("signed, aged, enforced domain = authentic (even with a name mismatch)", r["verdict"] == "legitimate" and r["score"] >= 3, str(r["score"]))
check("name mismatch is mentioned, other-domain history is noted", any("does not appear in the domain" in x["text"] for x in r["reasons"]) and any("skyair.example" in x["text"] for x in r["reasons"]))
bad = {"domain": "x.biz", "spf": {"present": False, "policy": None}, "dmarc": {"present": False, "policy": None}, "age_days": 10, "registered": "2026-10-18"}
r = sc.evaluate("x.biz", "Casino Bonus", "a@x.biz", bad, {"dkim": None, "dmarc": None, "spf": None, "dkim_domain": None}, None)
check("brand-new, unauthenticated domain = suspicious", r["verdict"] == "suspicious", str(r))
r = sc.evaluate("points-mail.example", "A", "a@points-mail.example", good, {"spf": "pass", "dkim": "fail", "dmarc": "fail", "dkim_domain": None}, None)
check("a failed signature outweighs a good-looking domain", r["verdict"] == "suspicious", str(r["score"]))
r = sc.evaluate("points-mail.example", "A", "a@points-mail.example", {**good, "age_days": 200, "dmarc": {"present": False, "policy": None}}, None, None)
check("no message to read + middling domain = unclear", r["verdict"] == "unclear" and any("could not be read" in x["text"] for x in r["reasons"]), str(r["score"]))
check("summary is short and states the verdict", r["summary"].startswith("Unclear") and len(r["summary"]) <= 200)

# ---- verify endpoint (IMAP mocked)
acct = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="h", imap_port=993, imap_username="u", imap_password_encrypted=encrypt("p"))
db.add(acct); db.commit()
run = ScanRun(account_id=acct.id, folder="Inbox", dry_run=True, status=ScanStatus.complete); db.add(run); db.commit()
def rec(mid, sender, name, cat="spam", action=EmailAction.none, url="https://x.example/u"):
    r = EmailRecord(account_id=acct.id, scan_run_id=run.id, message_id=mid, subject="s " + mid, sender_name=name, sender_email=sender, category=cat, action=action,
                    unsubscribe_url=url, confidence=.9, unsubscribe_method="spam_skipped" if cat == "spam" else "pending_review")
    db.add(r); db.commit(); return r
a1, a2 = rec("<a1>", "orbitrewards@points-mail.example", "Orbit Rewards"), rec("<a2>", "orbitrewards@points-mail.example", "Orbit Rewards")
class FakeClient:
    def read_auth_results(self, folder, mid): assert folder == "Inbox"; return "dkim=pass header.d=points-mail.example; dmarc=pass; spf=pass"
    def sender_history(self, tokens): assert "orbit" in tokens; return [{"domain": "points-mail.example", "dkim_domain": "points-mail.example", "count": 2, "newest": "2026-10-27", "oldest": "2026-10-01"}]
scanner._client_for = lambda acct, db: FakeClient()
class Rq: headers = {}; client = None
out = asyncio.run(emails_api.verify_sender(a1.id, Rq(), False, db)); db.expire_all()
check("verify returns verdict, reasons, facts, history and the caveat", out["verdict"] == "legitimate" and out["facts"]["age_days"] > 4000 and out["history"] and "does not prove" in out["caveat"])
check("verdict is stored on every email from that sender", db.get(EmailRecord, a1.id).verify_verdict == "legitimate" and db.get(EmailRecord, a2.id).verify_verdict == "legitimate" and db.get(EmailRecord, a2.id).verify_summary)
async def fake_explain(evidence): assert "subject" not in json.dumps(evidence).lower() and "body" not in evidence; return "Looks like routine vendor marketing."
sc.explain = fake_explain
out = asyncio.run(emails_api.verify_sender(a1.id, Rq(), True, db))
check("model explanation is optional and gets facts only (no email content)", out["explanation"].startswith("Looks like"))
async def broken_explain(evidence): raise RuntimeError("model offline")
sc.explain = broken_explain
out = asyncio.run(emails_api.verify_sender(a1.id, Rq(), True, db))
check("a failing model does not break verification", out["verdict"] == "legitimate" and "model offline" in out["explanation_error"])
class DeadClient:
    def read_auth_results(self, *a): raise ConnectionError("mail server unreachable")
    def sender_history(self, *a): raise ConnectionError("x")
scanner._client_for = lambda acct, db: DeadClient()
out = asyncio.run(emails_api.verify_sender(a1.id, Rq(), False, db))
check("mailbox failure falls back to domain-only checks with a note", out["notes"] and out["verdict"] in ("legitimate", "unclear"))
check("audit has domain and verdict only", all("Orbit" not in (e.detail or "") and "s <a1>" not in (e.detail or "") for e in db.query(AuditEvent).filter(AuditEvent.event_type == "sender_verified")) and db.query(AuditEvent).filter(AuditEvent.event_type == "sender_verified").count() == 4)
try: asyncio.run(emails_api.verify_sender(99999, Rq(), False, db)); check("unknown email -> 404", False)
except HTTPException as e: check("unknown email -> 404", e.status_code == 404)

# ---- Not spam
class R2: headers = {}; client = None
res = emails_api.not_spam(a1.id, R2(), db); db.expire_all()
check("not spam: sender's emails become promotional and pending review", res["emails"] == 2 and db.get(EmailRecord, a1.id).category == "promotional" and db.get(EmailRecord, a1.id).action == EmailAction.unsubscribe_pending)
check("not spam: sender now appears in the review list", "orbitrewards@points-mail.example" in {g["sender_email"] for g in bulk_unsub.sender_groups(db)})
check("not spam: rule remembered", db.query(SenderRule).filter(SenderRule.decision == "not_spam").count() == 1)
check("review group carries mismatch flag, verdict and a record id", [g for g in bulk_unsub.sender_groups(db) if g["sender_email"].startswith("orbit")][0]["brand_mismatch"] and [g for g in bulk_unsub.sender_groups(db)][0]["record_id"])
EM = [RawEmail(uid=1, message_id="<new1>", subject="110% more points", sender_name="Orbit Rewards", sender_email="orbitrewards@points-mail.example", received_at=None,
               list_unsubscribe="<https://x.example/u>", snippet="b", auth_results="dkim=pass header.d=points-mail.example; dmarc=pass")]
IMAPClient.fetch_emails = lambda self, folder, limit: iter(EM[:limit])
async def says_spam(subject, sender, snippet=""): return {"is_spam": True, "category": "spam", "confidence": .9, "reason": "domain suspicious"}
scanner.classify_email = says_spam
scanner._client_for = lambda acct, db: IMAPClient("h", 993, "u", "p")
def run_scan():
    r = ScanRun(account_id=acct.id, folder="Inbox", dry_run=True, status=ScanStatus.pending); db.add(r); db.commit(); scanner.run_scan(r.id); db.expire_all(); return db.get(ScanRun, r.id)
r = run_scan(); new = db.query(EmailRecord).filter(EmailRecord.message_id == "<new1>").first()
check("a not-spam rule overrides the model's spam verdict on later scans", r.status == ScanStatus.complete and new.category == "promotional" and new.action == EmailAction.unsubscribe_pending, f"{new.category} {new.action}")
rule = db.query(SenderRule).filter(SenderRule.decision == "not_spam").first(); bulk_unsub.undo_safe(db, rule); db.expire_all()
check("undo puts the spam label back", db.get(EmailRecord, a1.id).category == "spam" and db.get(EmailRecord, a1.id).action == EmailAction.none)
try: emails_api.not_spam(new.id, R2(), db); check("not-spam on non-spam is refused", False)
except HTTPException as e: check("not-spam on non-spam is refused", e.status_code == 404)
mini = EmailRecord(account_id=acct.id, message_id="<m>", sender_email="@domain.com", category="spam", action=EmailAction.none); db.add(mini); db.commit()
try: emails_api.not_spam(mini.id, R2(), db); check("minimized senders cannot be reclassified", False)
except HTTPException as e: check("minimized senders cannot be reclassified", e.status_code == 400)
bulk_unsub.mark_safe(db, acct.id, "orbitrewards@points-mail.example", decision="keep"); db.expire_all()
check("switching a sender from not-spam to safe works", db.query(SenderRule).filter(SenderRule.sender_email == "orbitrewards@points-mail.example").one().decision == "keep" and db.get(EmailRecord, a1.id).category == "kept")

# ---- automatic verification during scans
def fresh_account():
    a = Account(label="t2", provider_type=ProviderType.imap, email_address="z@b.c", imap_host="h", imap_port=993, imap_username="u", imap_password_encrypted=encrypt("p")); db.add(a); db.commit(); return a
acct2 = fresh_account()
EM[:] = [RawEmail(uid=2, message_id="<auto1>", subject="Win big", sender_name="Casino Bonus", sender_email="x@throwaway.biz", received_at=None, list_unsubscribe="<https://t.biz/u>",
                  snippet="b", auth_results="dkim=none"),
         RawEmail(uid=3, message_id="<auto2>", subject="Weekly", sender_name="The Daily Planet", sender_email="news@planetmail.com", received_at=None, list_unsubscribe="<https://p.com/u>",
                  snippet="b", auth_results="dkim=pass header.d=planetmail.com")]
async def spam_then_promo(subject, sender, snippet=""):
    return {"is_spam": True, "category": "spam", "confidence": .9, "reason": "x"} if subject == "Win big" else {"is_newsletter": True, "category": "newsletter", "confidence": .9, "reason": "n"}
scanner.classify_email = spam_then_promo
async def facts_stub(db_, domain): return {**bad, "domain": domain}
sc.domain_facts = facts_stub
def run_scan2():
    r = ScanRun(account_id=acct2.id, folder="Inbox", dry_run=True, status=ScanStatus.pending); db.add(r); db.commit(); scanner.run_scan(r.id); db.expire_all(); return db.get(ScanRun, r.id)
app_settings.update({"auto_verify": False}); run_scan2()
check("auto verify off: no verdicts are computed", all(r.verify_verdict is None for r in db.query(EmailRecord).filter(EmailRecord.account_id == acct2.id)))
db.query(EmailRecord).filter(EmailRecord.account_id == acct2.id).delete(); db.commit()
app_settings.update({"auto_verify": True}); r = run_scan2(); recs = {x.message_id: x for x in db.query(EmailRecord).filter(EmailRecord.account_id == acct2.id)}
check("auto verify on: flagged spam gets a verdict stored with the record", r.status == ScanStatus.complete and recs["<auto1>"].verify_verdict == "suspicious", str(recs["<auto1>"].verify_verdict))
check("auto verify on: a normal, matching newsletter is not looked up", recs["<auto2>"].verify_verdict is None)
async def exploding(db_, domain): raise RuntimeError("dns down")
sc.domain_facts = exploding
db.query(EmailRecord).filter(EmailRecord.account_id == acct2.id).delete(); db.commit()
r = run_scan2()
check("a verification failure never fails the scan", r.status == ScanStatus.complete and db.query(EmailRecord).filter(EmailRecord.account_id == acct2.id).count() == 2)

# ---- "Done by me"
db.add(EmailRecord(account_id=acct.id, message_id="<d1>", subject="x", sender_email="m@manual.example", category="promotional", action=EmailAction.unsubscribe_pending, unsubscribe_url="mailto:u@manual.example"))
db.commit()
res = unsub_api.mark_done(unsub_api.DoneRequest(senders=[unsub_api.SenderRef(account_id=acct.id, sender_email="M@Manual.example")]), R2(), db); db.expire_all()
d = db.query(EmailRecord).filter(EmailRecord.message_id == "<d1>").one()
check("done by me: marks pending mail unsubscribed (case-insensitive) with a manual record", res["emails"] == 1 and d.action == EmailAction.unsubscribed and d.unsubscribe_result == "manual_done" and d.unsubscribed_at)
check("done by me: leaves the review queue and audits domains only", "m@manual.example" not in {g["sender_email"] for g in bulk_unsub.sender_groups(db)} and all("m@manual" not in (e.detail or "") for e in db.query(AuditEvent).filter(AuditEvent.event_type == "unsubscribe_marked_done")))
print(f"\n{ok} passed, {fail} failed")
