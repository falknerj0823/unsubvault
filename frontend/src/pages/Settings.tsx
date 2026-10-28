import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { browserTimezone, formatTime, timezoneList } from "../lib/time";
import { logoutEverywhere, deleteScanData, getLLM, saveLLM, testLLM, LLMConfigInput, listLLMModels, getAppSettings, saveAppSettings, AppSettingsInput, changePassword } from "../lib/api";

const INFO: Record<string, { label: string; needsKey: boolean; keyLabel: string; needsUrl: boolean; urlHint: string; note?: string }> = {
  openai: { label: "OpenAI (API key)", needsKey: true, keyLabel: "API key", needsUrl: false, urlHint: "" },
  anthropic: { label: "Anthropic (API key)", needsKey: true, keyLabel: "API key", needsUrl: false, urlHint: "" },
  ollama: { label: "Ollama (local)", needsKey: false, keyLabel: "", needsUrl: true, urlHint: "http://host.docker.internal:11434" },
  openai_compatible: { label: "OpenAI-compatible (LM Studio, vLLM, OpenRouter, Groq…)", needsKey: true, keyLabel: "API key (optional for local servers)", needsUrl: true, urlHint: "https://openrouter.ai/api/v1" },
  claude_cli: { label: "Claude subscription (Claude Code CLI)", needsKey: true, keyLabel: "Token from `claude setup-token`", needsUrl: false, urlHint: "",
    note: "Needs the image built with INSTALL_AI_CLIS=true. Run `claude setup-token` on your machine and paste the token here. Defaults to the cheapest model (Haiku) at low effort; type another model name to override." },
  codex_cli: { label: "ChatGPT subscription (Codex CLI) — experimental", needsKey: false, keyLabel: "", needsUrl: false, urlHint: "",
    note: "Needs the image built with INSTALL_AI_CLIS=true and ~/.codex mounted (docker-compose.cli.yml). Not yet tested against a real ChatGPT login." },
};

const field = "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";

function LLMSection() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["llm"], queryFn: getLLM });
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);

  // Each provider keeps its own saved model, URL and key; picking one loads that profile.
  const loadProfile = (p: string) => {
    const saved = data?.profiles[p];
    setProvider(p); setModel(saved?.model ?? ""); setBaseUrl(saved?.base_url ?? ""); setApiKey(""); setClearKey(false);
  };
  useEffect(() => { if (data) loadProfile(data.active); }, [data]);  // eslint-disable-line react-hooks/exhaustive-deps

  const info = INFO[provider] ?? INFO.openai;
  const [models, setModels] = useState<string[]>([]);
  const [modelsErr, setModelsErr] = useState("");
  const body = (): LLMConfigInput => ({ provider, model, base_url: info.needsUrl ? baseUrl : "",
    ...(clearKey ? { api_key: "" } : apiKey ? { api_key: apiKey } : {}) });
  const refreshModels = () => {
    if (!["ollama", "openai_compatible"].includes(provider)) { setModels([]); setModelsErr(""); return; }
    listLLMModels(body()).then(r => { setModels(r.models); setModelsErr(r.ok ? "" : r.error ?? "Could not list models"); })
      .catch(() => { setModels([]); setModelsErr("Could not list models"); });
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (data) refreshModels(); }, [data, provider]);
  const save = useMutation({ mutationFn: () => saveLLM(body()), onSuccess: d => { qc.setQueryData(["llm"], d); qc.invalidateQueries({ queryKey: ["settings"] }); } });
  const test = useMutation({ mutationFn: () => testLLM(body()) });
  const keySet = data?.profiles[provider]?.api_key_set && !clearKey;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">LLM</h2>
        <p className="text-sm text-gray-500 mt-1">Which model classifies your emails. Subject, sender and the first 500 characters of each email are sent to the provider you pick here.</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <label className="block text-sm font-medium text-gray-700">Provider
          <select className={`${field} mt-1`} value={provider} onChange={e => { loadProfile(e.target.value); test.reset(); }}>
            {(data?.providers ?? Object.keys(INFO)).map(p => (
              <option key={p} value={p}>{INFO[p]?.label ?? p}{p === data?.active ? "  — active" : data?.profiles[p] ? "  ✓ saved" : ""}</option>
            ))}
          </select>
          <span className="text-xs text-gray-400 mt-1 block">
            Saving makes this provider the active one. Other providers keep their saved settings and keys, so you can switch back any time.
          </span>
        </label>
        {info.note && <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2">{info.note}</p>}
        <label className="block text-sm font-medium text-gray-700">Model
          <input className={`${field} mt-1`} value={model} onChange={e => setModel(e.target.value)} list="llm-models"
            placeholder={data?.default_models[provider] || (models.length ? "pick an installed model" : "provider default")} />
          <datalist id="llm-models">{models.map(m => <option key={m} value={m} />)}</datalist>
          {models.length > 0 && <span className="text-xs text-gray-400 mt-1 block">{models.length} installed — click the field to pick one.</span>}
          {modelsErr && <span className="text-xs text-amber-700 mt-1 block break-words">Couldn't list models: {modelsErr}</span>}
        </label>
        {info.needsUrl && (
          <label className="block text-sm font-medium text-gray-700">Base URL
            <input className={`${field} mt-1`} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} onBlur={refreshModels} placeholder={info.urlHint} />
            <span className="text-xs text-gray-400 mt-1 block">The app runs in Docker: <code>localhost</code> is translated to your host machine automatically.</span>
          </label>
        )}
        {info.needsKey && (
          <label className="block text-sm font-medium text-gray-700">{info.keyLabel}
            <input type="password" autoComplete="off" className={`${field} mt-1`} value={apiKey}
              onChange={e => { setApiKey(e.target.value); setClearKey(false); }}
              placeholder={keySet ? "•••••••• saved (leave blank to keep)" : "not set"} />
            {keySet && <button type="button" className="text-xs text-red-600 mt-1" onClick={() => { setClearKey(true); setApiKey(""); }}>Remove saved key</button>}
            {clearKey && <span className="text-xs text-gray-500 mt-1 block">Saved key will be removed on save.</span>}
          </label>
        )}
        <div className="flex gap-2 pt-1">
          <button onClick={() => test.mutate()} disabled={test.isPending}
            className="px-4 py-2 text-sm rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            {test.isPending ? "Testing…" : "Test connection"}</button>
          <button onClick={() => save.mutate()} disabled={save.isPending}
            className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white disabled:opacity-50">
            {save.isPending ? "Saving…" : "Save"}</button>
        </div>
        {test.data && (test.data.ok
          ? <p className="text-sm text-green-700">Connected. Model replied: “{test.data.reply}”</p>
          : <p className="text-sm text-red-600 break-words">Failed: {test.data.error}</p>)}
        {test.isError && <p className="text-sm text-red-600">Test request failed.</p>}
        {save.isSuccess && <p className="text-sm text-green-700">Saved.</p>}
        {save.isError && <p className="text-sm text-red-600">Save failed.</p>}
      </div>
    </div>
  );
}

const card = "bg-white border border-gray-200 rounded-xl p-5 space-y-4";
const btn = "px-4 py-2 text-sm rounded-lg bg-blue-600 text-white disabled:opacity-50";
const errText = (e: unknown) => (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Request failed";

function useAppSettings() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["app-settings"], queryFn: getAppSettings });
  const save = useMutation({
    mutationFn: (body: AppSettingsInput) => saveAppSettings(body),
    onSuccess: d => { qc.setQueryData(["app-settings"], d); qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["auth-info"] }); },
  });
  return { data, save };
}

function SaveRow({ save }: { save: { isPending: boolean; isSuccess: boolean; isError: boolean; error: unknown } }) {
  return (
    <div className="flex items-center gap-3 pt-1">
      <button type="submit" className={btn} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</button>
      {save.isSuccess && <span className="text-sm text-green-700">Saved.</span>}
      {save.isError && <span className="text-sm text-red-600">{errText(save.error)}</span>}
    </div>
  );
}

function TextField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label className="block text-sm font-medium text-gray-700">{label}
      <input className={`${field} mt-1`} value={value} placeholder={placeholder} onChange={e => onChange(e.target.value)} />
    </label>
  );
}

function GeneralSection() {
  const { data, save } = useAppSettings();
  const [f, setF] = useState({ dry_run: true, scan_batch_size: 50, frontend_url: "", timezone: "", scan_retention_days: 0, auto_verify: false, auto_link_check: false });
  useEffect(() => { if (data) setF({ dry_run: data.dry_run, scan_batch_size: data.scan_batch_size, frontend_url: data.frontend_url, timezone: data.timezone ?? "", scan_retention_days: data.scan_retention_days ?? 0, auto_verify: !!data.auto_verify, auto_link_check: !!data.auto_link_check }); }, [data]);
  const zones = timezoneList();
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-gray-900">General</h2>
      <form className={card} onSubmit={e => { e.preventDefault(); save.mutate(f); }}>
        <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
          <input type="checkbox" checked={f.dry_run} onChange={e => setF({ ...f, dry_run: e.target.checked })} />
          Dry-run mode (scan and classify, never unsubscribe)
        </label>
        <p className="text-xs text-gray-400 -mt-2">When on, the server forces dry-run even if a scan request asks otherwise.</p>
        <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
          <input type="checkbox" checked={f.auto_verify} onChange={e => setF({ ...f, auto_verify: e.target.checked })} />
          Automatically verify senders that a scan flags (spam, or a name that doesn't match the domain)
        </label>
        <p className="text-xs text-gray-400 -mt-2">Looks up the sender's domain age and mail policies (public DNS and registry data) during scans. The result appears as a badge. Nothing from the email itself is sent.</p>
        <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
          <input type="checkbox" checked={f.auto_link_check} onChange={e => setF({ ...f, auto_link_check: e.target.checked })} />
          Check data broker links automatically every week
        </label>
        <p className="text-xs text-gray-400 -mt-2">Off by default. When on, this computer contacts the broker sites on your Privacy checklist once a week to see if their opt-out pages still work. You can always run it by hand from the Privacy page.</p>
        <label className="block text-sm font-medium text-gray-700">Scan batch size
          <input type="number" min={1} max={1000} className={`${field} mt-1`} value={f.scan_batch_size}
            onChange={e => setF({ ...f, scan_batch_size: Number(e.target.value) })} />
        </label>
        <TextField label="Frontend URL" value={f.frontend_url} onChange={v => setF({ ...f, frontend_url: v })} />
        <label className="block text-sm font-medium text-gray-700">Timezone
          <select className={`${field} mt-1`} value={f.timezone} onChange={e => setF({ ...f, timezone: e.target.value })}>
            <option value="">Browser default ({browserTimezone()})</option>
            {zones.map(z => <option key={z} value={z}>{z.replace(/_/g, " ")}</option>)}
          </select>
          <span className="text-xs text-gray-400 mt-1 block">Times shown in the app (scans, activity). Now: {formatTime(new Date().toISOString(), f.timezone)}</span>
        </label>
        <label className="block text-sm font-medium text-gray-700">Delete stored scan details after (days)
          <input type="number" min={0} max={3650} className={`${field} mt-1`} value={f.scan_retention_days} onChange={e => setF({ ...f, scan_retention_days: Number(e.target.value) })} />
          <span className="text-xs text-gray-400 mt-1 block">0 keeps everything. Otherwise old results are deleted after each scan. Mail still waiting for your decision is never deleted.</span>
        </label>
        <SaveRow save={save} />
      </form>
      <DangerZone />
    </div>
  );
}

function DangerZone() {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const wipe = useMutation({ mutationFn: deleteScanData, onSuccess: () => { setConfirming(false); qc.invalidateQueries(); } });
  return (
    <div className={`${card} border-red-200`}>
      <p className="text-sm font-medium text-gray-800">Delete all scan data</p>
      <p className="text-xs text-gray-500">Removes every stored email result and scan history. Your accounts, settings, safe senders and activity log are kept. You can scan again any time.</p>
      {!confirming ? <button type="button" onClick={() => setConfirming(true)} className="px-4 py-2 text-sm rounded-lg border border-red-300 text-red-700 hover:bg-red-50">Delete all scan data…</button> : (
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => wipe.mutate()} disabled={wipe.isPending} className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white disabled:opacity-50">{wipe.isPending ? "Deleting…" : "Yes, delete everything"}</button>
          <button type="button" onClick={() => setConfirming(false)} className="text-sm text-gray-500">Cancel</button>
        </div>)}
      {wipe.isSuccess && <p className="text-sm text-green-700">Deleted {wipe.data.emails} emails and {wipe.data.scans} scans.</p>}
      {wipe.isError && <p className="text-sm text-red-600">Couldn't delete.</p>}
    </div>
  );
}

function SecuritySection() {
  const out = useMutation({ mutationFn: logoutEverywhere, onSuccess: () => window.location.reload() });
  const [cur, setCur] = useState(""); const [next, setNext] = useState(""); const [again, setAgain] = useState("");
  const m = useMutation({ mutationFn: () => changePassword(cur, next), onSuccess: () => { setCur(""); setNext(""); setAgain(""); } });
  const mismatch = again !== "" && next !== again;
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-gray-900">Admin password</h2>
      <form className={card} onSubmit={e => { e.preventDefault(); m.mutate(); }}>
        <label className="block text-sm font-medium text-gray-700">Current password
          <input type="password" autoComplete="current-password" className={`${field} mt-1`} value={cur} onChange={e => setCur(e.target.value)} /></label>
        <label className="block text-sm font-medium text-gray-700">New password (8+ characters)
          <input type="password" autoComplete="new-password" className={`${field} mt-1`} value={next} onChange={e => setNext(e.target.value)} /></label>
        <label className="block text-sm font-medium text-gray-700">Repeat new password
          <input type="password" autoComplete="new-password" className={`${field} mt-1`} value={again} onChange={e => setAgain(e.target.value)} /></label>
        {mismatch && <p className="text-sm text-red-600">Passwords don't match.</p>}
        <p className="text-xs text-gray-400">Changing it signs out every other browser. The value in .env is ignored once you set one here.</p>
        <div className="flex items-center gap-3">
          <button type="submit" className={btn} disabled={!cur || next.length < 8 || next !== again || m.isPending}>{m.isPending ? "Changing…" : "Change password"}</button>
          {m.isSuccess && <span className="text-sm text-green-700">Password changed.</span>}
          {m.isError && <span className="text-sm text-red-600">{errText(m.error)}</span>}
        </div>
        <div className="pt-3 border-t border-gray-100 flex items-center gap-3">
          <button type="button" onClick={() => out.mutate()} disabled={out.isPending} className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50">Sign out of every browser</button>
          <span className="text-xs text-gray-400">Use this if a device was lost. All sessions end, including this one.</span>
        </div>
      </form>
    </div>
  );
}

export default function Settings() {
  return (
    <div className="max-w-xl space-y-10">
      <h1 className="text-xl font-semibold text-gray-900">Settings</h1>
      <LLMSection />
      <GeneralSection />
      <SecuritySection />
    </div>
  );
}
