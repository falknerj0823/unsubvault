# Connect Outlook / Hotmail / Microsoft 365

Personal Outlook.com, Hotmail and Live mailboxes no longer accept passwords over IMAP, so UnsubVault signs in through Microsoft OAuth. That needs a small "app registration" in your own Microsoft account. It's free, takes about 10 minutes, and the app is yours alone: nobody else can use it.

> **Status:** written from Microsoft's documentation. The UnsubVault side is tested up to the Microsoft sign-in page; a full run against a real Microsoft account has not been verified yet. If a step doesn't match what you see, Microsoft may have moved a menu.

## 1. Create the app registration

1. Go to **https://entra.microsoft.com** (or portal.azure.com) and sign in with the Microsoft account you want to scan. If it offers to create a free directory or tenant, accept. You do not need a paid Azure subscription.
2. Open **Entra ID → App registrations → New registration**.
3. **Name:** `UnsubVault` (anything you like).
4. **Supported account types:**
   - Outlook.com / Hotmail / Live only: **Personal Microsoft accounts only**.
   - Work or school mailboxes too: **Accounts in any organizational directory and personal Microsoft accounts**.
5. **Redirect URI:** platform **Web**, and paste exactly:

   `{{REDIRECT_URI}}`

   It has to match character for character, including `http`/`https` and the port. If you change the "Frontend URL" in Settings, come back and update this.
6. Click **Register**.

## 2. Copy the client ID

On the app's **Overview** page, copy **Application (client) ID**. You'll paste it into UnsubVault in step 4.

## 3. Create a client secret and add the IMAP permission

1. **Certificates & secrets → New client secret.** Pick an expiry (up to 24 months) and click Add.
2. Copy the secret's **Value** column right now; Microsoft only shows it once. Do **not** copy the "Secret ID" column, which is a different thing and causes a "invalid client secret" error.
3. **API permissions → Add a permission → APIs my organization uses →** search for **Office 365 Exchange Online → Delegated permissions →** tick **IMAP.AccessAsUser.All → Add permissions**.

## 4. Enter it in UnsubVault

All on the **Accounts** page, in the **Microsoft** section:

1. Under **Set up Microsoft app credentials**, paste the **client ID** and the **client secret** (the Value).
2. **Tenant:** `consumers` for personal accounts only, `common` if you chose the "any organizational directory and personal" option, or your tenant ID for a single work tenant.
3. Click **Save credentials**. The status changes to "Ready to connect".

## 5. Connect

Click **Connect Microsoft account** in the same section, sign in, and approve the permission. You land back on the Accounts page with the mailbox listed under Microsoft.

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `AADSTS50011` redirect URI mismatch | The redirect URI in Azure differs from the one above. Re-copy it. |
| `AADSTS7000215` invalid client secret | You pasted the Secret ID, not the Value. Make a new secret and copy the Value. |
| `AADSTS700016` application not found | Wrong client ID, or the account type setting doesn't match the tenant value in Settings. |
| `AADSTS65001` consent required | The IMAP permission wasn't added, or your organization's admin must approve it. |
| `invalid_state` after signing in | The sign-in took more than 10 minutes, or the backend restarted mid-sign-in. Try again. |
| Sign-in works but scans fail later | IMAP may be disabled on the mailbox (work accounts: ask your admin). |

Your tokens are stored encrypted in the local database using your `SECRET_KEY`. If you ever change `SECRET_KEY`, reconnect your accounts.
