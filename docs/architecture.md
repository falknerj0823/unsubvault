# Architecture

UnsubVault is a small web app that runs in Docker on your own machine. It reads a mailbox, asks a language model to classify mail, lets you decide per sender, and then acts (or only simulates) on your decision.

## Components

```
Browser ──► nginx (frontend container, port 80, published on BIND_ADDRESS:PORT)
              ├─ serves the React app (static files, security headers, CSP)
              └─ /api/* ──► backend (FastAPI + uvicorn, port 8000, not published)
                              ├─ Postgres (all state)
                              ├─ mail server (IMAP, Microsoft OAuth)
                              ├─ language model (Ollama, API providers, or a CLI)
                              └─ the internet, only through one guarded fetcher
worker (Celery) and redis: present for future background jobs; nothing is queued on them today
```

| Container | Image | Role |
|---|---|---|
| `frontend` | nginx 1.31 with the Vite build | UI and reverse proxy. The only service reachable from the host |
| `backend` | Python 3.12, FastAPI | API, scans, unsubscribes, runs `alembic upgrade head` at start |
| `db` | postgres:16-alpine | Persistent state (volume `pgdata`) |
| `redis`, `worker` | redis 7, same image as the backend | Stub for future jobs. Scans currently run inside the API process |

## Code layout (`backend/app`)

| Folder | Contents |
|---|---|
| `api/` | One FastAPI router per area: accounts, auth (Microsoft sign-in), scan, emails, unsubscribe, spam, privacy, settings, session, audit |
| `core/` | `config` (environment defaults), `app_settings` (editable settings stored in the database), `security` (sessions, passwords), `crypto` (encryption), `audit`, `database` |
| `services/` | The work: `scanner`, `imap_client`, `classifier`, `llm`, `unsubscriber`, `bulk_unsub`, `safe_http`, `sender_check`, `registry`, `linkcheck`, `oauth_microsoft`, `domains` |
| `models/` | SQLAlchemy tables (see [reference.md](reference.md)) |
| `data/brokers.json` | The hand-checked data broker opt-out list |

The frontend (`frontend/src`) is one page per area (Dashboard, Accounts, Scan, Emails, Review, Privacy, Activity, Settings, Guides) plus markdown guides.

## Configuration layers

1. `.env` supplies defaults and the things needed before the app can start (`SECRET_KEY`, `DATABASE_URL`, admin password).
2. Settings you change in the app are stored in the `app_settings` table and win over `.env`. Secrets there are encrypted.
3. LLM settings live in `llm_profiles`: one saved profile per provider, plus which one is active.

## The scan pipeline

`POST /api/scan/start` creates a `scan_runs` row and runs the scan in the background (one running scan per account).

1. **Connect.** Microsoft accounts use an OAuth access token (renewed with the refresh token when it expires, which needs the app's client secret). IMAP accounts use the stored app password.
2. **Fetch.** Open the folder **read-only**, newest first, using `BODY.PEEK` so mail is not marked as read. Only the first 64 KB of each message is read.
3. **Filter.** Mail without a `List-Unsubscribe` header is counted and skipped: it can't be unsubscribed from, and it never reaches the model.
4. **Deduplicate.** `(account, Message-ID)` already stored means skip.
5. **Rules.** A *safe sender* rule stores the mail as "kept" with no model call. A *not spam* rule overrides a spam verdict.
6. **Classify.** The configured model gets the subject, sender and the first 500 characters of text, inside delimiters, and answers with JSON: category (newsletter, promotional, transactional, personal, spam, other) and a reason. Three model failures in a row stop the scan with an explanation.
7. **Store.** Marketing is stored for review (subject, sender, reason, unsubscribe link, one-click flag). Receipts and personal mail keep only the sender's company domain. Spam keeps its subject so false positives can be rescued.
8. **Optional verification.** If enabled, flagged senders get the technical checks below.
9. **Finish.** Counters are saved. If retention is on, old finished rows are purged.

A restart while a scan runs marks it failed at the next start.

## The unsubscribe pipeline

1. The **Review** page groups pending marketing mail by sender (`GET /api/unsubscribe/senders`) and shows the method for each: one-click, plain web link, or manual (email-only, `http`-only, or no link).
2. You select senders and confirm. `POST /api/unsubscribe/bulk` creates a job. **If dry-run is on in Settings the server forces a dry run**, whatever the request says. One job runs at a time.
3. For each sender, one request: a one-click sender gets the standard RFC 8058 `POST`; a plain-link sender gets a `GET`; the rest are marked manual. All requests go through `safe_http`. There is a one-second pause between senders.
4. The result is applied to every pending email from that sender: *confirmed* (one-click accepted), *request sent, unverified* (a plain link answered 2xx; it may only have shown a confirmation page), *manual*, or *failed* with the reason.
5. The audit log records host and result per sender, never the link (links often carry personal tokens).

You can also record an unsubscribe you did yourself (**Done by me**).

## `safe_http`: the only way to fetch a URL taken from the outside world

Used for unsubscribe links, link checks, the broker registry and the registry lookup service. It allows `https` on port 443 only, no credentials in the URL, resolves the host and refuses anything that is not a public address (private, loopback, link-local, carrier-grade NAT, cloud metadata, IPv4-mapped, NAT64, 6to4, Teredo), connects to the checked address while verifying the certificate against the host name, follows redirects by hand re-checking every hop (at most 5), ignores proxy settings, never reads a body unless a size cap is given, and has a 45-second overall deadline.

## Moving spam to Junk

A separate, manual action. For spam that sits in a normal folder, the app finds each message by an **exact** `Message-ID` match (a single hit only), and moves it to the server's Junk folder. It never deletes. In dry-run mode it opens the mailbox read-only and reports what would move.

## Verifying a sender

`POST /api/emails/{id}/verify` combines: the provider's own signature result for that message (only the topmost `Authentication-Results` header from a server known to add one), the domain's age (registry RDAP), its SPF/DMARC policies (DNS), and which domains your mailbox already holds mail from under the same brand word. An explainable score gives *authentic*, *unclear* or *suspicious*. Authentic means the sender is who its domain says, not that it is the brand in the display name, and not that you want the mail. An optional model explanation sees only the sender name, domain and these facts.

## Data broker features

- A hand-checked catalog (`data/brokers.json`) with your progress per broker (`broker_status`), re-check reminders, and a link-health monitor (`link_checks`; automatic weekly checks are off by default).
- A sync of California's public data broker registry (`registry_brokers`), with new/changed/removed tracking between syncs. Registry text is untrusted and rendered as plain text.
- An optional profile (name, city, state) encrypted in the database, used only to build web-search links that open in your browser.
- A read-only mailbox check for broker confirmation emails (headers only, with the sender-verification result; links are never extracted).

## What is stored where

See [reference.md](reference.md) for every table. In short: accounts and tokens (encrypted), scan history, one row per stored email, sender rules, unsubscribe jobs, settings, per-provider model settings, the audit log, broker progress, the registry copy, link-check results and cached domain facts.

## Background work

| What | When |
|---|---|
| Scan, bulk unsubscribe | Started by you; run in the API process |
| Startup recovery | At every start, scans and jobs left "running" are marked failed |
| Audit pruning | At start, entries older than 180 days are deleted |
| Retention purge | After each scan, if a retention period is set |
| Link monitor | Hourly check whether a weekly run is due, only if automatic link checks are on |
