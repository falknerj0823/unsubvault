# Design decisions

Why the app behaves the way it does. Each entry says what was decided, why, and the cost.

1. **Spam is never unsubscribed from.** An unsubscribe request to a spammer confirms the address is live and contacts a link chosen by a scammer. Spam is stored (so it is not re-classified) and can be moved to Junk, which also trains the mail provider's filter. *Cost:* a real but unwanted sender wrongly labelled spam needs "Not spam" first.
2. **Dry-run is the default and the server enforces it.** A UI checkbox can be bypassed by a crafted request; the server setting cannot. *Cost:* the first real run needs one deliberate setting change.
3. **Scans are read-only; the only mailbox change is moving spam to Junk, and nothing is ever deleted.** Mistakes must be recoverable. *Cost:* the app can't empty a mailbox for you.
4. **Decide per sender, not per email.** One link covers all of a sender's mail, and decisions should not need repeating ("Safe sender", "Not spam", "Done by me" are remembered).
5. **Store less.** Receipts, account notices and personal mail keep only the sender's company domain, because that is enough to warn about mixed senders and nothing more is needed. Retention and "delete all scan data" exist. *Cost:* you can't browse those emails in the app.
6. **Only one way to fetch a URL from the outside world** (`safe_http`). Any other code path doing network requests to attacker-influenced addresses is a bug.
7. **Classification is advice, not authority.** The model can be wrong (it once called a real vendor domain spam). So every verdict is reversible, shows its reason, and a separate technical "verify sender" tool exists. Verdict wording is deliberate: *authentic* means the domain is who it says, not that it is the brand named, and not that you want the mail.
8. **A "name does not match the domain" mismatch is a prompt to verify, not a verdict.** Real companies use vendor mail domains.
9. **Secrets are encrypted with keys derived from `SECRET_KEY` (separate keys per purpose).** Old data stays readable. If `SECRET_KEY` is lost, secrets must be re-entered; there is no recovery.
10. **Models are your choice.** Local Ollama keeps mail text on your machine; API providers and the Claude Code / Codex CLIs are options. Each provider keeps its own saved settings so you can switch back and forth. A saved key never follows a changed endpoint.
11. **Provider-trusted authentication results only.** `Authentication-Results` headers can be forged by senders, so only the topmost one from a server known to add it is used; otherwise the answer is "unknown".
12. **Registry and web text is untrusted.** Shown as plain text, never as links we generate from it.
13. **A hand-checked broker catalog plus an official registry sync, not scraping.** The app tracks and guides; it does not submit opt-out forms or solve CAPTCHAs, because that needs your identity sent to every broker and breaks constantly.
14. **Automatic broker link checks are off by default.** They contact broker sites from your connection; you can run them by hand.
15. **Dependabot is quiet on purpose.** Monthly, grouped, no major versions; for Python only patch releases, because minor releases of SQLAlchemy and the model SDKs broke migrations in CI. Minor and major upgrades are done by hand after the full suite passes.
16. **Publishing from a new repository.** GitHub keeps a hidden ref for every pull request forever, so a force-push cannot scrub history that a pull request (such as one opened by Dependabot) points at. If sensitive history must not become public, publish a fresh repository.
17. **Single administrator, single user.** Multi-user would need per-user data separation, roles and a much larger threat model. It is out of scope.
