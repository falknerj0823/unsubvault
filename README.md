# 🔐 UnsubVault

**A self-hosted email cleanup tool: find the mailing lists you never want, unsubscribe from them safely, ignore spam, and start removing your details from data brokers.**

UnsubVault runs on your own computer with Docker. Your mail, keys and results stay in a database you control.

> **Status: pre-alpha.** It works end to end for Outlook/Hotmail/Microsoft 365 and for any IMAP mailbox, but expect rough edges. It is a single-user tool: don't put it on the open internet. See [SECURITY.md](SECURITY.md).

## What it does

- **Scans a mailbox (read-only)** and finds mail with an unsubscribe header. Only those emails (subject, sender, and the first 500 characters) go to the AI model you choose, which can be fully local.
- **Classifies** each sender as newsletter, promotional, receipt/account notice, personal, or **spam**, with a short reason.
- **Review & unsubscribe**: decisions are per sender, with a preview, dry-run mode and a confirmation step. One-click (RFC 8058) senders are confirmed; plain web links are marked "request sent, unverified"; email-only senders are listed for you to handle.
- **Fix the model's mistakes**: mark a sender **Safe** (never offered again) or **Not spam** (it moves to Review as ordinary marketing). Companies that also send you receipts get a warning before you unsubscribe, and unsubscribes you do yourself can be recorded with **Done by me**.
- **Verify a sender**: one click checks who really sent a message: your provider's own signature check (used only when your provider adds it; some IMAP servers don't), the domain's age and mail policies, and what else your mailbox holds from that name. It can also ask your model to weigh the evidence, sending it the sender's display name and domain plus those technical facts, never the email's subject or body. An optional setting runs the checks automatically on senders a scan flags.
- **Spam is never unsubscribed from** (that only confirms your address is live). Optionally move detected spam to Junk, which trains your provider's filter. Nothing is ever deleted.
- **Privacy cleanup**: a data broker opt-out checklist (California's DROP first), California's official broker registry with change tracking, an optional weekly link-health monitor (off by default), a "Search for me" helper, and a read-only check of your mailbox for broker confirmation emails (with sender verification, to spot fakes).
- **Activity log** of sensitive actions (sign-ins, setting changes, scans, unsubscribes) without secrets or email content.

## What it does *not* do (yet)

- Gmail sign-in (OAuth). Gmail works today through IMAP with an app password.
- Send `mailto:` unsubscribe emails. Those senders are listed for you to handle.
- Automate data-broker opt-out forms or solve CAPTCHAs. It tracks and guides; you click the buttons.
- Work well on a phone screen. The layout targets desktop browsers.

## Quick start

Requires Docker with Compose.

```bash
git clone https://github.com/falknerj0823/unsubvault.git
cd unsubvault
cp .env.example .env
```

Edit `.env` and set at least:

| Variable | What to put |
|---|---|
| `SECRET_KEY` | A long random string: `openssl rand -hex 32`. It encrypts stored tokens and keys. **If you change it, reconnect your accounts.** |
| `ADMIN_PASSWORD` | The login password (8+ characters). You can change it later in Settings. |
| `POSTGRES_PASSWORD` and the password inside `DATABASE_URL` | A strong value; the two must match. |

Then:

```bash
docker compose up --build
```

Open **http://localhost:3000**, sign in, and follow **Guides** in the sidebar:

1. **Accounts**: connect Outlook/Hotmail (needs a free Azure app registration, see the in-app guide) or add an IMAP account with an app password.
2. **Settings → LLM**: pick a provider. Local Ollama keeps everything on your machine.
3. **Scan**, then **Review**. Dry-run mode is on by default, so nothing is sent until you turn it off in Settings.

The app listens on `127.0.0.1` only. To run it on a home server or NAS and reach it from other devices, follow [docs/home-server.md](docs/home-server.md) (HTTPS reverse proxy, Microsoft redirect address, moving an existing install).

## Choosing an AI model

OpenAI, Anthropic, Ollama (local), any OpenAI-compatible server (LM Studio, vLLM, OpenRouter...), plus two **subscription** options that use the official CLIs: Claude Code (`claude setup-token`) and Codex. The CLIs are installed into the image only if you set `INSTALL_AI_CLIS=true` in `.env`; the Codex path is experimental and untested against a real login. API keys are stored encrypted and each provider keeps its own saved settings.

## How your data is handled

- Everything lives in your Postgres volume. **Encrypted with `SECRET_KEY`:** provider tokens, IMAP passwords, API keys, client secrets and your optional broker-search profile. **Stored as plain text in the database:** the subject, sender name and address of marketing and spam mail, the model's one-line reason, unsubscribe links, message IDs, your account addresses, and the activity log. Anyone who can read your database can read those, so protect the volume and your backups.
- Receipts, account notices and personal mail are stored as the sender's company domain only (no subject, name or description). You can set automatic deletion of old results and wipe all scan data from Settings. The activity log (sender domains and addresses for unsubscribes and accounts) is kept for 180 days and is not part of "delete all scan data".
- **Network connections the app makes:** your mail server; the AI provider you choose (and, if you pick the Claude Code or Codex option, whatever those programs contact: the app turns off their telemetry and auto-update where they allow it); `login.microsoftonline.com` for Microsoft sign-in; sender unsubscribe links when you approve a real run; `cppa.ca.gov` (the broker registry) when you press Sync; `data.iana.org` and the domain registries' RDAP servers, plus DNS lookups of sender domains, when you verify a sender; and, only when you press the button or turn on the optional weekly check, the data broker pages on your checklist. There is no telemetry.
- Requests to links taken from emails go through one guarded path (`backend/app/services/safe_http.py`): https and port 443 only, public addresses only, connection pinned to the checked address, every redirect re-checked, and an overall time limit.
- The app has one administrator. That person can point the app at any LLM address or mail server (needed for local models), so treat the admin password as the key to your network as well as your mail.

## Maintenance and troubleshooting

- **Forgot the admin password?** The password you set in Settings overrides `ADMIN_PASSWORD` in `.env`. To fall back to the `.env` value:
  `docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DELETE FROM app_settings WHERE key IN ('admin_password_hash','session_version');"` (run it from a shell where those variables are set, or type the values), then sign in with the `.env` password.
- **Back up** before upgrades: `docker compose exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > ../unsubvault-backup.sql`. Remember `SECRET_KEY` too: without it, stored tokens and keys can't be decrypted.
- **Upgrading**: `git pull && docker compose up --build -d`. Database migrations run automatically on start.
- **`docker compose down -v` deletes your database.** Use plain `docker compose down` to stop the app.
- **Rotating the database password**: change it inside Postgres (`ALTER USER ... PASSWORD ...`), then update both `POSTGRES_PASSWORD` and `DATABASE_URL` in `.env`, and restart.

## Data sources and disclaimers

- Broker information comes from a hand-checked list ([`backend/app/data/brokers.json`](backend/app/data/brokers.json)) and the public [California data broker registry](https://cppa.ca.gov/data_broker_registry/). Brokers change their pages often; verify before relying on a link. Contributions that fix links are welcome.
- This project is not affiliated with any data broker, mail provider or AI company, and is not legal advice. The "Delete Act"/DROP link points to the state's own site, which you use yourself.

## Project layout

```
backend/    FastAPI + SQLAlchemy + Alembic (app/), tests (tests/), catalog checker (scripts/)
frontend/   React + Vite + Tailwind, served by nginx, which proxies /api to the backend
docker-compose.yml, .env.example
```

The `worker` container is a Celery stub for future background jobs; scans currently run inside the API process.

## Documentation

Start at [docs/README.md](docs/README.md): [architecture](docs/architecture.md), [security model](docs/security-model.md), [design decisions](docs/decisions.md), [operations](docs/runbooks/operations.md) and [troubleshooting](docs/runbooks/troubleshooting.md) runbooks, [running on a NAS or home server](docs/home-server.md), [testing](docs/testing.md), [maintaining the project](docs/runbooks/maintaining.md), and the generated [reference](docs/reference.md).

## Development and tests

See [CONTRIBUTING.md](CONTRIBUTING.md). In short:

```bash
docker compose exec backend python -m tests.run_all      # about 420 checks against throwaway databases
python backend/scripts/check_catalog.py                  # validates the broker list
```

## License

[MIT](LICENSE) © 2026 Jeffrey Falkner
