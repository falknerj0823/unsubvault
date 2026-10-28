# Contributing

Thanks for helping. UnsubVault is small and self-hosted, so the bar is: keep it safe, keep it understandable.

## Run it

```bash
cp .env.example .env        # fill in SECRET_KEY (openssl rand -hex 32), ADMIN_PASSWORD and the database password
docker compose up --build   # http://localhost:3000
```

## Run the tests

The tests give every script its own throwaway database (`unsubvault_test`) on the Postgres in `DATABASE_URL`.
They never touch real data.

```bash
docker compose exec backend python -m tests.run_all          # inside the running stack
UNSUBVAULT_OFFLINE=1 python -m tests.run_all                 # from backend/, skips checks that call third-party sites
cd backend && python scripts/check_catalog.py                # validates the broker catalog
cd frontend && npm ci && npm run build                       # type-checks the UI
```

Add a test for behavior you change. Tests are plain scripts that print `PASS`/`FAIL` lines (see `backend/tests/`).

## The data broker catalog (easiest way to help)

`backend/app/data/brokers.json` lists opt-out pages. Brokers change their pages constantly, so fixes are very welcome.

1. Open the opt-out page yourself and confirm it works. **Do not copy links from a service that sells removal; use the broker's own page.**
2. Add or fix the entry (fields are documented by `scripts/check_catalog.py`). No affiliate or tracking parameters, no links inside `notes`.
3. Update `checked_at`, run `python scripts/check_catalog.py`, and say in the pull request how you verified the link.

## Documentation

Docs live in `docs/` (start at `docs/README.md`). `docs/reference.md` is generated from the code: after changing a route, table, setting, audit event or `.env.example`, regenerate it (command in `docs/runbooks/maintaining.md`); CI fails if it is stale. Keep examples generic: no real addresses, names or tokens.

## Ground rules

- **Never log or store secrets, email content or personal details** beyond what a feature needs. Say what a feature stores in the pull request.
- **Anything that requests a URL from an email or the web must use `app/services/safe_http.py`.**
- Changes that act on a mailbox or contact third parties must respect dry-run mode and be reversible or confirmed.
- No telemetry, no external services that hold user data.

## Pull requests

Keep them focused, explain the why, and note what you tested. By contributing you agree your work is released under the MIT license.
