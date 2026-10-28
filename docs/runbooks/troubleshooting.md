# Troubleshooting

Find the symptom, read the cause, apply the fix. For anything not here, `docker compose logs backend` and the **Activity** page are the first places to look.

## The app won't start or won't stay up

| Symptom | Cause | Fix |
|---|---|---|
| `docker compose up` says a port is already allocated | Something else uses port 3000 | Set `PORT=3001` (or another) in `.env` and `docker compose up -d` |
| Backend shows `unhealthy`, log mentions `SECRET_KEY must be set` | `SECRET_KEY` is missing, short (under 32 characters) or still a placeholder | `openssl rand -hex 32`, put it in `.env`, restart |
| Log mentions `ADMIN_PASSWORD must be set` | No admin password in `.env` and none saved in the database | Set one (8+ characters) in `.env` |
| `DATABASE_URL is not set` | `.env` missing or not read | Copy `.env.example` to `.env` in the project folder |
| Backend fails right after an upgrade, log shows an `alembic` error | A migration could not apply | Read the error; restore the backup taken before upgrading and report it |
| Log warns "default development password" | `.env` still has a placeholder database password | Rotate it ([operations.md](operations.md#rotating-secrets)) |

## Signing in

| Symptom | Cause | Fix |
|---|---|---|
| Login page returns after an update | The update changed how sessions are signed, or the password changed | Sign in again |
| "Too many failed attempts" | Five wrong passwords in five minutes (per address) | Wait five minutes. If it was you, check the password; see "Forgot the admin password" |
| 403 "Cross-site request blocked" when saving | You're browsing from an address that is not the **Frontend URL** | Open the app at the Frontend URL, or fix that URL in Settings → General |

## Microsoft sign-in and scanning

| Symptom | Cause | Fix |
|---|---|---|
| "Connect Microsoft" is disabled | Client ID or secret missing | Accounts → Microsoft → paste both → Save |
| Error `invalid_client` / AADSTS7000215 | The Azure **Secret ID** was pasted instead of the secret **Value** | Create a new secret in Azure and paste its Value |
| AADSTS50011 (redirect URI mismatch) | The address in Azure differs from the one shown on the Accounts page | Copy the exact address from Accounts into Azure (Web platform). Off `localhost` it must be `https://` |
| AADSTS700016 | Wrong client ID, or tenant setting does not match the account type | Re-copy the Application (client) ID; tenant `consumers` for Outlook.com/Hotmail |
| AADSTS65001 | The IMAP permission was not added or needs admin consent | Add `IMAP.AccessAsUser.All` (Office 365 Exchange Online, delegated) |
| `invalid_state` after signing in | The sign-in took over ten minutes or the app restarted mid-way | Press Connect again |
| Scan fails: "client secret is missing" | The Microsoft sign-in expired and renewing it needs the client secret | Re-enter the client secret on Accounts, then retry |
| Scan fails: "mail server rejected the login" | Wrong or revoked IMAP app password; for Microsoft the sign-in was revoked | Re-add the app password or reconnect the account |
| "Can't be read (SECRET_KEY changed?)" / "Cannot decrypt" | `.env` has a different `SECRET_KEY` than the one that encrypted the data | Restore the original key. If lost, remove and re-add accounts and re-enter keys |
| Folder list fails | Same causes as above, or the mail server is unreachable | You can still type the folder name |

## Models

| Symptom | Cause | Fix |
|---|---|---|
| Ollama test: "Pick a model" / "not installed" | No model chosen or it isn't pulled | Click the Model field and pick an installed one, or `ollama pull <model>` |
| Ollama "connection error" | The server can't reach Ollama | In Docker, `localhost` means your computer (the app translates it to `host.docker.internal`). For another machine use its address and check firewalls |
| Scan stops: "The LLM is not responding correctly" | Three model calls in a row failed | Run **Test connection**, fix the cause, scan again (stored emails are skipped) |
| Claude CLI: "is not installed in this image" | The image was built without the CLIs | Set `INSTALL_AI_CLIS=true` in `.env`, `docker compose up --build -d` |
| Claude CLI: 401 "Invalid bearer token" | You pasted the one-time login code (it contains `#`) instead of the token | In a normal terminal run `claude setup-token`, paste the code **into the terminal**, then copy the token it prints |
| Claude CLI: "Not logged in" | No token saved | Paste the token in Settings → LLM → Claude subscription |
| Codex CLI errors | Experimental; needs `codex login` on the host and the extra compose file | See [home-server.md](../home-server.md) and the in-app guide |

## Review, unsubscribe, spam

| Symptom | Cause | Fix |
|---|---|---|
| Review is empty after a scan | Nothing had an unsubscribe header, mail was already seen, or it was classed spam/receipt | Check the scan card counts; Emails page → Spam and Kept tabs; use **Not spam** if needed |
| "Unsubscribe" does nothing visible | An old build (fixed) hid the confirmation below the screen | Update and hard-refresh the page |
| Run says "dry run" and nothing was sent | Dry-run is on in Settings | Turn it off in Settings → General, then tick "Actually send" in the pop-up |
| "Request sent, unverified" | A plain link answered OK but may only show a confirmation page | Open the sender's page yourself if the mail continues |
| "Another bulk unsubscribe is still running" | One job at a time | Wait; interrupted jobs are marked failed at the next start |
| Spam move: "Could not find a Junk folder" | The account has no folder flagged Junk or named Junk/Spam | Create or rename one |
| Spam move: some messages "no longer in the folder" | They were moved or deleted since the scan | Rescan; harmless |

## Privacy page

| Symptom | Cause | Fix |
|---|---|---|
| "Can't be auto-checked" on a link | The site blocks automated requests | Open the link yourself to verify |
| Registry sync: "answered HTTP 503" or "synced a few minutes ago" | The state's site throttles; the app also limits syncs to one per ten minutes | Wait and retry |
| "Check my mailbox" finds nothing | No recent mail from those brokers in Inbox/Junk, or the sign-in expired | Widen the days; fix the sign-in |
| Verification says "signature not checked" | Your mail server doesn't add provider verdict headers the app can trust, or the message could not be read | The domain checks still apply |
