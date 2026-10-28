"""Validate the data broker catalog (backend/app/data/brokers.json).

    python scripts/check_catalog.py            # structure only, no network (used in CI)
    python scripts/check_catalog.py --links    # also request every opt-out link (needs the internet)

Exit code 1 if anything is wrong, so it can gate a pull request."""
import asyncio, json, re, sys
from pathlib import Path
from urllib.parse import urlsplit

CATALOG = Path(__file__).resolve().parent.parent / "app" / "data" / "brokers.json"
CATEGORIES = {"california", "people_search", "marketing_data", "mail_calls", "tools"}
METHODS = {"web form", "email", "state site", "tool"}
LINK_CHECKS = {"ok", "blocks_bots"}
REQUIRED = ("id", "name", "category", "method", "url", "notes", "recheck_months", "sender_domains", "link_check")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")

def validate(data: dict) -> list[str]:
    errors: list[str] = []
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(data.get("checked_at", ""))):
        errors.append("checked_at must be a date like 2026-10-28")
    brokers = data.get("brokers")
    if not isinstance(brokers, list) or not brokers:
        return errors + ["brokers must be a non-empty list"]
    seen: set[str] = set()
    for i, b in enumerate(brokers):
        where = f"brokers[{i}] ({b.get('id', '?')})"
        for k in REQUIRED:
            if k not in b:
                errors.append(f"{where}: missing '{k}'")
        if errors and any(e.startswith(where) for e in errors):
            continue
        if not ID_RE.match(b["id"]) or b["id"] in seen:
            errors.append(f"{where}: id must be unique lowercase letters, digits and dashes")
        seen.add(b["id"])
        if b["category"] not in CATEGORIES: errors.append(f"{where}: category must be one of {sorted(CATEGORIES)}")
        if b["method"] not in METHODS: errors.append(f"{where}: method must be one of {sorted(METHODS)}")
        if b["link_check"] not in LINK_CHECKS: errors.append(f"{where}: link_check must be one of {sorted(LINK_CHECKS)}")
        u = urlsplit(b["url"])
        if u.scheme != "https" or not u.hostname: errors.append(f"{where}: url must be an https link")
        if u.username or u.password or "?" in b["url"] and re.search(r"(ref|aff|utm_)", b["url"], re.I):
            errors.append(f"{where}: url must not contain credentials or tracking/affiliate parameters")
        if not isinstance(b["recheck_months"], int) or not 1 <= b["recheck_months"] <= 120: errors.append(f"{where}: recheck_months must be 1-120")
        if not isinstance(b["sender_domains"], list) or not all(isinstance(d, str) and DOMAIN_RE.match(d) for d in b["sender_domains"]):
            errors.append(f"{where}: sender_domains must be a list of lowercase domains")
        if len(b["notes"]) < 20 or len(b["notes"]) > 600: errors.append(f"{where}: notes should be 20-600 characters")
        if re.search(r"https?://", b["notes"]): errors.append(f"{where}: put links in 'url', not in notes")
    return errors

async def check_links(brokers: list[dict]) -> list[str]:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.services.linkcheck import check_one
    problems = []
    for b in brokers:
        state, status, final, note = await check_one(b["url"])
        print(f"  {state:8} {b['id']:22} {note}")
        if state in ("broken", "moved"):
            problems.append(f"{b['id']}: {state}: {note}")
        await asyncio.sleep(1)
    return problems

def main() -> int:
    data = json.loads(CATALOG.read_text())
    errors = validate(data)
    if not errors and "--links" in sys.argv:
        errors += asyncio.run(check_links(data["brokers"]))
    for e in errors:
        print("ERROR:", e)
    print(f"{len(data['brokers'])} brokers checked, {len(errors)} problem(s)")
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
