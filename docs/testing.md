# Testing

About 420 automated checks, plus CI on every push and pull request. There is no browser test suite; the UI is checked by the TypeScript build.

## Run them

```bash
docker compose exec backend python -m tests.run_all       # inside the running stack
cd backend && UNSUBVAULT_OFFLINE=1 python -m tests.run_all # from a checkout with a Postgres reachable via DATABASE_URL
python backend/scripts/check_catalog.py                    # validates the broker list (add --links to request each link)
python backend/scripts/gen_reference.py --check docs/reference.md   # is the generated reference current?
cd frontend && npm ci && npm run build                     # type-checks and builds the UI
```

`UNSUBVAULT_OFFLINE=1` skips checks that contact third-party sites (CI sets it). DNS lookups of well-known public names are still used by the URL-safety tests.

## How the tests are built

Each file in `backend/tests/` is a plain script that prints `PASS` / `FAIL` lines and a final `N passed, M failed`. `run_all.py` runs them one by one and fails if any crash or fail.

Every script starts with `from tests import _env; _env.setup()`. That creates a throwaway database called `unsubvault_test` on the Postgres server in `DATABASE_URL`, runs the migrations on it, and points the app at it, so tests never touch real data. `run_all` drops it at the end.

| Module | Covers |
|---|---|
| `scan_pipeline` | Mail parsing, dedupe, classification storage, failure handling, history counters |
| `bulk_unsubscribe` | URL safety rules, redirect handling, unsubscribe outcomes, bulk jobs, dry-run enforcement, audit contents |
| `spam_detection`, `recovery_and_review_rules` | Spam handling, what may be offered for review, recovery of interrupted work |
| `safe_senders` | Domain helpers, minimization, safe-sender rules and undo, retention, delete-all |
| `spam_move` | Moving spam to Junk against a fake IMAP server with real substring-search behaviour |
| `broker_checklist`, `registry_and_links` | Broker status, mailbox check, registry parsing and diffing, safe downloads, link classification, profile encryption |
| `sender_verification` | Verification verdicts, DNS/RDAP parsing and caching, Not spam, auto-verify, Done by me |
| `auth_settings_llm` | Login, sessions, rate limiting, password change, encryption, settings validation, per-provider model settings, audit API |
| `hardening` | Regressions from the security audits: exact Message-ID matching, forged headers, CLI environment, origin checks, an auth check over every API route, key and hash formats, retention edge cases, OAuth state, migrations down and up |

## Adding a test

1. Put it in the module for that area, or create a new script following the same header and add it to `MODULES` in `run_all.py`.
2. Use made-up data (`example.com`-style names). **Never put real mail, real names or real tokens in a test.**
3. Mock the outside world (IMAP, DNS, HTTP, the model) with small fakes. Keep the fake as faithful as the real thing: the IMAP fake must do substring search, because the real server does.
4. A check should fail if the behaviour breaks. Avoid `A and B or C` expressions that pass either way.

## What the tests do **not** cover

- Real Microsoft sign-in, a real IMAP server, a real unsubscribe request to a real sender, a real model.
- Whether broker links still work (the checker does that; see the maintainer runbook).
- The look of the UI (checked manually).

## Manual smoke test before a release

1. Fresh `.env`, `docker compose up --build`, sign in.
2. Add an IMAP or Microsoft account; run **Test connection** on a model; scan a small folder with dry-run on.
3. Review: select a sender, confirm the pop-up appears, run a dry run, check the activity log shows it and nothing was sent.
4. Spam tab: **Not spam** and **Safe sender** move a card; Settings: change password, sign out everywhere.
5. Privacy: sync the registry, check a broker's link, save a profile.
