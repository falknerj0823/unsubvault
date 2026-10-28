"""Technical checks on who really sent a message. Uses only the sender's domain, public DNS and registry data, and the mail
provider's own verdict headers. It never fetches the sender's website and never sends email content anywhere.

'Authentic' means the sender is who its domain says. It does not prove the domain belongs to the brand in the display name,
and it does not mean you want the mail."""
import asyncio, json, re
from datetime import datetime, timedelta
import dns.exception, dns.resolver
from sqlalchemy.orm import Session
from app.models.sender_check import SenderCheck
from app.services.domains import brand_mismatch, domain_of, root_domain
from app.services.safe_http import UnsafeURL, safe_get_bytes

FACTS_TTL = timedelta(days=30)
RDAP_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
_bootstrap: dict | None = None
_bootstrap_at: datetime | None = None

# ------------------------------------------------------------------ DNS
def _dns(name: str, rtype: str) -> list[str]:
    r = dns.resolver.Resolver()
    r.lifetime = 4.0
    try:
        return [x.to_text().strip('"') for x in r.resolve(name, rtype)]
    except (dns.exception.DNSException, OSError):
        return []

def _txt(name: str) -> list[str]:
    return [re.sub(r'"\s+"', "", t) for t in _dns(name, "TXT")]

def parse_spf(records: list[str]) -> dict:
    spf = next((r for r in records if r.lower().startswith("v=spf1")), None)
    if not spf:
        return {"present": False, "policy": None}
    m = re.search(r"\s([-~?+])all\b", spf)
    return {"present": True, "policy": {"-": "fail", "~": "softfail", "?": "neutral", "+": "open"}.get(m.group(1)) if m else None}

def parse_dmarc(records: list[str]) -> dict:
    d = next((r for r in records if r.lower().startswith("v=dmarc1")), None)
    if not d:
        return {"present": False, "policy": None}
    m = re.search(r"\bp=(\w+)", d, re.I)
    return {"present": True, "policy": m.group(1).lower() if m else None}

# ------------------------------------------------------------------ registration date (RDAP, the registries' own API)
async def _rdap_base(tld: str) -> str | None:
    global _bootstrap, _bootstrap_at
    if _bootstrap is None or not _bootstrap_at or datetime.utcnow() - _bootstrap_at > timedelta(days=1):
        status, data = await safe_get_bytes(RDAP_BOOTSTRAP, max_bytes=2_000_000)
        if status != 200:
            return None
        _bootstrap = {t.lower(): next(u for u in urls if u.startswith("https://")) for tlds, urls in json.loads(data)["services"] for t in tlds if any(u.startswith("https://") for u in urls)}
        _bootstrap_at = datetime.utcnow()
    return _bootstrap.get(tld.lower())

def parse_rdap_age(data: bytes) -> datetime | None:
    try:
        for ev in json.loads(data).get("events", []):
            if ev.get("eventAction") == "registration":
                return datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, KeyError, TypeError):
        pass
    return None

async def registration_date(domain: str) -> datetime | None:
    try:
        base = await _rdap_base(domain.rsplit(".", 1)[-1])
        if not base:
            return None
        status, data = await safe_get_bytes(f"{base.rstrip('/')}/domain/{domain}", max_bytes=2_000_000)
        return parse_rdap_age(data) if status == 200 else None
    except (UnsafeURL, OSError, ValueError, KeyError):
        return None
    except Exception:
        return None

# ------------------------------------------------------------------ facts about a domain (cached)
async def domain_facts(db: Session, domain: str) -> dict:
    root = root_domain(domain)
    row = db.query(SenderCheck).filter(SenderCheck.domain == root).first()
    if row and row.checked_at and datetime.utcnow() - row.checked_at < FACTS_TTL:
        return json.loads(row.facts)
    spf_recs, dmarc_recs, mx, reg = await asyncio.gather(
        asyncio.to_thread(_txt, root), asyncio.to_thread(_txt, f"_dmarc.{root}"), asyncio.to_thread(_dns, root, "MX"), registration_date(root))
    facts = {"domain": root, "spf": parse_spf(spf_recs), "dmarc": parse_dmarc(dmarc_recs),
             "mx": [m.split()[-1].rstrip(".").lower() for m in mx][:3],
             "registered": reg.date().isoformat() if reg else None,
             "age_days": (datetime.utcnow() - reg).days if reg else None}
    if row:
        row.facts, row.checked_at = json.dumps(facts), datetime.utcnow()
    else:
        db.add(SenderCheck(domain=root, facts=json.dumps(facts), checked_at=datetime.utcnow()))
    db.commit()
    return facts

# ------------------------------------------------------------------ the provider's own verdict for one message
def parse_auth(results: str) -> dict:
    results = results or ""
    def first(k): m = re.search(rf"\b{k}=(\w+)", results, re.I); return m.group(1).lower() if m else None
    d = re.search(r"dkim=pass[^;]*?header\.d=([A-Za-z0-9.-]+)", results, re.I)
    return {"spf": first("spf"), "dkim": first("dkim"), "dmarc": first("dmarc"), "dkim_domain": d.group(1).lower() if d else None}

def _related(a: str | None, b: str | None) -> bool:
    return bool(a and b and root_domain(a) == root_domain(b))

# ------------------------------------------------------------------ verdict
def evaluate(domain: str, name: str | None, address: str, facts: dict, auth: dict | None, history: list[dict] | None) -> dict:
    """Explainable scoring. Each reason is {ok: True|False|None, text}. Returns verdict, summary and reasons."""
    score = 0.0
    reasons: list[dict] = []
    def add(ok, text, pts=0.0):
        nonlocal score
        score += pts; reasons.append({"ok": ok, "text": text})
    if auth is not None:
        if auth.get("dkim") == "pass" and _related(auth.get("dkim_domain"), domain):
            add(True, f"Your mail provider verified this message's digital signature for {auth['dkim_domain']}.", 2)
        elif auth.get("dkim") in ("fail", "permerror", "temperror"):
            add(False, "The message's digital signature failed verification.", -3)
        elif auth.get("dkim") == "pass":
            add(None, f"It was signed by {auth['dkim_domain']}, which is a different domain from the sender address.", 0)
        else:
            add(None, "No usable signature result for this message.", 0)
        if auth.get("dmarc") == "pass":
            add(True, "It passed the sender's anti-spoofing policy (DMARC).", 1)
        elif auth.get("dmarc") == "fail":
            add(False, "It failed the sender's anti-spoofing policy (DMARC).", -2)
        if auth.get("spf") == "fail":
            add(False, "It came from a server the domain does not authorize (SPF fail).", -2)
    else:
        add(None, "The original message could not be read, so its signature was not checked.", 0)
    d = facts.get("dmarc", {})
    if d.get("present") and d.get("policy") in ("reject", "quarantine"):
        add(True, f"The domain enforces an anti-spoofing policy (DMARC {d['policy']}).", 1)
    elif not d.get("present"):
        add(False, "The domain publishes no anti-spoofing (DMARC) policy.", -0.5)
    s = facts.get("spf", {})
    if not s.get("present"):
        add(False, "The domain lists no authorized mail servers (no SPF record).", -1)
    elif s.get("policy") in ("fail", "softfail"):
        add(True, "The domain lists exactly which servers may send its mail (SPF).", 0.5)
    age = facts.get("age_days")
    if age is None:
        add(None, "Could not look up when the domain was registered.", 0)
    elif age < 90:
        add(False, f"The domain was registered only {age} days ago, typical of throwaway senders.", -2)
    elif age >= 730:
        add(True, f"The domain has existed for {age // 365} years (registered {facts['registered']}).", 1)
    else:
        add(None, f"The domain is about {age // 30} months old.", 0)
    if brand_mismatch(name, address):
        add(None, f"The sender name ({name}) does not appear in the domain, which is common for vendors but also for impostors.", -0.5)
    if history:
        same = [h for h in history if _related(h["domain"], domain)]
        if same and sum(h["count"] for h in same) >= 2:
            add(True, f"Your mailbox holds {sum(h['count'] for h in same)} messages from this domain over time, not a one-off.", 0.5)
        others = [h for h in history if not _related(h["domain"], domain) and h.get("dkim_domain")]
        if others and brand_mismatch(name, address):
            names = ", ".join(sorted({h["domain"] for h in others})[:3])
            add(None, f"Other mail with a similar sender name in your mailbox comes from {names}, not this domain.", -0.5)
    verdict = "legitimate" if score >= 3 else "suspicious" if score <= -1 else "unclear"
    good = [r["text"] for r in reasons if r["ok"] is True][:2]
    bad = [r["text"] for r in reasons if r["ok"] is False][:2]
    summary = {"legitimate": "Authentic sender. ", "suspicious": "Suspicious. ", "unclear": "Unclear. "}[verdict] + " ".join((bad or good)[:1])
    return {"verdict": verdict, "score": round(score, 1), "summary": summary[:200], "reasons": reasons}

EXPLAIN_SYSTEM = ("You help a person decide whether the sender of a marketing email is legitimate. Use ONLY the facts provided, never invent any. "
                  "Answer in 3 to 5 plain sentences: your overall read, what supports it, and what remains unknown (for example, whether "
                  "the domain really belongs to the brand in the display name). Do not give legal or security guarantees.")

async def explain(evidence: dict) -> str:
    from app.services.llm import complete
    return (await complete(EXPLAIN_SYSTEM, json.dumps(evidence, indent=1))).strip()[:1200]
