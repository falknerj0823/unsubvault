# Security policy

UnsubVault is **pre-alpha, single-user software** meant to run on your own machine or home server. It handles
mailbox access and API keys, so please report problems privately.

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** (the "Report a vulnerability" button on the Security tab).
Please do not open a public issue for something exploitable. Include what you found, how to reproduce it,
and what an attacker could do. You'll get an answer as soon as I can manage; this is a one-person project.

## What the app does to protect you

- Login with one admin password (scrypt-hashed); sessions are signed, HttpOnly cookies; failed logins are rate limited per client address (behind Docker Desktop every local request appears to come from one address, so repeated failures briefly lock all local sign-ins).
- Writes from another website are rejected (SameSite cookies plus an Origin check), and **Settings → Sign out of every browser** ends all sessions.
- Provider tokens, IMAP passwords, API keys and your broker-search profile are encrypted at rest (Fernet; separate keys derived from `SECRET_KEY`). **Mail subjects, sender names and addresses, the model's reasons, unsubscribe links and the activity log are stored as plain text** (see the README).
- All outbound requests to URLs taken from emails go through one guarded path: https only, port 443, public
  addresses only, connection pinned to the checked address, redirects re-checked at every hop.
- Scans read mail read-only. Moving spam to Junk is the only change the app makes to a mailbox. It matches each message by an exact Message-ID check (a single exact match only), never deletes, and only checks (read-only) while dry-run mode is on.
- The "verified sender" results rely on your mail provider's own Authentication-Results header, and only the topmost one from servers known to add it (Microsoft, Google) or that name their own domain. Elsewhere the result is "unknown".
- An activity log records sensitive actions without storing secrets or email content. The app never edits or deletes entries except pruning those older than 180 days; it is not tamper-proof against someone with database access.

## Known limitations (please don't report these as new)

- One user, one password. There are no roles. Do not expose the app to the internet without a TLS reverse proxy
  and extra authentication in front of it.
- The login rate limiter and the in-progress Microsoft sign-ins are in memory and reset on restart. Sessions are signed tokens that last 7 days and survive restarts; use "Sign out of every browser" or change the password to end them.
- The administrator can make the server connect to any address (LLM base URL, IMAP host) because local models and home mail servers need that. It is a feature for the admin, not a hole for other users.
- Containers run as root. The optional CLI providers (`INSTALL_AI_CLIS=true`) add third-party npm packages to the image.
- IP addresses in the activity log are approximate behind a proxy.
- Data broker and registry information is third-party data and can be wrong or out of date.
