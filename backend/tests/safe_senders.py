import os, subprocess, json
from datetime import datetime, timedelta
from tests import _env; _env.setup()  # fresh scratch database + migrations
from app.core.database import SessionLocal, engine
assert str(engine.url).endswith("unsubvault_test"), "NOT scratch DB"
from fastapi import BackgroundTasks, HTTPException
from app.core import app_settings
from app.core.crypto import encrypt
from app.models.account import Account, ProviderType
from app.models.email_record import EmailAction, EmailRecord
from app.models.scan_run import ScanRun, ScanStatus
from app.models.sender_rule import SenderRule
from app.models.audit_event import AuditEvent
from app.models.unsub_job import UnsubJob
from app.services import scanner, bulk_unsub, unsubscriber
from app.services.domains import root_domain, minimized_sender
from app.services.imap_client import IMAPClient, RawEmail
from app.api import unsubscribe as unsub_api, settings as settings_api
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

for a, b in (("eg.travelco.example", "travelco.example"), ("offers@mail.bigbank.example", "bigbank.example"), ("a@mail.foo.co.uk", "foo.co.uk"), ("x.com", "x.com"), ("@account.bigbank.example", "bigbank.example"), ("US@Example.COM", "example.com")):
    check(f"root_domain({a}) = {b}", root_domain(a) == b, root_domain(a))
check("minimized_sender keeps only the company", minimized_sender("Pay.Support@Billing.CardCo.example") == "@billing.cardco.example")

db = SessionLocal()
acct = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="h", imap_port=993, imap_username="a@b.c", imap_password_encrypted=encrypt("p"))
db.add(acct); db.commit()
def mk(i, sender, subj): return RawEmail(uid=i, message_id=f"<m{i}@x>", subject=subj, sender_name=f"Name {i}", sender_email=sender, received_at=None,
                                          list_unsubscribe="<https://x.com/u?t=TOK>", snippet="body", list_unsubscribe_post="List-Unsubscribe=One-Click")
EM = [mk(1, "offers@mail.bigbank.example", "Life insurance offer"), mk(2, "alerts@account.bigbank.example", "Your payment is due"),
      mk(3, "points@points-mail.example", "Up to 110% more points"), mk(4, "news@real.com", "Weekly digest"), mk(5, "hr@person.com", "Hi Sam, quick question")]
IMAPClient.fetch_emails = lambda self, folder, limit: iter(EM[:limit])
calls = []
async def fake(subject, sender, snippet=""):
    calls.append(subject)
    return {"Life insurance offer": {"is_promotional": True, "category": "promotional", "confidence": .95, "reason": "insurance marketing"},
            "Your payment is due": {"is_promotional": True, "category": "transactional", "confidence": .95, "reason": "payment notice from BigBank, account 1234"},
            "Up to 110% more points": {"is_spam": True, "category": "spam", "confidence": .9, "reason": "generic domain"},
            "Weekly digest": {"is_newsletter": True, "category": "newsletter", "confidence": .9, "reason": "newsletter"},
            "Hi Sam, quick question": {"is_newsletter": True, "category": "personal", "confidence": .8, "reason": "recruiter outreach"}}[subject]
scanner.classify_email = fake
def run():
    r = ScanRun(account_id=acct.id, folder="INBOX", dry_run=True, status=ScanStatus.pending); db.add(r); db.commit()
    scanner.run_scan(r.id); db.expire_all(); return db.get(ScanRun, r.id)
r = run(); rec = {x.message_id: x for x in db.query(EmailRecord).all()}
check("scan completes", r.status == ScanStatus.complete, str(r.error))
t, p, s_, n, h = (rec[f"<m{i}@x>"] for i in range(2, 7)) if False else (rec["<m2@x>"], rec["<m1@x>"], rec["<m3@x>"], rec["<m4@x>"], rec["<m5@x>"])
check("receipt/notice stores NO subject, name, reason or link", (t.subject, t.sender_name, t.classification_reason, t.unsubscribe_url) == (None, None, None, None))
check("receipt stores only the company domain", t.sender_email == "@account.bigbank.example" and t.unsubscribe_method == "minimized")
check("personal mail is minimized too", (h.subject, h.sender_name, h.classification_reason) == (None, None, None) and h.sender_email == "@person.com" and h.action == EmailAction.none)
check("marketing keeps subject/name/reason for review", p.subject == "Life insurance offer" and p.classification_reason == "insurance marketing" and p.action == EmailAction.unsubscribe_pending)
check("spam keeps its subject so false positives can be rescued", s_.subject == "Up to 110% more points" and s_.category == "spam")
g = {x["sender_email"]: x for x in bulk_unsub.sender_groups(db)}
check("mixed sender: BigBank marketing flagged because BigBank account mail exists", g["offers@mail.bigbank.example"]["mixed_count"] == 1 and g["news@real.com"]["mixed_count"] == 0)
check("review rows carry the model's reason and sample subjects", g["news@real.com"]["reason"] == "newsletter" and g["news@real.com"]["samples"][0]["subject"] == "Weekly digest")

# ---- safe sender: marketing sender
changed = bulk_unsub.mark_safe(db, acct.id, "News@Real.com")
db.expire_all(); n = db.get(EmailRecord, n.id)
check("safe sender relabels stored mail (case-insensitive) and removes it from review", changed == 1 and n.category == "kept" and n.action == EmailAction.none and "news@real.com" not in {x["sender_email"] for x in bulk_unsub.sender_groups(db)})
check("rule remembers what it overrode", n.prior_category == "newsletter" and n.prior_action == "unsubscribe_pending")
# ---- safe sender: rescue a spam false positive (a loyalty-program vendor domain)
bulk_unsub.mark_safe(db, acct.id, "points@points-mail.example"); db.expire_all(); s_ = db.get(EmailRecord, s_.id)
check("spam false positive can be rescued", s_.category == "kept" and s_.prior_category == "spam")
# ---- later scan: kept senders are not re-classified and nothing is stored beyond the company
EM[:] = [mk(10, "news@real.com", "Another digest"), mk(11, "points@points-mail.example", "Bonus points!"), mk(12, "offers@mail.bigbank.example", "More insurance")]
calls.clear()
async def fake2(subject, sender, snippet=""):
    calls.append(subject); return {"is_promotional": True, "category": "promotional", "confidence": .9, "reason": "m"}
scanner.classify_email = fake2
r2 = run(); db.expire_all()
check("kept senders never reach the LLM; others still do", calls == ["More insurance"], str(calls))
k = db.query(EmailRecord).filter(EmailRecord.message_id == "<m10@x>").first()
check("auto-kept mail stores only the company, not pending", k.subject is None and k.sender_email == "@real.com" and k.category == "kept" and k.action == EmailAction.none)
# ---- undo
rule = db.query(SenderRule).filter(SenderRule.sender_email == "news@real.com").first(); rid = rule.id
restored = bulk_unsub.undo_safe(db, rule); db.expire_all(); n = db.get(EmailRecord, n.id)
check("undo restores the original classification and review status", restored == 1 and n.category == "newsletter" and n.action == EmailAction.unsubscribe_pending and "news@real.com" in {x["sender_email"] for x in bulk_unsub.sender_groups(db)})
check("undo removes the rule", db.query(SenderRule).filter(SenderRule.id == rid).count() == 0)
rule2 = db.query(SenderRule).filter(SenderRule.sender_email == "points@points-mail.example").first(); bulk_unsub.undo_safe(db, rule2); db.expire_all()
check("undoing a rescue puts the spam label back", db.get(EmailRecord, s_.id).category == "spam")
# ---- API guards
try: unsub_api.keep(unsub_api.KeepRequest(senders=[unsub_api.SenderRef(account_id=acct.id, sender_email="@account.bigbank.example")]), None, db); check("API refuses company-only senders", False)
except HTTPException as e: check("API refuses company-only senders", e.status_code == 400)
res = unsub_api.keep(unsub_api.KeepRequest(senders=[unsub_api.SenderRef(account_id=acct.id, sender_email="hr@person.com")]), None, db)
check("API keep works for a normal sender and audits without addresses", res["senders"] == 1 and any(json.loads(e.detail)["domains"] == ["person.com"] for e in db.query(AuditEvent).filter(AuditEvent.event_type == "safe_sender_added")))
# ---- exact sender matching in a bulk job (underscore is a SQL wildcard in ILIKE)
for i, addr in ((20, "no_reply@wild.com"), (21, "noxreply@wild.com")):
    db.add(EmailRecord(account_id=acct.id, message_id=f"<w{i}>", subject="s", sender_email=addr, category="promotional", confidence=.9, action=EmailAction.unsubscribe_pending, unsubscribe_url="https://wild.com/u", unsubscribe_one_click=True))
db.commit()
async def okreq(method, url, form=None): return 200, url
unsubscriber.safe_request = okreq; bulk_unsub.DELAY_BETWEEN_SENDERS = 0
j = UnsubJob(status="pending", dry_run=False, selection=json.dumps([[acct.id, "no_reply@wild.com"]]), total=1); db.add(j); db.commit()
bulk_unsub.run_job(j.id); db.expire_all()
act = lambda a: db.query(EmailRecord).filter(EmailRecord.sender_email == a).first().action
check("bulk job touches exactly the chosen sender (no wildcard bleed)", act("no_reply@wild.com") == EmailAction.unsubscribed and act("noxreply@wild.com") == EmailAction.unsubscribe_pending)
# ---- retention + purge
old = datetime.utcnow() - timedelta(days=60)
for i, (action, cat) in enumerate(((EmailAction.none, "spam"), (EmailAction.unsubscribe_pending, "promotional"), (EmailAction.unsubscribed, "promotional"))):
    db.add(EmailRecord(account_id=acct.id, message_id=f"<old{i}>", subject="o", sender_email=f"o{i}@old.com", category=cat, action=action, created_at=old))
db.commit()
before = db.query(EmailRecord).count()
check("retention 0 = keep forever", scanner.purge_old_records(db) == 0 and db.query(EmailRecord).count() == before)
app_settings.update({"scan_retention_days": 30})
deleted = scanner.purge_old_records(db)
check("retention deletes old non-pending records only (2 of 3)", deleted == 2 and db.query(EmailRecord).filter(EmailRecord.message_id == "<old1>").count() == 1, str(deleted))
check("retention never deletes recent records", db.query(EmailRecord).count() == before - 2 + 0)
# ---- delete all scan data
res = settings_api.delete_scan_data(None, db)
check("delete-all wipes records, scans and finished runs", db.query(EmailRecord).count() == 0 and db.query(ScanRun).count() == 0 and res["emails"] > 0)
check("delete-all keeps accounts and safe-sender rules", db.query(Account).count() == 1 and db.query(SenderRule).count() >= 1)
check("delete-all is audited with counts only", db.query(AuditEvent).filter(AuditEvent.event_type == "scan_data_deleted").count() == 1)
print(f"\n{ok} passed, {fail} failed")
