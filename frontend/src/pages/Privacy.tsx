import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, Search, ShieldAlert, ShieldCheck } from "lucide-react";
import { Broker, BrokerMail, PrivacyProfile, RegistryItem, checkBrokerLinks, checkBrokerMail, deletePrivacyProfile, getAccounts, getBrokers, getPrivacyProfile,
  getRegistry, savePrivacyProfile, setBrokerStatus, syncRegistry } from "../lib/api";
import { formatTime, useTimezone } from "../lib/time";

const SECTIONS: { key: string; title: string; blurb: string }[] = [
  { key: "california", title: "California residents: start here", blurb: "One request to every data broker registered in California." },
  { key: "people_search", title: "People-search sites", blurb: "They publish your name, address, phone and relatives, and they tend to re-list people, so re-check every few months." },
  { key: "marketing_data", title: "Marketing data brokers", blurb: "They sell the lists behind targeted mail, calls and ads." },
  { key: "mail_calls", title: "Junk mail and calls", blurb: "Official opt-outs for prescreened offers, catalogs and telemarketing." },
  { key: "tools", title: "Check where your email leaked", blurb: "Not a removal, but it shows which breaches expose your address, the likeliest source of spam." },
];
const STATUS = [["not_started", "Not started"], ["requested", "Requested"], ["confirmed", "Done (confirmed)"], ["relisted", "Came back"]] as const;
const STATUS_CLS: Record<string, string> = { not_started: "bg-gray-100 text-gray-600", requested: "bg-yellow-100 text-yellow-700", confirmed: "bg-green-100 text-green-700", relisted: "bg-red-100 text-red-600" };
const LINK_CHIP: Record<string, { label: string; cls: string }> = {
  ok: { label: "link ok", cls: "text-green-700" }, moved: { label: "link moved", cls: "text-amber-700" },
  blocked: { label: "can't be auto-checked", cls: "text-gray-400" }, broken: { label: "link broken", cls: "text-red-600" },
};
const safeUrl = (u: string | null | undefined) => (u && /^https:\/\//i.test(u) ? u : undefined);
const input = "border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-300";

/** A web-search link restricted to the broker's own site. Built in your browser; opens in a new tab. */
function searchLink(profile: PrivacyProfile | undefined, domain: string | null, engine: string): string | undefined {
  if (!profile?.full_name || !domain) return undefined;
  const q = `"${profile.full_name}" ${profile.city} ${profile.state} site:${domain}`.replace(/\s+/g, " ").trim();
  return engine === "ddg" ? `https://duckduckgo.com/?q=${encodeURIComponent(q)}` : `https://www.google.com/search?q=${encodeURIComponent(q)}`;
}

function StatusSelect({ id, status }: { id: string; status: string }) {
  const qc = useQueryClient();
  const set = useMutation({ mutationFn: (s: string) => setBrokerStatus(id, s), onSuccess: () => ["brokers", "registry"].forEach(k => qc.invalidateQueries({ queryKey: [k] })) });
  return (
    <select value={status} onChange={e => set.mutate(e.target.value)} disabled={set.isPending} className={`text-xs rounded-full px-2.5 py-1 border-0 font-medium ${STATUS_CLS[status]}`}>
      {STATUS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

function SearchBtn({ href }: { href?: string }) {
  if (!href) return null;
  return <a href={href} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs px-2.5 py-1 border border-blue-200 text-blue-700 rounded-md hover:bg-blue-50" title="Search this broker's site for you (opens a search in a new tab)"><Search size={12} /> Search for me</a>;
}

function MailList({ mail, tz }: { mail?: BrokerMail[]; tz: string }) {
  if (!mail || mail.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1">
      {mail.map((m, i) => (
        <li key={i} className="text-xs flex items-start gap-2">
          {m.verified ? <ShieldCheck size={14} className="text-green-600 shrink-0 mt-0.5" /> : <ShieldAlert size={14} className="text-red-500 shrink-0 mt-0.5" />}
          <span className="text-gray-700">{m.subject || "(no subject)"} <span className="text-gray-400">· {formatTime(m.date, tz, "short")} · {m.folder}</span>
            <span className={m.verified ? "text-green-700" : "text-red-600"}> · {m.verified ? "sender verified by your mail provider" : "NOT verified: could be fake"}</span></span>
        </li>))}
    </ul>
  );
}

function Row({ b, mail, tz, profile, engine }: { b: Broker; mail?: BrokerMail[]; tz: string; profile?: PrivacyProfile; engine: string }) {
  const [open, setOpen] = useState(false);
  const chip = LINK_CHIP[b.link_state] ?? LINK_CHIP.ok;
  return (
    <div className="px-4 py-3 border-b border-gray-100 last:border-0">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[14rem]">
          <p className="text-sm font-medium text-gray-800">{b.name}</p>
          <p className="text-xs text-gray-400">
            {b.method} · <span className={chip.cls} title={b.link_note ?? undefined}>{chip.label}</span>
            {b.requested_at && <> · requested {formatTime(b.requested_at, tz, "short")}</>}
            {b.confirmed_at && <> · done {formatTime(b.confirmed_at, tz, "short")}</>}
          </p>
          {b.link_moved_to && <p className="text-xs text-amber-700">Now redirects to {b.link_moved_to}</p>}
        </div>
        {b.recheck_due && <span className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full">re-check due</span>}
        <SearchBtn href={searchLink(profile, b.search_domain, engine)} />
        <StatusSelect id={b.id} status={b.status} />
        {safeUrl(b.url) && <a href={b.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs px-2.5 py-1 border border-gray-200 rounded-md text-gray-700 hover:bg-gray-50"><ExternalLink size={12} /> Open</a>}
        <button onClick={() => setOpen(v => !v)} className="text-xs text-gray-500 underline">{open ? "Hide" : "How"}</button>
      </div>
      {open && <p className="mt-2 text-xs text-gray-600 max-w-2xl">{b.notes}</p>}
      <MailList mail={mail} tz={tz} />
    </div>
  );
}

function ProfileCard({ onEngine, engine }: { onEngine: (e: string) => void; engine: string }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["privacy-profile"], queryFn: getPrivacyProfile });
  const [f, setF] = useState<PrivacyProfile>({ full_name: "", city: "", state: "", also_known_as: [] });
  const [open, setOpen] = useState(false);
  useEffect(() => { if (data) setF(data); }, [data]);
  const save = useMutation({ mutationFn: () => savePrivacyProfile(f), onSuccess: d => qc.setQueryData(["privacy-profile"], d) });
  const wipe = useMutation({ mutationFn: deletePrivacyProfile, onSuccess: () => { setF({ full_name: "", city: "", state: "", also_known_as: [] }); qc.invalidateQueries({ queryKey: ["privacy-profile"] }); } });
  const err = (save.error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;
  const has = !!data?.full_name;
  return (
    <div className="mb-6 bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-gray-800">Find my listing {has && <span className="text-green-700 text-xs ml-1">· profile saved</span>}</p>
          <p className="text-xs text-gray-500">Save your name and area once to get a "Search for me" button on each broker. It opens a web search limited to that broker's site, in your browser. Your details are stored encrypted in your own database and are never sent to the brokers by this app.</p>
        </div>
        <button onClick={() => setOpen(v => !v)} className="text-sm text-blue-600 underline shrink-0 ml-3">{open ? "Close" : has ? "Edit" : "Set up"}</button>
      </div>
      {open && (
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-6 gap-3">
            <input className={`${input} col-span-6 sm:col-span-3`} placeholder="Full name" value={f.full_name} onChange={e => setF({ ...f, full_name: e.target.value })} />
            <input className={`${input} col-span-4 sm:col-span-2`} placeholder="City" value={f.city} onChange={e => setF({ ...f, city: e.target.value })} />
            <input className={`${input} col-span-2 sm:col-span-1`} placeholder="State (CA)" maxLength={2} value={f.state} onChange={e => setF({ ...f, state: e.target.value })} />
          </div>
          <input className={input} placeholder="Other names you've used, comma separated (optional)" value={f.also_known_as.join(", ")} onChange={e => setF({ ...f, also_known_as: e.target.value.split(",").map(x => x.trim()).filter(Boolean) })} />
          <div className="flex flex-wrap items-center gap-3">
            <button onClick={() => save.mutate()} disabled={save.isPending} className="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50">{save.isPending ? "Saving…" : "Save profile"}</button>
            {has && <button onClick={() => wipe.mutate()} className="text-sm text-red-600 underline">Delete my profile</button>}
            <label className="text-xs text-gray-500 ml-auto">Search with <select value={engine} onChange={e => onEngine(e.target.value)} className="border border-gray-200 rounded px-1.5 py-0.5"><option value="google">Google</option><option value="ddg">DuckDuckGo</option></select></label>
            {save.isSuccess && <span className="text-xs text-green-700">Saved.</span>}{err && <span className="text-xs text-red-600">{err}</span>}
          </div>
          <p className="text-xs text-gray-400">Clicking a search sends your name and area to the search engine you pick, from your browser, as when you search for yourself.</p>
        </div>)}
    </div>
  );
}

function Checklist({ profile, engine, tz }: { profile?: PrivacyProfile; engine: string; tz: string }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["brokers"], queryFn: getBrokers, refetchInterval: q => (q.state.data?.links_running ? 3000 : false) });
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: getAccounts });
  const [accountId, setAccountId] = useState(""); const [days, setDays] = useState(45);
  const check = useMutation({ mutationFn: () => checkBrokerMail(Number(accountId || accounts[0]?.id), days) });
  const links = useMutation({ mutationFn: checkBrokerLinks, onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["brokers"] }), 1500) });
  const err = (check.error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;
  const brokers = data?.brokers ?? [];
  const handled = brokers.filter(b => b.status === "confirmed" || b.status === "requested").length;
  const broken = brokers.filter(b => b.link_state === "broken" || b.link_state === "moved").length;
  return (<>
    <div className="mb-6 bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-center justify-between text-sm mb-2"><span className="font-medium text-gray-800">Progress</span><span className="text-gray-500">{handled} of {brokers.length} requested or done</span></div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden"><div className="h-full bg-green-500" style={{ width: `${brokers.length ? (100 * handled) / brokers.length : 0}%` }} /></div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-gray-500">
        <span>Links {data?.links_live ? `checked ${formatTime(data.links_checked_at, tz, "short")}` : "not checked yet"}{broken > 0 && <span className="text-amber-700"> · {broken} need attention</span>}. Checks run when you press the button (automatic weekly checks are optional in Settings).</span>
        <button onClick={() => links.mutate()} disabled={links.isPending || data?.links_running} className="flex items-center gap-1 px-2.5 py-1 border border-gray-200 rounded-md text-gray-700 hover:bg-gray-50 disabled:opacity-50"><RefreshCw size={12} className={data?.links_running ? "animate-spin" : ""} /> {data?.links_running ? "Checking…" : "Check links now"}</button>
      </div>
    </div>
    <div className="mb-6 bg-white border border-gray-200 rounded-xl p-4 space-y-3">
      <div>
        <p className="text-sm font-medium text-gray-800">Look for confirmation emails</p>
        <p className="text-xs text-gray-500">Many removals only finish after you click a link in an email from the broker. This looks in your Inbox and Junk (read-only, headers only) for recent mail from these brokers, and shows whether your mail provider verified the sender, because fake "confirm your removal" emails are a common scam. It never opens or shows links: open the email yourself and only click links on the broker's own website.</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {accounts.length > 1 && <select className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm" value={accountId} onChange={e => setAccountId(e.target.value)}><option value="">Account…</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.email_address}</option>)}</select>}
        <select className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm" value={days} onChange={e => setDays(Number(e.target.value))}><option value={30}>Last 30 days</option><option value={45}>Last 45 days</option><option value={90}>Last 90 days</option></select>
        <button onClick={() => check.mutate()} disabled={check.isPending || accounts.length === 0 || (accounts.length > 1 && !accountId)} className="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50">{check.isPending ? "Checking…" : "Check my mailbox"}</button>
        {check.data && <span className="text-xs text-gray-500">Found {check.data.messages} message{check.data.messages === 1 ? "" : "s"} from {Object.keys(check.data.by_broker).length} broker{Object.keys(check.data.by_broker).length === 1 ? "" : "s"}.</span>}
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
    </div>
    {SECTIONS.map(sec => {
      const rows = brokers.filter(b => b.category === sec.key);
      if (rows.length === 0) return null;
      return (
        <section key={sec.key} className="mb-6">
          <h3 className="text-base font-semibold text-gray-800">{sec.title}</h3>
          <p className="text-xs text-gray-500 mb-2">{sec.blurb}</p>
          <div className="bg-white border border-gray-200 rounded-xl">{rows.map(b => <Row key={b.id} b={b} tz={tz} profile={profile} engine={engine} mail={check.data?.by_broker[b.id]} />)}</div>
        </section>);
    })}
  </>);
}

function RegistryRow({ r, profile, engine }: { r: RegistryItem; profile?: PrivacyProfile; engine: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="px-4 py-3 border-b border-gray-100 last:border-0">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[14rem]">
          <p className="text-sm font-medium text-gray-800">{r.name}
            {r.is_new && <span className="ml-2 text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">new</span>}
            {r.is_changed && <span className="ml-2 text-xs bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded-full">changed</span>}
            {r.is_removed && <span className="ml-2 text-xs bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded-full">no longer registered</span>}</p>
          <p className="text-xs text-gray-400">{r.website || "no website listed"}{r.email ? ` · ${r.email}` : ""}</p>
        </div>
        <SearchBtn href={searchLink(profile, r.search_domain, engine)} />
        <StatusSelect id={r.id} status={r.status} />
        {r.website_https && <a href={r.website!} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs px-2.5 py-1 border border-gray-200 rounded-md text-gray-700 hover:bg-gray-50"><ExternalLink size={12} /> Website</a>}
        <button onClick={() => setOpen(v => !v)} className="text-xs text-gray-500 underline">{open ? "Hide" : "Opt-out info"}</button>
      </div>
      {open && <p className="mt-2 text-xs text-gray-600 max-w-3xl whitespace-pre-wrap break-words">{r.optout_text || "The broker did not provide opt-out instructions in the registry."}
        <span className="block mt-1 text-gray-400">This text was written by the broker. Treat any link in it with care.</span></p>}
    </div>
  );
}

function RegistryTab({ profile, engine, tz }: { profile?: PrivacyProfile; engine: string; tz: string }) {
  const qc = useQueryClient();
  const [q, setQ] = useState(""); const [filter, setFilter] = useState("all"); const [offset, setOffset] = useState(0);
  const { data } = useQuery({ queryKey: ["registry", q, filter, offset], queryFn: () => getRegistry({ q, filter, offset }) });
  const sync = useMutation({ mutationFn: syncRegistry, onSuccess: () => { setOffset(0); qc.invalidateQueries({ queryKey: ["registry"] }); } });
  const err = (sync.error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;
  const ls = data?.last_sync;
  return (<>
    <div className="mb-4 bg-white border border-gray-200 rounded-xl p-4 space-y-2">
      <p className="text-sm font-medium text-gray-800">California's official data broker registry</p>
      <p className="text-xs text-gray-500">Every data broker registered in California, published by the state. Sync to see which brokers are new, which changed their details, and which dropped off. You can track any of them here the same way as the checklist.</p>
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => sync.mutate()} disabled={sync.isPending} className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50"><RefreshCw size={14} className={sync.isPending ? "animate-spin" : ""} /> {sync.isPending ? "Syncing…" : ls ? "Sync again" : "Sync registry"}</button>
        {ls && <span className="text-xs text-gray-500">Last synced {formatTime(ls.at, tz, "short")} · {ls.total} brokers{ls.baseline ? " (first sync: everything is the baseline)" : ` · ${ls.new} new, ${ls.changed} changed, ${ls.removed} removed`}</span>}
        {sync.data && <span className="text-xs text-green-700">Synced {sync.data.total} brokers.</span>}
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
    </div>
    {data?.synced && (<>
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <input className={`${input} max-w-xs`} placeholder="Search by name or website…" value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} />
        <select className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm" value={filter} onChange={e => { setFilter(e.target.value); setOffset(0); }}>
          <option value="all">All registered</option><option value="new">New since last sync</option><option value="changed">Changed since last sync</option><option value="removed">No longer registered</option><option value="tracked">Ones I'm tracking</option>
        </select>
        <span className="text-xs text-gray-400 ml-auto">{data.total} shown</span>
      </div>
      <div className="bg-white border border-gray-200 rounded-xl">
        {data.items.map(r => <RegistryRow key={r.id} r={r} profile={profile} engine={engine} />)}
        {data.items.length === 0 && <p className="px-4 py-6 text-sm text-gray-400 text-center">Nothing matches.</p>}
      </div>
      <div className="flex gap-3 mt-3">
        {offset > 0 && <button onClick={() => setOffset(Math.max(0, offset - 50))} className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg">Previous</button>}
        {data.has_more && <button onClick={() => setOffset(offset + 50)} className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg">Next 50</button>}
      </div>
    </>)}
  </>);
}

export default function Privacy() {
  const tz = useTimezone();
  const { data: profile } = useQuery({ queryKey: ["privacy-profile"], queryFn: getPrivacyProfile });
  const [engine, setEngine] = useState("google");
  const [tab, setTab] = useState<"checklist" | "registry">("checklist");
  return (
    <div className="max-w-4xl">
      <h2 className="text-2xl font-bold text-gray-800 mb-2">Privacy cleanup</h2>
      <p className="text-sm text-gray-600 mb-1">Get your details removed from data brokers. Honest expectations: this mostly cuts targeted scams, junk mail and calls. The casino and pharma spam in your Junk folder usually comes from breached and resold lists, so it helps only a little.</p>
      <p className="text-xs text-gray-400 mb-4">Tracking stores only which brokers you've handled. Opt-out links come from a hand-checked list and California's public registry; sites change often, so verify before you rely on one.</p>
      <ProfileCard engine={engine} onEngine={setEngine} />
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {([["checklist", "Checklist"], ["registry", "All registered brokers"]] as const).map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-4 py-2 text-sm font-medium ${tab === k ? "border-b-2 border-blue-600 text-blue-700" : "text-gray-500 hover:text-gray-700"}`}>{l}</button>))}
      </div>
      {tab === "checklist" ? <Checklist profile={profile} engine={engine} tz={tz} /> : <RegistryTab profile={profile} engine={engine} tz={tz} />}
    </div>
  );
}
