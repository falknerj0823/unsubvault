import email, email.header, email.utils, re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Generator
from bs4 import BeautifulSoup
from imapclient import IMAPClient as _IMAPClient

from app.services.domains import root_domain

JUNK_NAMES = {"junk", "junk email", "junk e-mail", "spam", "bulk mail", "[gmail]/spam"}
PEEK_BYTES = 65536  # headers + start of the body; enough for a snippet without downloading attachments
CHUNK = 25

def dkim_pass_domain(auth_results: str) -> Optional[str]:
    """Domain whose DKIM signature the receiving server verified, from the Authentication-Results header."""
    m = re.search(r"dkim=pass[^;]{0,300}?header\.d=([A-Za-z0-9.-]+)", (auth_results or "")[:4000], re.I)
    return m.group(1).lower() if m else None

_KNOWN_PROVIDER_HOSTS = ("office365.com", "outlook.com", "gmail.com", "googlemail.com", "google.com")

def trusted_auth(msg, host: str) -> str:
    """The mail provider's own Authentication-Results header, or "" when it cannot be trusted.
    Senders can add forged Authentication-Results headers to what they send; only the TOPMOST one is added by the receiving
    server. For providers we know add one (Microsoft, Google) we use it; for other servers it must name the server's own domain."""
    headers = msg.get_all("Authentication-Results") or []
    if not headers:
        return ""
    top = re.sub(r"\s+", " ", str(headers[0]))[:4000]
    h = (host or "").lower()
    if any(h == d or h.endswith("." + d) for d in _KNOWN_PROVIDER_HOSTS):
        return top
    m = re.match(r"\s*([A-Za-z0-9.-]+)\s*;", top)
    return top if m and root_domain(m.group(1)) == root_domain(h) else ""

_MID_RE = re.compile(r"^<[^<>\s\"\\\x00-\x1f]{1,300}>$")

def clean_message_id(mid: Optional[str]) -> Optional[str]:
    """A Message-ID safe to put into an IMAP search, or None. Whitespace (including folded CRLF) is removed."""
    mid = re.sub(r"\s+", "", mid or "")
    return mid if _MID_RE.match(mid) else None

def exact_uids(c, mid: Optional[str]) -> list[int]:
    """UIDs whose Message-ID header is EXACTLY mid. IMAP's SEARCH HEADER only does a case-insensitive substring match, so every
    hit is re-checked; a broad match (one odd ID matching many messages) is refused."""
    clean = clean_message_id(mid)
    if not clean:
        return []
    hits = list(c.search(["HEADER", "Message-ID", clean]))
    if len(hits) > 20:
        return []
    out = []
    for uid in hits:
        data = c.fetch([uid], ["BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"]).get(uid, {})
        raw = next((v for k, v in data.items() if k.startswith(b"BODY[")), b"")
        if re.sub(r"\s+", "", email.message_from_bytes(raw).get("Message-ID", "")) == clean:
            out.append(uid)
    return out

@dataclass
class RawEmail:
    uid: int
    message_id: str
    subject: str
    sender_name: str
    sender_email: str
    received_at: Optional[datetime]
    list_unsubscribe: Optional[str]
    snippet: str
    list_unsubscribe_post: Optional[str] = None
    auth_results: str = ""

class IMAPClient:
    def __init__(self, host: str, port: int = 993, username: str = "", password: str = "", access_token: str = ""):
        self.host = host; self.port = port
        self.username = username; self.password = password
        self.access_token = access_token

    def _login(self, c):
        if self.access_token:
            c.oauth2_login(self.username, self.access_token)
        else:
            c.login(self.username, self.password)

    def move_to_junk(self, folder: str, message_ids: list[str], dry_run: bool = True) -> dict:
        """Find each message by its Message-ID in `folder` and move it to the Junk folder (never deletes).
        With dry_run the mailbox is opened read-only and nothing moves. Returns which Message-IDs were found."""
        with _IMAPClient(self.host, port=self.port, ssl=True) as c:
            self._login(c)
            folders = c.list_folders()
            junk = (next((n for flags, _, n in folders if b"\\Junk" in flags), None)
                    or next((n for flags, _, n in folders if n.lower() in JUNK_NAMES), None))
            if not junk:
                raise ValueError("Could not find a Junk folder on this account.")
            if junk.lower() == folder.lower():
                raise ValueError("That folder is already the Junk folder.")
            c.select_folder(folder, readonly=dry_run)
            found: dict[str, list[int]] = {}
            for mid in message_ids:
                uids = exact_uids(c, mid)
                found[mid] = uids if len(uids) == 1 else []  # zero or ambiguous (duplicates) -> do not touch
            all_uids = sorted({u for us in found.values() for u in us})
            if all_uids and not dry_run:
                c.move(all_uids, junk)
        return {"junk_folder": junk, "found": [m for m, u in found.items() if u], "missing": [m for m, u in found.items() if not u], "dry_run": dry_run}

    def find_mail_from(self, domains: list[str], since_days: int = 45, max_messages: int = 200) -> list[dict]:
        """Headers only (never bodies, never links) of recent mail from the given sender domains, in Inbox and Junk.
        Includes whether the mail provider verified the sender (DKIM pass for that domain)."""
        from datetime import date, timedelta
        since = date.today() - timedelta(days=since_days)
        out: list[dict] = []
        with _IMAPClient(self.host, port=self.port, ssl=True) as c:
            self._login(c)
            names = [(flags, n) for flags, _, n in c.list_folders()]
            junk = (next((n for f, n in names if b"\\Junk" in f), None) or next((n for f, n in names if n.lower() in JUNK_NAMES), None))
            folders = [n for _, n in names if n.upper() == "INBOX"] + ([junk] if junk else [])
            for folder in folders:
                c.select_folder(folder, readonly=True)
                seen: set[int] = set()
                for d in domains:
                    for uid in c.search(["FROM", d, "SINCE", since]):
                        if uid in seen or len(out) >= max_messages:
                            continue
                        seen.add(uid)
                        data = c.fetch([uid], ["BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE AUTHENTICATION-RESULTS)]"]).get(uid, {})
                        raw = next((v for k, v in data.items() if k.startswith(b"BODY[")), b"")
                        msg = email.message_from_bytes(raw)
                        from_addr = email.utils.parseaddr(self._decode(msg.get("From", "")))[1].lower()
                        auth = trusted_auth(msg, self.host)
                        out.append({"folder": folder, "from": from_addr, "subject": self._decode(msg.get("Subject", ""))[:200],
                                    "date": (self._date(msg.get("Date")) or datetime.utcnow()).isoformat(timespec="seconds") + "Z",
                                    "dkim_domain": dkim_pass_domain(auth)})
        return out

    def read_auth_results(self, folder: str, message_id: str) -> str:
        """The mail provider's own verdict (SPF/DKIM/DMARC) for one message, found by Message-ID. Headers only, read-only."""
        with _IMAPClient(self.host, port=self.port, ssl=True) as c:
            self._login(c)
            c.select_folder(folder, readonly=True)
            uids = exact_uids(c, message_id)[:1]
            if not uids:
                return ""
            data = c.fetch(uids, ["BODY.PEEK[HEADER.FIELDS (AUTHENTICATION-RESULTS)]"])[uids[0]]
            raw = next((v for k, v in data.items() if k.startswith(b"BODY[")), b"")
            return trusted_auth(email.message_from_bytes(raw), self.host)

    def sender_history(self, terms: list[str], max_messages: int = 100) -> list[dict]:
        """Which domains has mail with these words in the sender name come from, in Inbox and Junk? Domains and counts only."""
        from collections import defaultdict
        stats: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "newest": "", "oldest": "9999"})
        with _IMAPClient(self.host, port=self.port, ssl=True) as c:
            self._login(c)
            names = [(f, n) for f, _, n in c.list_folders()]
            junk = (next((n for f, n in names if b"\\Junk" in f), None) or next((n for f, n in names if n.lower() in JUNK_NAMES), None))
            for folder in [n for _, n in names if n.upper() == "INBOX"] + ([junk] if junk else []):
                c.select_folder(folder, readonly=True)
                uids: set[int] = set()
                for t in terms[:3]:
                    uids |= set(c.search(["FROM", t]))
                for uid in sorted(uids)[-max_messages:]:
                    data = c.fetch([uid], ["BODY.PEEK[HEADER.FIELDS (FROM DATE AUTHENTICATION-RESULTS)]"])[uid]
                    msg = email.message_from_bytes(next((v for k, v in data.items() if k.startswith(b"BODY[")), b""))
                    dom = email.utils.parseaddr(msg.get("From", ""))[1].lower().rsplit("@", 1)[-1]
                    key = (dom, dkim_pass_domain(trusted_auth(msg, self.host)) or "")
                    st = stats[key]; st["count"] += 1
                    d = self._date(msg.get("Date"))
                    if d:
                        iso = d.date().isoformat(); st["newest"] = max(st["newest"], iso); st["oldest"] = min(st["oldest"], iso)
        return [{"domain": d, "dkim_domain": k or None, "count": v["count"], "newest": v["newest"], "oldest": v["oldest"] if v["oldest"] != "9999" else ""}
                for (d, k), v in sorted(stats.items(), key=lambda kv: -kv[1]["count"])]

    def list_folders(self) -> list[str]:
        """Selectable folders, INBOX first."""
        with _IMAPClient(self.host, port=self.port, ssl=True) as c:
            if self.access_token:
                c.oauth2_login(self.username, self.access_token)
            else:
                c.login(self.username, self.password)
            names = [name for flags, _, name in c.list_folders() if b"\\Noselect" not in flags and b"\\NonExistent" not in flags]
        return sorted(names, key=lambda n: (n.upper() != "INBOX", n.lower()))

    def fetch_emails(self, folder="INBOX", limit=50) -> Generator[RawEmail, None, None]:
        """Newest first. Read-only mailbox + BODY.PEEK, so scanning never marks mail as read."""
        with _IMAPClient(self.host, port=self.port, ssl=True) as c:
            if self.access_token:
                c.oauth2_login(self.username, self.access_token)
            else:
                c.login(self.username, self.password)
            c.select_folder(folder, readonly=True)
            uids = c.search(["ALL"])[-limit:][::-1]
            for i in range(0, len(uids), CHUNK):
                chunk = uids[i:i + CHUNK]
                fetched = c.fetch(chunk, [f"BODY.PEEK[]<0.{PEEK_BYTES}>"])
                for uid in chunk:
                    data = fetched.get(uid)
                    raw = next((v for k, v in (data or {}).items() if k.startswith(b"BODY[")), None)
                    if raw:
                        yield self._parse(uid, email.message_from_bytes(raw))

    def _parse(self, uid, msg) -> RawEmail:
        from_ = email.utils.parseaddr(self._decode(msg.get("From", "")))
        return RawEmail(uid=uid, message_id=(msg.get("Message-ID") or "").strip(),
                        subject=self._decode(msg.get("Subject", "")),
                        sender_name=from_[0], sender_email=from_[1],
                        received_at=self._date(msg.get("Date")),
                        list_unsubscribe=msg.get("List-Unsubscribe"),
                        snippet=self._snippet(msg),
                        list_unsubscribe_post=msg.get("List-Unsubscribe-Post"),
                        auth_results=trusted_auth(msg, self.host))

    @staticmethod
    def _text(part) -> str:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        try:
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")

    def _snippet(self, msg) -> str:
        plain = html = ""
        for part in (msg.walk() if msg.is_multipart() else [msg]):
            ctype = part.get_content_type()
            if ctype == "text/plain" and not plain:
                plain = self._text(part)
            elif ctype == "text/html" and not html:
                html = self._text(part)
        text = plain or (BeautifulSoup(html, "html.parser").get_text(" ") if html else "")
        return re.sub(r"\s+", " ", text).strip()[:500]

    @staticmethod
    def _date(val) -> Optional[datetime]:
        try:
            dt = email.utils.parsedate_to_datetime(val)
            return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            return None

    @staticmethod
    def _decode(val: str) -> str:
        out = []
        for text, enc in email.header.decode_header(val or ""):
            if isinstance(text, bytes):
                try:
                    text = text.decode(enc or "utf-8", errors="replace")
                except LookupError:
                    text = text.decode("utf-8", errors="replace")
            out.append(text)
        return "".join(out)
