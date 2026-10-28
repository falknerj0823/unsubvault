# Reference (generated)

> Generated from the code by `backend/scripts/gen_reference.py`. Do not edit by hand: run
> `docker compose exec -T backend python scripts/gen_reference.py > docs/reference.md`. CI fails if this file is out of date.

## API routes

Everything except the three `open` routes needs a signed-in session cookie. Writes also need a matching `Origin`.

| Method | Path | Access | What it does |
|---|---|---|---|
| `GET` | `/api/accounts/` | login | List Accounts |
| `POST` | `/api/accounts/imap` | login | Add Imap Account |
| `DELETE` | `/api/accounts/{account_id}` | login | Delete Account |
| `GET` | `/api/accounts/{account_id}/folders` | login | Folders on the mail server, for the scan folder picker. |
| `GET` | `/api/audit/` | login | Newest first. Page with before_id = the smallest id from the previous page. |
| `GET` | `/api/audit/types` | login | Event Types |
| `GET` | `/api/auth/microsoft/callback` | login | Microsoft Callback |
| `GET` | `/api/auth/microsoft/login` | login | Microsoft Login |
| `GET` | `/api/auth/microsoft/redirect-uri` | login | The exact URI to register in the Azure app registration. |
| `GET` | `/api/emails/` | login | List Emails |
| `GET` | `/api/emails/counts` | login | Tab badges: pending / unsubscribed / failed / kept (not spam) / spam / all. |
| `POST` | `/api/emails/{email_id}/not-spam` | login | The model called this sender spam and it is not. Treat the sender as ordinary marketing from now on (it appears in |
| `POST` | `/api/emails/{email_id}/verify` | login | Run the technical checks on this email's sender. Optionally ask the configured model to weigh the evidence |
| `GET` | `/api/health` | open | Health |
| `GET` | `/api/privacy/brokers` | login | Brokers |
| `PUT` | `/api/privacy/brokers/{broker_id}` | login | Set Status |
| `POST` | `/api/privacy/check-mailbox` | login | Read-only look for recent mail from the brokers' domains (headers only). Shows whether your mail provider |
| `POST` | `/api/privacy/links/check` | login | Check Links |
| `DELETE` | `/api/privacy/profile` | login | Delete Profile |
| `GET` | `/api/privacy/profile` | login | Get Profile |
| `PUT` | `/api/privacy/profile` | login | Put Profile |
| `GET` | `/api/privacy/registry` | login | List Registry |
| `POST` | `/api/privacy/registry/sync` | login | Sync Registry |
| `GET` | `/api/scan/runs` | login | List Runs |
| `POST` | `/api/scan/start` | login | Start Scan |
| `POST` | `/api/session/change-password` | login | Change Password |
| `POST` | `/api/session/login` | open | Login |
| `POST` | `/api/session/logout` | open | Logout |
| `POST` | `/api/session/logout-all` | login | Invalidate every session, including this one and any copied cookie. |
| `GET` | `/api/session/me` | login | Me |
| `GET` | `/api/settings/` | login | Get Settings |
| `GET` | `/api/settings/app` | login | Get App Settings |
| `PUT` | `/api/settings/app` | login | Put App Settings |
| `DELETE` | `/api/settings/data/scan` | login | Wipe stored scan results and history. Accounts, settings, safe-sender rules and the audit log are kept. |
| `GET` | `/api/settings/llm` | login | Get Llm |
| `PUT` | `/api/settings/llm` | login | Save this provider's profile and make it the active one. Other providers' profiles are untouched. |
| `POST` | `/api/settings/llm/models` | login | Llm Models |
| `POST` | `/api/settings/llm/test` | login | Test Llm |
| `GET` | `/api/spam/candidates` | login | Candidates |
| `POST` | `/api/spam/move` | login | Move chosen spam to Junk. The server-side dry-run setting forces a read-only check instead of a move. |
| `POST` | `/api/unsubscribe/bulk` | login | Bulk |
| `GET` | `/api/unsubscribe/jobs/{job_id}` | login | Get Job |
| `GET` | `/api/unsubscribe/keep` | login | List Keep |
| `POST` | `/api/unsubscribe/keep` | login | Mark senders as safe: never spam, never offered for unsubscribe, not sent to the LLM again. |
| `DELETE` | `/api/unsubscribe/keep/{rule_id}` | login | Undo Keep |
| `POST` | `/api/unsubscribe/mark-done` | login | You unsubscribed yourself (opened the sender's page or sent the email). Record it so the sender leaves the queue. |
| `GET` | `/api/unsubscribe/senders` | login | Senders |

## Database tables

Created by the Alembic migrations in `backend/alembic/versions/`.

### `accounts`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `label` | varchar | required |
| `provider_type` | varchar | required |
| `email_address` | varchar |  |
| `access_token` | varchar |  |
| `refresh_token` | varchar |  |
| `token_expires_at` | datetime |  |
| `imap_host` | varchar |  |
| `imap_port` | integer |  |
| `imap_username` | varchar |  |
| `imap_password_encrypted` | varchar |  |
| `created_at` | datetime |  |

### `app_settings`

| Column | Type | Notes |
|---|---|---|
| `key` | varchar | primary key |
| `value` | varchar |  |
| `encrypted` | boolean | required |

### `audit_events`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `created_at` | datetime | required |
| `event_type` | varchar | required |
| `success` | boolean | required |
| `actor` | varchar | required |
| `ip` | varchar |  |
| `detail` | text |  |

### `broker_status`

| Column | Type | Notes |
|---|---|---|
| `broker_id` | varchar | primary key |
| `status` | varchar | required |
| `requested_at` | datetime |  |
| `confirmed_at` | datetime |  |
| `updated_at` | datetime |  |

### `email_records`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `account_id` | integer | required, references `accounts.id` |
| `scan_run_id` | integer | references `scan_runs.id` |
| `message_id` | varchar |  |
| `subject` | varchar |  |
| `sender_name` | varchar |  |
| `sender_email` | varchar |  |
| `received_at` | datetime |  |
| `is_newsletter` | boolean |  |
| `is_promotional` | boolean |  |
| `confidence` | float |  |
| `category` | varchar |  |
| `classification_reason` | varchar |  |
| `action` | varchar |  |
| `unsubscribe_url` | varchar |  |
| `unsubscribe_method` | varchar |  |
| `unsubscribe_one_click` | boolean |  |
| `unsubscribe_result` | varchar |  |
| `unsubscribe_error` | varchar |  |
| `unsubscribed_at` | datetime |  |
| `prior_category` | varchar |  |
| `prior_action` | varchar |  |
| `verify_verdict` | varchar |  |
| `verify_summary` | varchar |  |
| `created_at` | datetime |  |

### `link_checks`

| Column | Type | Notes |
|---|---|---|
| `broker_id` | varchar | primary key |
| `checked_at` | datetime | required |
| `state` | varchar | required |
| `http_status` | integer |  |
| `final_url` | varchar |  |
| `note` | varchar |  |

### `llm_profiles`

| Column | Type | Notes |
|---|---|---|
| `provider` | varchar | primary key |
| `model` | varchar |  |
| `base_url` | varchar |  |
| `api_key_encrypted` | varchar |  |
| `updated_at` | datetime |  |

### `registry_brokers`

| Column | Type | Notes |
|---|---|---|
| `id` | varchar | primary key |
| `name` | varchar | required |
| `website` | varchar |  |
| `email` | varchar |  |
| `optout_text` | text |  |
| `date_added` | varchar |  |
| `fingerprint` | varchar | required |
| `first_seen_sync` | integer | required |
| `changed_sync` | integer |  |
| `removed_sync` | integer |  |
| `first_seen_at` | datetime |  |
| `last_seen_at` | datetime |  |

### `registry_syncs`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `at` | datetime |  |
| `total` | integer |  |
| `new` | integer |  |
| `changed` | integer |  |
| `removed` | integer |  |
| `baseline` | integer |  |

### `scan_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `account_id` | integer | required, references `accounts.id` |
| `status` | varchar | required |
| `folder` | varchar |  |
| `dry_run` | boolean |  |
| `emails_scanned` | integer |  |
| `emails_unsubscribed` | integer |  |
| `emails_failed` | integer |  |
| `started_at` | datetime |  |
| `completed_at` | datetime |  |
| `error` | varchar |  |
| `batch_size` | integer |  |
| `emails_found` | integer |  |
| `emails_known` | integer |  |
| `emails_no_link` | integer |  |
| `emails_spam` | integer |  |

### `sender_checks`

| Column | Type | Notes |
|---|---|---|
| `domain` | varchar | primary key |
| `checked_at` | datetime |  |
| `facts` | text | required |

### `sender_rules`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `account_id` | integer | required, references `accounts.id` |
| `sender_email` | varchar | required |
| `decision` | varchar | required |
| `sender_name` | varchar |  |
| `created_at` | datetime |  |

### `unsub_jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `status` | varchar | required |
| `dry_run` | boolean | required |
| `selection` | text | required |
| `total` | integer |  |
| `done` | integer |  |
| `confirmed` | integer |  |
| `unverified` | integer |  |
| `manual` | integer |  |
| `failed` | integer |  |
| `simulated` | integer |  |
| `error` | varchar |  |
| `started_at` | datetime |  |
| `completed_at` | datetime |  |

## Settings editable in the app

Stored in `app_settings` (database wins over the `.env` default). Secrets are encrypted with `SECRET_KEY`.

| Setting | Type | Storage | Default from `.env` / code |
|---|---|---|---|
| `auto_link_check` | bool | plain | `False` |
| `auto_verify` | bool | plain | `False` |
| `dry_run` | bool | plain | `True` |
| `frontend_url` | str | plain | `http://localhost:3000` |
| `google_client_id` | str | plain | `(empty)` |
| `google_client_secret` | str | encrypted, never shown | `(empty)` |
| `microsoft_client_id` | str | plain | `(empty)` |
| `microsoft_client_secret` | str | encrypted, never shown | `(empty)` |
| `microsoft_tenant` | str | plain | `consumers` |
| `scan_batch_size` | int | plain | `50` |
| `scan_retention_days` | int | plain | `0` |
| `timezone` | str | plain | `(empty)` |

## Audit event types

`account_added`, `account_connected`, `account_removed`, `app_started`, `broker_links_check_started`, `broker_mailbox_checked`, `broker_status_changed`, `bulk_unsubscribe_completed`, `bulk_unsubscribe_started`, `llm_config_changed`, `llm_test`, `login`, `login_blocked`, `login_failed`, `logout`, `logout_everywhere`, `marked_not_spam`, `microsoft_signin_failed`, `microsoft_signin_started`, `password_change_failed`, `password_changed`, `privacy_profile_deleted`, `privacy_profile_saved`, `registry_synced`, `safe_sender_added`, `safe_sender_removed`, `scan_completed`, `scan_data_deleted`, `scan_data_purged`, `scan_failed`, `scan_started`, `sender_verified`, `settings_changed`, `spam_moved_to_junk`, `unsubscribe_attempt`, `unsubscribe_marked_done`

## Environment variables (`.env`)

| Variable | Status | Note |
|---|---|---|
| `POSTGRES_USER` | in `.env.example` |  |
| `POSTGRES_PASSWORD` | in `.env.example` | use a long random value; it must match DATABASE_URL below |
| `POSTGRES_DB` | in `.env.example` |  |
| `DATABASE_URL` | in `.env.example` | required |
| `REDIS_URL` | in `.env.example` |  |
| `SECRET_KEY` | in `.env.example` | openssl rand -hex 32 (required, min 32 chars) |
| `ADMIN_PASSWORD` | in `.env.example` | UI login password (required) |
| `FRONTEND_URL` | in `.env.example` |  |
| `MICROSOFT_CLIENT_ID` | in `.env.example` |  |
| `MICROSOFT_CLIENT_SECRET` | in `.env.example` |  |
| `MICROSOFT_TENANT` | in `.env.example` |  |
| `GOOGLE_CLIENT_ID` | in `.env.example` |  |
| `GOOGLE_CLIENT_SECRET` | in `.env.example` |  |
| `LLM_PROVIDER` | in `.env.example` | openai / anthropic / ollama |
| `OPENAI_API_KEY` | in `.env.example` |  |
| `ANTHROPIC_API_KEY` | in `.env.example` |  |
| `OLLAMA_BASE_URL` | in `.env.example` |  |
| `OLLAMA_MODEL` | in `.env.example` |  |
| `SCAN_BATCH_SIZE` | in `.env.example` |  |
| `DRY_RUN` | in `.env.example` |  |
| `INSTALL_AI_CLIS` | in `.env.example` |  |
| `BIND_ADDRESS` | optional |  |
| `PORT` | optional |  |
