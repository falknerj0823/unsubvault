import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2, Mail, BookOpen, Copy, Check, ChevronDown, ChevronRight } from "lucide-react";
import { Account, getAccounts, deleteAccount, addImapAccount, getAuthInfo, getAppSettings, saveAppSettings } from "../lib/api";

const PRESETS: Record<string, { host: string; port: string }> = {
  "Gmail (app password)": { host: "imap.gmail.com", port: "993" },
  "iCloud (app-specific password)": { host: "imap.mail.me.com", port: "993" },
  "Yahoo (app password)": { host: "imap.mail.yahoo.com", port: "993" },
  "Fastmail (app password)": { host: "imap.fastmail.com", port: "993" },
};
const OAUTH_ERRORS: Record<string, string> = {
  microsoft_not_configured: "Microsoft sign-in isn't set up yet. Add your client ID and secret in the Microsoft section below.",
  microsoft_start_failed: "Couldn't start Microsoft sign-in. Check the client ID, secret and tenant below.",
  invalid_state: "That sign-in expired or was already used. Try Connect again.",
  token_exchange_failed: "Microsoft rejected the sign-in. Check the redirect URI and client secret (see the guide).",
  invalid_client: "Microsoft rejected the client secret. The usual cause is pasting the Secret ID instead of the secret Value. Create a new secret in Azure and paste its Value.",
  access_denied: "Sign-in was cancelled.",
  no_email_in_token: "Microsoft didn't return an email address for that account.",
};

const input = "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300";
const primary = "flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50";
const secondary = "flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-50";

function AccountList({ accounts, onDelete }: { accounts: Account[]; onDelete: (id: number) => void }) {
  if (accounts.length === 0) return <p className="text-sm text-gray-400">No accounts connected yet.</p>;
  return (
    <div className="space-y-2">
      {accounts.map(acc => (
        <div key={acc.id} className="border border-gray-200 rounded-lg px-4 py-3 flex items-center justify-between">
          <div>
            <p className="font-medium text-gray-800 text-sm">{acc.label}</p>
            <p className="text-xs text-gray-400 mt-0.5">{acc.email_address}</p>
          </div>
          <button onClick={() => onDelete(acc.id)} className="text-red-400 hover:text-red-600" title="Remove account"><Trash2 size={16} /></button>
        </div>
      ))}
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="bg-white border border-gray-200 rounded-xl p-5 mb-6 space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-gray-800">{title}</h3>
        <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>
      </div>
      {children}
    </section>
  );
}

function Collapsible({ label, open, onToggle, children }: { label: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div className="border border-gray-100 rounded-lg bg-gray-50">
      <button onClick={onToggle} className="w-full flex items-center gap-1 px-3 py-2 text-sm font-medium text-gray-700">
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}{label}
      </button>
      {open && <div className="px-3 pb-3 space-y-3">{children}</div>}
    </div>
  );
}

function MicrosoftCard({ accounts, onDelete }: { accounts: Account[]; onDelete: (id: number) => void }) {
  const qc = useQueryClient();
  const { data: auth } = useQuery({ queryKey: ["auth-info"], queryFn: getAuthInfo });
  const { data } = useQuery({ queryKey: ["app-settings"], queryFn: getAppSettings });
  const [open, setOpen] = useState<boolean | null>(null);
  const [clientId, setClientId] = useState(""); const [secret, setSecret] = useState(""); const [tenant, setTenant] = useState("consumers");
  const [copied, setCopied] = useState(false);
  useEffect(() => { if (data) { setClientId(data.microsoft_client_id); setTenant(data.microsoft_tenant || "consumers"); } }, [data]);
  const configured = !!auth?.configured;
  const showSetup = open ?? !configured;  // open by default until credentials exist
  const secretSaved = !!data?.microsoft_client_secret_set;
  const ready = clientId.trim() !== "" && (secret.trim() !== "" || secretSaved);
  const save = useMutation({
    mutationFn: () => saveAppSettings({ microsoft_client_id: clientId.trim(), microsoft_tenant: tenant.trim(), ...(secret ? { microsoft_client_secret: secret.trim() } : {}) }),
    onSuccess: () => { setSecret(""); qc.invalidateQueries({ queryKey: ["app-settings"] }); qc.invalidateQueries({ queryKey: ["auth-info"] }); },
  });
  const copy = () => { navigator.clipboard?.writeText(auth?.redirect_uri ?? "").then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {}); };
  return (
    <Section title="Microsoft: Outlook, Hotmail, Live, 365" subtitle="Signs in with Microsoft. Needs a free Azure app registration, set up once.">
      <div className="flex flex-wrap items-center gap-3">
        {configured
          ? <a href="/api/auth/microsoft/login" className={primary}><Mail size={16} /> Connect Microsoft account</a>
          : <button disabled className={primary}><Mail size={16} /> Connect Microsoft account</button>}
        <span className={`text-xs ${configured ? "text-green-700" : "text-amber-700"}`}>{configured ? "Ready to connect" : "Set up the app credentials below first"}</span>
        <Link to="/guides" className="flex items-center gap-1 text-xs text-blue-600 underline"><BookOpen size={13} /> Step-by-step guide</Link>
      </div>
      <Collapsible label={configured ? "Microsoft app credentials" : "Set up Microsoft app credentials"} open={showSetup} onToggle={() => setOpen(!showSetup)}>
        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">1. Redirect URI to register in Azure (Web platform)</p>
          <div className="flex gap-2">
            <code className="flex-1 bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs break-all">{auth?.redirect_uri ?? "…"}</code>
            <button onClick={copy} className="px-3 border border-gray-200 bg-white rounded-lg text-gray-500 hover:bg-gray-50" title="Copy">{copied ? <Check size={15} /> : <Copy size={15} />}</button>
          </div>
        </div>
        <p className="text-xs font-medium text-gray-600">2. Values from your Azure app registration</p>
        <input className={input} placeholder="Application (client) ID" value={clientId} onChange={e => setClientId(e.target.value)} />
        <input type="password" autoComplete="off" className={input} value={secret} onChange={e => setSecret(e.target.value)}
          placeholder={secretSaved ? "•••••••• client secret saved (leave blank to keep)" : "Client secret VALUE (not the Secret ID)"} />
        <input className={input} list="ms-tenants" placeholder="Tenant" value={tenant} onChange={e => setTenant(e.target.value)} />
        <datalist id="ms-tenants"><option value="consumers" /><option value="common" /><option value="organizations" /></datalist>
        <p className="text-xs text-gray-400"><code>consumers</code> = Outlook.com / Hotmail / Live only · <code>common</code> = personal + work/school.</p>
        <div className="flex items-center gap-3">
          <button disabled={!ready || save.isPending} onClick={() => save.mutate()} className={secondary}>{save.isPending ? "Saving…" : "Save credentials"}</button>
          {save.isSuccess && <span className="text-sm text-green-700">Saved.</span>}
          {save.isError && <span className="text-sm text-red-600">{(save.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Couldn't save."}</span>}
        </div>
      </Collapsible>
      <AccountList accounts={accounts} onDelete={onDelete} />
    </Section>
  );
}

function GoogleCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["app-settings"], queryFn: getAppSettings });
  const [open, setOpen] = useState(false);
  const [clientId, setClientId] = useState(""); const [secret, setSecret] = useState("");
  useEffect(() => { if (data) setClientId(data.google_client_id); }, [data]);
  const save = useMutation({
    mutationFn: () => saveAppSettings({ google_client_id: clientId.trim(), ...(secret ? { google_client_secret: secret.trim() } : {}) }),
    onSuccess: () => { setSecret(""); qc.invalidateQueries({ queryKey: ["app-settings"] }); },
  });
  return (
    <Section title="Google: Gmail" subtitle="Google sign-in isn't built yet. Add Gmail now with an app password in the IMAP section below (pick the Gmail preset).">
      <Collapsible label="Google app credentials (not used yet)" open={open} onToggle={() => setOpen(!open)}>
        <input className={input} placeholder="Client ID" value={clientId} onChange={e => setClientId(e.target.value)} />
        <input type="password" autoComplete="off" className={input} value={secret} onChange={e => setSecret(e.target.value)}
          placeholder={data?.google_client_secret_set ? "•••••••• saved (leave blank to keep)" : "Client secret"} />
        <div className="flex items-center gap-3">
          <button disabled={save.isPending} onClick={() => save.mutate()} className={secondary}>Save credentials</button>
          {save.isSuccess && <span className="text-sm text-green-700">Saved.</span>}
        </div>
      </Collapsible>
    </Section>
  );
}

function ImapCard({ accounts, onDelete }: { accounts: Account[]; onDelete: (id: number) => void }) {
  const qc = useQueryClient();
  const [show, setShow] = useState(false);
  const [form, setForm] = useState({ label: "", host: "", port: "993", username: "", password: "" });
  const add = useMutation({
    mutationFn: () => addImapAccount({ ...form, port: Number(form.port) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setShow(false); setForm({ label: "", host: "", port: "993", username: "", password: "" }); },
  });
  return (
    <Section title="IMAP: Gmail, iCloud, Yahoo, Fastmail, other" subtitle="Uses an app password, not your normal password. Not for Outlook.com / Hotmail (Microsoft disabled that).">
      <div><button onClick={() => setShow(v => !v)} className={secondary}>{show ? "Cancel" : "Add IMAP account"}</button></div>
      {show && (
        <div className="space-y-3 border border-gray-100 rounded-lg bg-gray-50 p-3">
          <select className={input} defaultValue="" onChange={e => { const p = PRESETS[e.target.value]; if (p) setForm(f => ({ ...f, ...p })); }}>
            <option value="">Quick fill a provider…</option>
            {Object.keys(PRESETS).map(k => <option key={k} value={k}>{k}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-3">
            {[{ k: "label", p: "Label" }, { k: "host", p: "IMAP host" }, { k: "port", p: "Port" }, { k: "username", p: "Username / email" }, { k: "password", p: "App password", t: "password" }].map(({ k, p, t }) => (
              <input key={k} type={t ?? "text"} placeholder={p} className={input}
                value={(form as Record<string, string>)[k]} onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))} />
            ))}
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => add.mutate()} disabled={add.isPending} className={primary}>{add.isPending ? "Saving…" : "Save account"}</button>
            {add.isError && <span className="text-sm text-red-600">Couldn't save the account.</span>}
          </div>
        </div>
      )}
      <AccountList accounts={accounts} onDelete={onDelete} />
    </Section>
  );
}

export default function Accounts() {
  const qc = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: getAccounts });
  const del = useMutation({ mutationFn: deleteAccount, onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }) });
  const [params, setParams] = useSearchParams();
  const connected = params.get("connected"); const oauthError = params.get("error");
  const by = (t: string) => accounts.filter(a => a.provider_type === t);
  return (
    <div className="max-w-3xl">
      <h2 className="text-2xl font-bold text-gray-800 mb-6">Email Accounts</h2>
      {connected && <p className="mb-4 text-sm text-green-800 bg-green-50 border border-green-200 rounded-lg px-3 py-2">Connected {connected}. <button className="underline" onClick={() => setParams({})}>Dismiss</button></p>}
      {oauthError && <p className="mb-4 text-sm text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{OAUTH_ERRORS[oauthError] ?? `Sign-in failed (${oauthError}).`} <button className="underline" onClick={() => setParams({})}>Dismiss</button></p>}
      <MicrosoftCard accounts={by("microsoft")} onDelete={id => del.mutate(id)} />
      <GoogleCard />
      <ImapCard accounts={by("imap")} onDelete={id => del.mutate(id)} />
    </div>
  );
}
