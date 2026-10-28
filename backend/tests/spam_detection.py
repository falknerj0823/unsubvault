import os, subprocess, json
from tests import _env; _env.setup()  # fresh scratch database + migrations
from app.core.database import SessionLocal, engine
assert str(engine.url).endswith("unsubvault_test"), "NOT scratch DB"
from app.core.crypto import encrypt
from app.models.account import Account, ProviderType
from app.models.email_record import EmailRecord
from app.models.scan_run import ScanRun, ScanStatus
from app.models.audit_event import AuditEvent
from app.services import scanner, classifier, bulk_unsub
from app.services.imap_client import IMAPClient, RawEmail
from app.api.emails import list_emails
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

check("prompt defines spam and asks for is_spam", "is_spam" in classifier.SYSTEM_PROMPT and "casino" in classifier.SYSTEM_PROMPT.lower())
check("JSON in code fences still parses with is_spam", classifier._parse_json('```json\n{"is_spam": true, "category": "spam"}\n```')["is_spam"] is True)

db = SessionLocal()
acct = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="h", imap_port=993, imap_username="a@b.c", imap_password_encrypted=encrypt("pw"))
db.add(acct); db.commit()
def mk(i): return RawEmail(uid=i, message_id=f"<m{i}@x>", subject=f"s{i}", sender_name="N", sender_email=f"n{i}@x{i}.com", received_at=None,
                           list_unsubscribe="<https://x.com/u>", snippet="b", list_unsubscribe_post="List-Unsubscribe=One-Click")
EM = [mk(1), mk(2), mk(3), mk(4)]
IMAPClient.fetch_emails = lambda self, folder, limit: iter(EM[:limit])
calls = []
async def fake(subject, sender, snippet=""):
    calls.append(subject)
    return {"s1": {"is_spam": True, "is_promotional": True, "category": "promotional", "confidence": .97, "reason": "casino"},       # flag only; model also said promotional
            "s2": {"is_spam": False, "category": "spam", "is_promotional": True, "confidence": .9, "reason": "scam"},                 # category only
            "s3": {"is_spam": False, "is_promotional": True, "category": "promotional", "confidence": .9, "reason": "real store"},
            "s4": {"is_spam": False, "is_newsletter": True, "category": "newsletter", "confidence": .9, "reason": "real list"}}[subject]
scanner.classify_email = fake
r = ScanRun(account_id=acct.id, folder="Junk", dry_run=True, status=ScanStatus.pending); db.add(r); db.commit()
scanner.run_scan(r.id); db.expire_all(); r = db.get(ScanRun, r.id)
rec = {x.subject: x for x in db.query(EmailRecord).all()}
check("scan completes", r.status == ScanStatus.complete, str(r.error))
check("spam flagged by is_spam OR by category is stored as spam", rec["s1"].category == "spam" and rec["s2"].category == "spam")
check("spam is never pending for unsubscribe, flags cleared", all(rec[s].action.value == "none" and not rec[s].is_promotional and not rec[s].is_newsletter for s in ("s1", "s2")))
check("spam marked spam_skipped", rec["s1"].unsubscribe_method == "spam_skipped")
check("legit promo/newsletter still pending review", rec["s3"].action.value == "unsubscribe_pending" and rec["s4"].action.value == "unsubscribe_pending")
check("counters: 2 spam, 2 to review", (r.emails_spam, r.emails_found) == (2, 2), str((r.emails_spam, r.emails_found)))
check("spam senders excluded from bulk unsubscribe list", {g["sender_email"] for g in bulk_unsub.sender_groups(db)} == {"n3@x3.com", "n4@x4.com"})
check("one-click header captured for the review senders", all(g["method"] == "one_click" for g in bulk_unsub.sender_groups(db)))
calls.clear(); r2 = ScanRun(account_id=acct.id, folder="Junk", dry_run=True, status=ScanStatus.pending); db.add(r2); db.commit()
scanner.run_scan(r2.id); db.expire_all(); r2 = db.get(ScanRun, r2.id)
check("rescan does not re-send spam (or anything) to the LLM", not calls and r2.emails_known == 4 and r2.emails_spam == 0, f"{calls} {r2.emails_known}")
check("emails list filter category=spam returns only spam", {e["subject"] for e in list_emails(None, "spam", db)} == {"s1", "s2"})
ev = [json.loads(e.detail) for e in db.query(AuditEvent).filter(AuditEvent.event_type == "scan_completed").all()]
check("scan_completed audit includes spam count", ev and ev[0].get("spam") == 2, str(ev))
print(f"\n{ok} passed, {fail} failed")
