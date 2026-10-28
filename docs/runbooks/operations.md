# Operations runbook

Everyday tasks for whoever runs an install. Commands run from the project folder.

## Quick reference

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop (keeps data) | `docker compose stop` |
| Status | `docker compose ps` (backend should say `healthy`) |
| Health check | `curl -s localhost:3000/api/health` returns `{"status":"ok"}` |
| Logs | `docker compose logs -f backend` |
| Update | `git pull && docker compose up --build -d` |
| Run the tests | `docker compose exec backend python -m tests.run_all` |

Use the port you set in `PORT` if it isn't 3000. **`docker compose down -v` deletes the database**; plain `down` or `stop` does not.

## First run

1. `cp .env.example .env`, then set `SECRET_KEY` (`openssl rand -hex 32`), `ADMIN_PASSWORD`, and a strong `POSTGRES_PASSWORD` that also appears inside `DATABASE_URL`. `chmod 600 .env`.
2. `docker compose up --build -d`. The first build takes a few minutes. The backend runs the migrations itself.
3. Open the UI, sign in, then follow **Guides**: Accounts (Microsoft or IMAP), Settings → LLM (Test connection), Scan, Review. Dry-run stays on until you turn it off in Settings.
4. Store `SECRET_KEY` somewhere other than the server (a password manager). Without it, backups of the database can't be decrypted.

## Backups and restore

**Back up** (database only):

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > ../unsubvault-backup.sql
chmod 600 ../unsubvault-backup.sql
```

The dump holds mail subjects and sender addresses in plain text; store it like the mailbox itself, and not inside the project folder or a shared folder. Keep `SECRET_KEY` separately.

**Restore** into an empty database (same `SECRET_KEY` as the original):

```bash
docker compose up -d db
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\"" -c "CREATE DATABASE \"$POSTGRES_DB\""'
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < ../unsubvault-backup.sql
docker compose up -d
```

Moving to another machine is the same procedure ([home-server.md](../home-server.md)).

## Upgrading

`git pull && docker compose up --build -d`. Migrations run at start. If the backend does not become healthy, read `docker compose logs backend`; a failed migration stops the start rather than damaging data. To go back, `git checkout` the previous version and restore the backup you took before upgrading.

## Rotating secrets

| Secret | How | Effect |
|---|---|---|
| **Admin password** | Settings → Admin password | Signs out every other browser. The password set here overrides `ADMIN_PASSWORD` in `.env` |
| **Sign out everywhere** | Settings → Admin password → *Sign out of every browser* | Ends all sessions, including this one |
| **Database password** | 1. take a backup. 2. `docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres` and run `ALTER USER <user> WITH PASSWORD '<new>';`. 3. put the new value in **both** `POSTGRES_PASSWORD` and `DATABASE_URL` in `.env`. 4. `docker compose up -d --force-recreate db backend worker`. 5. check `docker compose ps` and sign in | No data change. The old password stops working |
| **`SECRET_KEY`** | Set a new value in `.env` and restart. Everything encrypted with the old key becomes unreadable, so afterwards re-enter the Microsoft client secret, model API keys and the search profile, and remove and re-add every mail account | Sessions end. There is no automatic re-encryption |
| **Microsoft client secret** | Create a new secret in Azure, paste its **Value** into Accounts → Microsoft, delete the old secret in Azure | Renewing sign-ins keeps working |
| **A model API key** | Settings → LLM, pick the provider, paste the new key, Save | |

## Forgot the admin password

The password saved in Settings overrides `.env`. To fall back to the `.env` value:

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DELETE FROM app_settings WHERE key IN ('"'"'admin_password_hash'"'"','"'"'session_version'"'"')"'
```

Then sign in with `ADMIN_PASSWORD` from `.env` and set a new one in Settings.

## Data hygiene

- **Settings → General → delete stored scan details after N days** removes finished results automatically (mail waiting for a decision, spam waiting to be moved, and failed unsubscribes are kept).
- **Delete all scan data** wipes results and history; accounts, settings and safe senders stay.
- The activity log keeps 180 days and then prunes itself.
- To remove everything: `docker compose down -v`, delete the folder, and remove the app under your Microsoft account's app permissions.

## Reading the activity log

Activity shows sign-ins and failures, setting and model changes, accounts added or removed, scans, unsubscribe attempts (sender and result, never the link), safe-sender decisions, and sender verifications. Use it to answer "did the app send anything?" ([reference.md](../reference.md) lists the event types).

## Before turning dry-run off

1. Run a dry run on a few senders and read the result list.
2. Prefer one-click senders first. "Request sent, unverified" means a plain link answered OK but may only have shown a confirmation page.
3. Watch for the mail to actually stop over the next weeks. Open manual senders' pages yourself and press **Done by me**.
