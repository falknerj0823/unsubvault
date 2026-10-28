import os, subprocess
from tests import _env; _env.setup()  # fresh scratch database + migrations
from app.core.database import SessionLocal, engine
assert str(engine.url).endswith("unsubvault_test"), "NOT scratch DB"
from app.core.crypto import encrypt
from app.models.account import Account, ProviderType
from app.models.scan_run import ScanRun, ScanStatus
from app.models.unsub_job import UnsubJob
from app.services.scanner import _reviewable, recover_interrupted
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
check("promotional is reviewable", _reviewable({"category": "promotional", "is_promotional": True}, False))
check("newsletter is reviewable", _reviewable({"category": "newsletter", "is_newsletter": True}, False))
check("transactional never reviewable, even with promo flag", not _reviewable({"category": "transactional", "is_promotional": True, "is_newsletter": True}, False))
check("personal never reviewable, even with newsletter flag", not _reviewable({"category": "Personal", "is_newsletter": True}, False))
check("spam never reviewable", not _reviewable({"category": "promotional", "is_promotional": True}, True))
check("other with no flags not reviewable", not _reviewable({"category": "other"}, False))
db = SessionLocal()
a = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="h", imap_port=993, imap_username="u", imap_password_encrypted=encrypt("p"))
db.add(a); db.commit()
runs = [ScanRun(account_id=a.id, folder="INBOX", status=s, dry_run=True) for s in (ScanStatus.running, ScanStatus.pending, ScanStatus.complete)]
jobs = [UnsubJob(status=s, dry_run=True, selection="[]") for s in ("running", "complete")]
db.add_all(runs + jobs); db.commit()
res = recover_interrupted(); db.expire_all()
st = [db.get(ScanRun, r.id).status for r in runs]
check("running + pending scans marked failed, complete untouched", st == [ScanStatus.failed, ScanStatus.failed, ScanStatus.complete], str(st))
check("failed scans explain why and have a finish time", all("restarted" in db.get(ScanRun, r.id).error and db.get(ScanRun, r.id).completed_at for r in runs[:2]))
check("running job failed, complete job untouched", (db.get(UnsubJob, jobs[0].id).status, db.get(UnsubJob, jobs[1].id).status) == ("failed", "complete"))
check("returns counts", res == {"scans": 2, "unsubscribe_jobs": 1}, str(res))
check("second call is a no-op", recover_interrupted() == {"scans": 0, "unsubscribe_jobs": 0})
print(f"\n{ok} passed, {fail} failed")
