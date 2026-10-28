# Security model

This page explains what UnsubVault protects, against whom, how, and what it does not protect. For reporting a vulnerability see [SECURITY.md](../SECURITY.md).

## What it holds that matters

| Asset | Where | Why it matters |
|---|---|---|
| Mailbox access (Microsoft tokens, IMAP app passwords) | `accounts` table, encrypted | Lets anyone who has them read the mailbox |
| API keys and the subscription token for a model | `llm_profiles`, encrypted | Costs money, can be abused |
| Admin session and password | cookie, `app_settings` (scrypt hash) | Controls everything above |
| Mail metadata (subjects, sender addresses, model reasons, unsubscribe links) | `email_records`, **plain text** | Reveals who you deal with |
| Your search profile (name, city, state) | `app_settings`, encrypted | Personal details |
| `SECRET_KEY` | `.env` | Decrypts all of the above |

## Who it defends against

| Threat | How it is handled | Tested in |
|---|---|---|
| **A malicious email** tries to make the server fetch an internal address (SSRF) through an unsubscribe link | Every URL goes through `safe_http`: https/443 only, public addresses only, connection pinned to the checked address, redirects re-checked, deadline | `bulk_unsubscribe`, `hardening` |
| A malicious email carries a **prompt injection** | The model only returns a classification; its output is parsed as JSON and used for labels. For the optional CLI providers all tools are disabled and the environment is limited to an allowlist | `hardening`, `scan_pipeline` |
| A malicious email **forges "verified" headers** | Only the topmost `Authentication-Results` header from a server known to add one is trusted; input is size-capped | `hardening` |
| A crafted **Message-ID** makes a mailbox search match many messages and move them to Junk | IDs are validated, every search hit is re-checked for an exact match, a single exact match is required | `hardening`, `spam_move` |
| A **website you visit** tries to act as you (CSRF) | HttpOnly SameSite=Lax cookie, CORS limited to the app's own origin, state-changing requests rejected unless their `Origin` is the app's | `hardening`, `auth_settings_llm` |
| **Someone on your network** tries the login page | Password hashed with scrypt, failed logins rate limited, the app listens on loopback unless you change it | `auth_settings_llm` |
| **A stolen database dump or backup** | Tokens, keys and the profile are encrypted with keys derived from `SECRET_KEY` | `auth_settings_llm`, `hardening` |
| A **stolen session cookie** | Signed, 7-day expiry, ended by changing the password or **Sign out of every browser** | `hardening` |
| **Untrusted text** from the broker registry or the web | Stored and rendered as plain text, size-capped, truncated files refused | `registry_and_links` |
| **Dependency problems** | Pinned versions, CI on every change, Dependabot (patch-only for Python), a stable base image | CI |

## Safety rails on actions

- Dry-run mode is on by default and enforced on the **server**, not only in the UI.
- Scans never change the mailbox. The only mailbox change the app can make is moving spam to Junk, which never deletes and is previewed first.
- Spam, receipts and personal mail can never be unsubscribed from (the job only touches mail waiting for review).
- Every sensitive action is written to the audit log without secrets or mail content.

## What it does **not** protect

- **Anyone who can read the database or its backups** can read subjects, sender names and addresses, model reasons and unsubscribe links, because those are plain text. Protect the volume, backups and the machine.
- **Anyone who gets `.env`** can decrypt everything. Keep it `chmod 600` and out of shared folders.
- **There is one administrator.** That person can point the app at any LLM or mail server address (needed for local models), so the admin password is the key to your network position as well as your mail.
- **Sessions are stateless** tokens valid for 7 days; they survive restarts. Use *Sign out of every browser* to end them.
- **No TLS by itself.** Put an HTTPS proxy in front before using it from other devices ([home-server.md](home-server.md)). Never expose it to the internet.
- **Containers run as root.** The optional CLI providers add third-party packages to the image.
- **Rate limiting is in memory** and keyed by the address nginx reports; behind Docker Desktop all local requests share one address.
- **Third-party services see some data:** the model provider you choose sees subject, sender and 500 characters of marketing mail; DNS and registry servers see the domains you verify; broker sites see requests when you press the link check or turn it on.
- **Broker and registry data is third party** and can be wrong or out of date.

## Network connections

Your mail server; the model provider you choose; `login.microsoftonline.com` (Microsoft sign-in); sender unsubscribe links you approve; `cppa.ca.gov` (registry sync, when you press the button); `data.iana.org` and registry RDAP servers plus DNS (sender checks); broker pages (link checks, when you press the button or enable the weekly check). No telemetry. The CLI providers turn off their own telemetry and auto-update where they allow it.

## Reviewing this

Two independent read-only audits were run before publication (an early one that found missing authentication, plaintext credentials and an unguarded fetcher, and a final one that found test data from a real inbox in the fixtures and an IMAP substring-match risk). All findings were fixed or documented, and each fix has a regression test in `backend/tests/hardening.py`.
