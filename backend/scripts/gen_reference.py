"""Generate docs/reference.md (API routes, database tables, settings, audit events, environment variables) from the code.

    python scripts/gen_reference.py > ../docs/reference.md      # regenerate
    python scripts/gen_reference.py --check ../docs/reference.md  # exit 1 if the file is out of date (used in CI)

Only names, types and defaults are read: never the values of a running install."""
import os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for k, v in {"DATABASE_URL": "postgresql://user:password@localhost/db", "SECRET_KEY": "x" * 40, "ADMIN_PASSWORD": "placeholder-password"}.items():
    os.environ[k] = v   # fixed placeholders so the output never depends on the environment it runs in

from app.core.config import Settings                  # noqa: E402
from app.core import app_settings                     # noqa: E402
from app.core.database import Base                    # noqa: E402
import app.models  # noqa: E402,F401
import importlib, pkgutil                             # noqa: E402
for m in pkgutil.iter_modules([str(ROOT / "app" / "models")]):
    importlib.import_module(f"app.models.{m.name}")
from app.main import app                              # noqa: E402

OPEN = {("GET", "/api/health"), ("POST", "/api/session/login"), ("POST", "/api/session/logout")}

def routes() -> str:
    rows = []
    for path, methods in sorted(app.openapi()["paths"].items()):
        for method, op in sorted(methods.items()):
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            doc = (op.get("description") or op.get("summary") or "").strip().split("\n")[0].replace("|", "\\|")
            rows.append(f"| `{method.upper()}` | `{path}` | {'open' if (method.upper(), path) in OPEN else 'login'} | {doc} |")
    return "| Method | Path | Access | What it does |\n|---|---|---|---|\n" + "\n".join(rows)

def tables() -> str:
    out = []
    for t in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        out.append(f"### `{t.name}`\n\n| Column | Type | Notes |\n|---|---|---|")
        for c in t.columns:
            notes = [n for n, on in (("primary key", c.primary_key), ("required", not c.nullable and not c.primary_key),
                                     (f"references `{next(iter(c.foreign_keys)).target_fullname}`" if c.foreign_keys else "", bool(c.foreign_keys))) if on and n]
            out.append(f"| `{c.name}` | {str(c.type).split('(')[0].lower()} | {', '.join(notes)} |")
        out.append("")
    return "\n".join(out)

def settings_table() -> str:
    rows = []
    defaults = Settings.model_fields
    for key, (typ, secret) in sorted(app_settings.FIELDS.items()):
        d = defaults[key].default if key in defaults else ""
        rows.append(f"| `{key}` | {typ.__name__} | {'encrypted, never shown' if secret else 'plain'} | `{d if d != '' else '(empty)'}` |")
    return "| Setting | Type | Storage | Default from `.env` / code |\n|---|---|---|---|\n" + "\n".join(rows)

def audit_events() -> str:
    names = set()
    for f in (ROOT / "app").rglob("*.py"):
        names |= set(re.findall(r'audit\.record\(\s*"([a-z_]+)"', f.read_text()))
    return ", ".join(f"`{n}`" for n in sorted(names))

def env_vars() -> str:
    rows = []
    for line in (ROOT.parent / ".env.example").read_text().splitlines():
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=(.*?)(?:\s+#\s*(.*))?$", line)
        if m and not line.startswith("# ─"):
            name, val, note = m.groups()
            rows.append(f"| `{name}` | {'optional' if line.startswith('#') else 'in `.env.example`'} | {(note or '').strip().replace('|', '/')} |")
    return "| Variable | Status | Note |\n|---|---|---|\n" + "\n".join(rows)

def build() -> str:
    return f"""# Reference (generated)

> Generated from the code by `backend/scripts/gen_reference.py`. Do not edit by hand: run
> `docker compose exec -T backend python scripts/gen_reference.py > docs/reference.md`. CI fails if this file is out of date.

## API routes

Everything except the three `open` routes needs a signed-in session cookie. Writes also need a matching `Origin`.

{routes()}

## Database tables

Created by the Alembic migrations in `backend/alembic/versions/`.

{tables()}
## Settings editable in the app

Stored in `app_settings` (database wins over the `.env` default). Secrets are encrypted with `SECRET_KEY`.

{settings_table()}

## Audit event types

{audit_events()}

## Environment variables (`.env`)

{env_vars()}
"""

if __name__ == "__main__":
    text = build()
    if len(sys.argv) > 2 and sys.argv[1] == "--check":
        current = Path(sys.argv[2]).read_text() if Path(sys.argv[2]).exists() else ""
        if current != text:
            print("docs/reference.md is out of date. Regenerate it with: python scripts/gen_reference.py > ../docs/reference.md")
            sys.exit(1)
        print("docs/reference.md is up to date")
    else:
        sys.stdout.write(text)
