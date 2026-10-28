# Add Gmail, iCloud, Yahoo or any IMAP mailbox

For these providers UnsubVault uses an **app password**: a separate password that works only for mail access and can be revoked at any time. Your normal password is never used. Use **Accounts → Add IMAP account**.

> **Not for Outlook.com / Hotmail / Live.** Microsoft turned off password logins for personal mailboxes. Use the Microsoft guide.

## Gmail

1. Turn on **2-Step Verification**: https://myaccount.google.com/security
2. Create an app password at https://myaccount.google.com/apppasswords. Name it `UnsubVault` and copy the 16-character password.
3. In UnsubVault: host `imap.gmail.com`, port `993`, username = your full Gmail address, password = the app password (spaces don't matter).

Google sign-in (OAuth) for Gmail is not built yet; the app password route is the way for now.

## Other providers

| Provider | IMAP host | Port | Password to use |
|---|---|---|---|
| iCloud Mail | `imap.mail.me.com` | 993 | App-specific password from https://account.apple.com (username = your iCloud email) |
| Yahoo Mail | `imap.mail.yahoo.com` | 993 | App password from Account Info → Security |
| Fastmail | `imap.fastmail.com` | 993 | App password from Settings → Privacy & Security |
| Proton Mail | needs the paid Proton Bridge app | | Not supported directly |
| Your own domain | your provider's IMAP host | usually 993 | Your mailbox password or app password |

The **Add IMAP account** form has presets that fill the host and port for you.

## Troubleshooting

- **Login failed:** almost always the normal password was used instead of an app password, or 2-Step Verification is off.
- **Connection refused / timeout:** wrong host or port, or your network blocks outbound port 993.
- UnsubVault reads mail read-only for scanning; it never deletes messages.
