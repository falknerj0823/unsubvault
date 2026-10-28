# Running UnsubVault on a home server or NAS

UnsubVault is a single-user app. Run it on a machine you control, keep it on your home network, and put HTTPS in front of it.

## 1. Requirements
- Docker with Compose. x86-64 or arm64: the images are built on the machine itself (`docker compose up --build`), so the first start takes a few minutes.
- Do **not** run it in a folder that is shared over the network or readable by other users. `.env` holds your admin password, `SECRET_KEY` and database password. Use `chmod 600 .env`, and keep the project folder out of any SMB/NFS share.

## 2. Reach it from other devices (safely)
By default the UI listens on `127.0.0.1` only. To open it from another computer, publish it on the server's network address and put a reverse proxy with HTTPS in front:

```bash
# .env
BIND_ADDRESS=0.0.0.0     # or the server's own LAN address
PORT=8080
```

Example Caddy site (any reverse proxy works; use your own host name and server address):

```
unsubvault.home {
    tls internal
    reverse_proxy 192.0.2.10:8080
}
```

Never expose this app to the internet. It has one password and no other protection.

## 3. HTTPS and Microsoft sign-in
Microsoft only accepts a plain `http://` redirect address for `localhost`. For any other host name it must be `https://`.
1. In **Settings → General**, set **Frontend URL** to your HTTPS address (for example `https://unsubvault.home`). Cookies become `Secure` automatically.
2. In your Azure app registration, add `https://unsubvault.home/api/auth/microsoft/callback` as a Web redirect URI. The Accounts page shows the exact value.
3. The device you browse from must trust the proxy's certificate (for `tls internal`, install the proxy's root certificate).

## 4. Local AI models
`localhost` in the LLM settings means the server itself. Point the Ollama base URL at the machine that runs Ollama, for example `http://192.0.2.20:11434`, and make sure any firewall between the two allows it. `host.docker.internal` refers to the server running Docker.

## 5. Moving an existing install
1. On the old machine: `docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > unsubvault.sql` (keep this file private).
2. Copy `.env` to the new machine. **`SECRET_KEY` must stay identical**, or every stored token, key and the profile become unreadable.
3. On the new machine: `docker compose up -d db`, then `docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < unsubvault.sql`, then `docker compose up --build -d`.
4. If the address changed, update the Frontend URL and the Azure redirect URI (section 3). Your stored sign-in does not need redoing.

## 6. Backups
Run a nightly `pg_dump` into a folder only you can read, and keep `SECRET_KEY` somewhere separate (a password manager). A database dump contains mail subjects and sender addresses in plain text, so treat it like the mailbox itself.

## 7. Updates
`git pull && docker compose up --build -d`. Migrations run on start, and every service restarts on its own after a reboot.
