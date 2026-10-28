import os, subprocess
from tests import _env; _env.setup()  # fresh scratch database + migrations
from app.core.database import SessionLocal, engine
assert str(engine.url).endswith("unsubvault_test"), "NOT scratch DB"
from fastapi import HTTPException
from app.core import app_settings
from app.core.crypto import encrypt
from app.models.account import Account, ProviderType
from app.models.audit_event import AuditEvent
from app.models.email_record import EmailAction, EmailRecord
from app.models.scan_run import ScanRun, ScanStatus
import app.services.imap_client as ic
from app.api import spam as spam_api
ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

class FakeServer:
    log = []; mailbox = {"<a@x>": [11], "<b@x>": [12], "<c@x>": []}; folders = [((b"\\HasNoChildren",), "/", "Inbox"), ((b"\\Junk",), "/", "Junk Email"), ((), "/", "Archive")]
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def login(self, *a): pass
    def oauth2_login(self, *a): pass
    def list_folders(self): return FakeServer.folders
    def select_folder(self, name, readonly=False): FakeServer.log.append(("select", name, readonly))
    def search(self, crit):  # real IMAP semantics: case-insensitive SUBSTRING match
        return [u for mid, us in FakeServer.mailbox.items() if crit[2].lower() in mid.lower() for u in us]
    def fetch(self, uids, parts):
        by_uid = {u: mid for mid, us in FakeServer.mailbox.items() for u in us}
        return {u: {b"BODY[HEADER.FIELDS (MESSAGE-ID)]": f"Message-ID: {by_uid[u]}\r\n\r\n".encode()} for u in uids}
    def move(self, uids, dest): FakeServer.log.append(("move", list(uids), dest))
ic._IMAPClient = FakeServer
c = ic.IMAPClient("h", 993, "u", "p")
FakeServer.log.clear(); r = c.move_to_junk("Inbox", ["<a@x>", "<b@x>", "<c@x>"], dry_run=True)
check("dry run opens READ-ONLY and never moves", ("select", "Inbox", True) in FakeServer.log and not any(x[0] == "move" for x in FakeServer.log))
check("dry run reports found/missing and the Junk folder (by \\Junk flag)", r["found"] == ["<a@x>", "<b@x>"] and r["missing"] == ["<c@x>"] and r["junk_folder"] == "Junk Email")
FakeServer.log.clear(); r = c.move_to_junk("Inbox", ["<a@x>", "<b@x>", "<c@x>"], dry_run=False)
check("live run opens read-write and moves exactly the found messages to Junk", ("select", "Inbox", False) in FakeServer.log and ("move", [11, 12], "Junk Email") in FakeServer.log)
FakeServer.folders = [((), "/", "Inbox"), ((), "/", "Spam")]
check("falls back to a folder NAMED Spam when there is no \\Junk flag", c.move_to_junk("Inbox", ["<a@x>"], dry_run=True)["junk_folder"] == "Spam")
FakeServer.folders = [((), "/", "Inbox")]
try: c.move_to_junk("Inbox", ["<a@x>"]); check("no Junk folder -> clear error", False)
except ValueError as e: check("no Junk folder -> clear error", "Junk folder" in str(e))
FakeServer.folders = [((b"\\Junk",), "/", "Junk Email"), ((), "/", "Inbox")]
try: c.move_to_junk("Junk Email", ["<a@x>"]); check("refuses to 'move' from Junk into Junk", False)
except ValueError: check("refuses to 'move' from Junk into Junk", True)

db = SessionLocal()
acct = Account(label="t", provider_type=ProviderType.imap, email_address="a@b.c", imap_host="h", imap_port=993, imap_username="u", imap_password_encrypted=encrypt("p"))
db.add(acct); db.commit()
runs = {f: ScanRun(account_id=acct.id, folder=f, dry_run=True, status=ScanStatus.complete) for f in ("Inbox", "Junk", "Trash")}
db.add_all(runs.values()); db.commit()
def rec(mid, folder, cat="spam", method="spam_skipped"):
    r = EmailRecord(account_id=acct.id, scan_run_id=runs[folder].id, message_id=mid, subject=f"s {mid}", sender_email="x@y.z", category=cat, action=EmailAction.none, unsubscribe_method=method)
    db.add(r); db.commit(); return r
a, b, cm = rec("<a@x>", "Inbox"), rec("<b@x>", "Inbox"), rec("<c@x>", "Inbox")
inJunk, inTrash, notSpam, done = rec("<j@x>", "Junk"), rec("<t@x>", "Trash"), rec("<n@x>", "Inbox", cat="promotional", method="pending_review"), rec("<d@x>", "Inbox", method="moved_to_junk")
FakeServer.folders = [((b"\\Junk",), "/", "Junk Email"), ((), "/", "Inbox")]; FakeServer.log.clear()
cands = spam_api.candidates(db)
check("candidates: only unmoved spam in normal folders (3 of 7)", cands["count"] == 3 and {i["id"] for i in cands["items"]} == {a.id, b.id, cm.id}, str(cands["count"]))
check("candidates exclude Junk, Trash, non-spam and already-moved", not ({inJunk.id, inTrash.id, notSpam.id, done.id} & {i["id"] for i in cands["items"]}))
app_settings.update({"dry_run": True})
res = spam_api.move(spam_api.MoveRequest(ids=[a.id, b.id, cm.id]), None, db); db.expire_all()
check("server dry-run: nothing moved, records untouched", res["dry_run"] and res["moved"] == 0 and res["found"] == 2 and db.get(EmailRecord, a.id).unsubscribe_method == "spam_skipped" and not any(x[0] == "move" for x in FakeServer.log), str(res))
check("dry-run flags messages missing from the folder", db.get(EmailRecord, cm.id).unsubscribe_method == "not_in_folder")
app_settings.update({"dry_run": False}); FakeServer.log.clear()
res = spam_api.move(spam_api.MoveRequest(ids=[a.id, b.id]), None, db); db.expire_all()
check("live: moves both and marks them moved", res["moved"] == 2 and res["junk_folder"] == "Junk Email" and db.get(EmailRecord, a.id).unsubscribe_method == "moved_to_junk" and ("move", [11, 12], "Junk Email") in FakeServer.log, str(res))
check("moved messages are no longer candidates", spam_api.candidates(db)["count"] == 0)
try: spam_api.move(spam_api.MoveRequest(ids=[a.id, inJunk.id]), None, db); check("cannot move messages that are not eligible", False)
except HTTPException as e: check("cannot move messages that are not eligible", e.status_code == 400)
check("audit logged with counts only (no subjects/senders)", all("x@y.z" not in (e.detail or "") and "s <" not in (e.detail or "") for e in db.query(AuditEvent).filter(AuditEvent.event_type == "spam_moved_to_junk")) and db.query(AuditEvent).filter(AuditEvent.event_type == "spam_moved_to_junk").count() == 2)
print(f"\n{ok} passed, {fail} failed")
