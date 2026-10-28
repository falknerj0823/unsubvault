import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ShieldCheck } from "lucide-react";
import { getUnsubSenders, startBulkUnsub, getUnsubJob, keepSenders, getSafeSenders, undoSafeSender, markDone, UnsubSender } from "../lib/api";
import VerifyPanel, { VerdictChip } from "../components/VerifyPanel";

const METHOD: Record<string, { label: string; cls: string; auto: boolean }> = {
  one_click: { label: "One-click", cls: "bg-green-100 text-green-700", auto: true },
  web_link: { label: "Web link (unverified)", cls: "bg-yellow-100 text-yellow-700", auto: true },
  mailto: { label: "Email only (manual)", cls: "bg-gray-100 text-gray-600", auto: false },
  none: { label: "No usable link", cls: "bg-gray-100 text-gray-500", auto: false },
};
const key = (s: { account_id: number; sender_email: string }) => `${s.account_id}|${s.sender_email}`;
const safeHref = (t: string | null) => (t && /^(https:\/\/|mailto:)/i.test(t) ? t : undefined);
const refreshAll = (qc: ReturnType<typeof useQueryClient>) => ["unsub-senders", "emails", "email-counts", "safe-senders"].forEach(k => qc.invalidateQueries({ queryKey: [k] }));

export default function Unsubscribe() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["unsub-senders"], queryFn: getUnsubSenders });
  const safe = useQuery({ queryKey: ["safe-senders"], queryFn: getSafeSenders });
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [sendForReal, setSendForReal] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [showSafe, setShowSafe] = useState(false);

  const serverDry = data?.dry_run ?? true;
  const senders = data?.senders ?? [];
  const visible = useMemo(() => senders.filter(s => !filter || `${s.sender_name} ${s.sender_email} ${s.sample_subject} ${s.reason ?? ""}`.toLowerCase().includes(filter.toLowerCase())), [senders, filter]);
  const selected = senders.filter(s => sel.has(key(s)));
  const mixedSelected = selected.filter(s => s.mixed_count > 0);
  const dryRun = serverDry || !sendForReal;

  const job = useQuery({ queryKey: ["unsub-job", jobId], queryFn: () => getUnsubJob(jobId!), enabled: jobId !== null,
    refetchInterval: q => (q.state.data && ["complete", "failed"].includes(q.state.data.status) ? false : 1500) });
  const finished = !!job.data && ["complete", "failed"].includes(job.data.status);
  const running = !!job.data && !finished;
  useEffect(() => { if (finished) refreshAll(qc); }, [finished, qc]);

  const start = useMutation({
    mutationFn: () => startBulkUnsub(selected.map(s => ({ account_id: s.account_id, sender_email: s.sender_email })), dryRun),
    onSuccess: j => { setJobId(j.id); setConfirming(false); setSel(new Set()); window.scrollTo({ top: 0, behavior: "smooth" }); },
  });
  const makeSafe = useMutation({
    mutationFn: (list: UnsubSender[]) => keepSenders(list.map(s => ({ account_id: s.account_id, sender_email: s.sender_email }))),
    onSuccess: (r, list) => { setNotice(`Marked ${list.length === 1 ? (list[0].sender_name || list[0].sender_email) : `${list.length} senders`} as safe. They won't be offered again. Undo in "Safe senders" below.`); setSel(new Set()); refreshAll(qc); },
  });
  const done = useMutation({
    mutationFn: (list: UnsubSender[]) => markDone(list.map(s => ({ account_id: s.account_id, sender_email: s.sender_email }))),
    onSuccess: (_r, list) => { setNotice(`Recorded ${list.length === 1 ? (list[0].sender_name || list[0].sender_email) : `${list.length} senders`} as unsubscribed by you. Keep an eye out for whether the mail stops.`); setSel(new Set()); refreshAll(qc); },
  });
  const undo = useMutation({ mutationFn: undoSafeSender, onSuccess: () => refreshAll(qc) });

  const err = (start.error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;
  const toggle = (s: UnsubSender) => setSel(prev => { const n = new Set(prev); n.has(key(s)) ? n.delete(key(s)) : n.add(key(s)); return n; });
  const toggleOpen = (s: UnsubSender) => setOpen(prev => { const n = new Set(prev); n.has(key(s)) ? n.delete(key(s)) : n.add(key(s)); return n; });
  const selectWhere = (fn: (s: UnsubSender) => boolean) => setSel(new Set(visible.filter(s => METHOD[s.method].auto && fn(s)).map(key)));

  return (
    <div className="max-w-5xl pb-24">
      <h2 className="text-2xl font-bold text-gray-800 mb-2">Review &amp; unsubscribe</h2>
      <p className="text-sm text-gray-500 mb-4">Senders found by scans, waiting for your decision. One request per sender covers all of their emails. Nothing is sent until you confirm. If something is wrongly here, mark it a <b>safe sender</b>.</p>

      <div className={`mb-4 text-sm rounded-lg px-3 py-2 border ${serverDry ? "bg-yellow-50 border-yellow-200 text-yellow-800" : "bg-blue-50 border-blue-200 text-blue-800"}`}>
        {serverDry ? <>Dry-run mode is <b>on</b>: runs only simulate and send nothing. Turn it off in <Link to="/settings" className="underline">Settings → General</Link> to send real requests.</>
                   : <>Dry-run mode is <b>off</b>. You can choose to send real requests when you confirm.</>}
      </div>
      {notice && <div className="mb-4 text-sm rounded-lg px-3 py-2 border bg-green-50 border-green-200 text-green-800 flex justify-between gap-3"><span>{notice}</span><button className="underline shrink-0" onClick={() => setNotice("")}>Dismiss</button></div>}

      {job.data && (
        <div className="mb-4 bg-white border border-gray-200 rounded-xl p-4 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-gray-800">{running ? "Working…" : job.data.status === "failed" ? "Stopped" : "Finished"}{job.data.dry_run ? " (dry run: nothing was sent)" : ""}</span>
            <span className="text-gray-500">{job.data.done} / {job.data.total} senders</span>
          </div>
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden"><div className="h-full bg-blue-500 transition-all" style={{ width: `${job.data.total ? (100 * job.data.done) / job.data.total : 0}%` }} /></div>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-600">
            {job.data.simulated > 0 && <span>Would send: <b>{job.data.simulated}</b></span>}
            {job.data.confirmed > 0 && <span className="text-green-700">Confirmed (one-click): <b>{job.data.confirmed}</b></span>}
            {job.data.unverified > 0 && <span className="text-yellow-700">Request sent, unverified: <b>{job.data.unverified}</b></span>}
            {job.data.manual > 0 && <span>Needs manual action: <b>{job.data.manual}</b></span>}
            {job.data.failed > 0 && <span className="text-red-600">Failed: <b>{job.data.failed}</b></span>}
          </div>
          {finished && job.data.unverified > 0 && <p className="text-xs text-gray-500">"Unverified" means the sender's page answered OK, but plain links often only open a confirmation page. Keep an eye on whether mail from them stops.</p>}
          {job.data.error && <p className="text-xs text-red-600">{job.data.error}</p>}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter senders…" className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm" />
        <button onClick={() => selectWhere(s => s.method === "one_click" && s.mixed_count === 0)} className="text-xs px-2.5 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50" title="One-click senders that don't also send you account mail">Select recommended</button>
        <button onClick={() => selectWhere(() => true)} className="text-xs px-2.5 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50">Select all automatic</button>
        <button onClick={() => setSel(new Set())} className="text-xs px-2.5 py-1.5 text-gray-500 hover:text-gray-800">Clear</button>
        <span className="text-xs text-gray-400 ml-auto">{senders.length} sender{senders.length === 1 ? "" : "s"}</span>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-gray-500 border-b border-gray-100">
            <th className="px-3 py-2 w-8"></th><th className="px-3 py-2 font-medium">Sender</th><th className="px-3 py-2 font-medium">Emails</th><th className="px-3 py-2 font-medium">How</th><th className="px-3 py-2 w-40"></th>
          </tr></thead>
          <tbody>
            {visible.map(s => {
              const m = METHOD[s.method]; const href = safeHref(s.target); const isOpen = open.has(key(s));
              return (
                <Fragment key={key(s)}>
                  <tr className={`border-b border-gray-50 align-top ${sel.has(key(s)) ? "bg-blue-50/40" : ""} ${m.auto && !running ? "cursor-pointer hover:bg-gray-50" : ""}`} onClick={() => m.auto && !running && toggle(s)}>
                    <td className="px-3 py-2" onClick={e => e.stopPropagation()}><input type="checkbox" disabled={!m.auto || running} checked={sel.has(key(s))} onChange={() => toggle(s)} /></td>
                    <td className="px-3 py-2 min-w-0">
                      <p className="font-medium text-gray-800 truncate max-w-md">{s.sender_name || s.sender_email}</p>
                      <p className="text-xs text-gray-500 truncate max-w-md">{s.sender_email}</p>
                      {s.reason && <p className="text-xs text-gray-400 italic mt-0.5 max-w-md line-clamp-2">{s.reason}</p>}
                      <div className="flex flex-wrap gap-1 mt-1">
                        {s.brand_mismatch && !s.verify_verdict && <span className="text-xs bg-amber-50 border border-amber-200 text-amber-800 px-2 py-0.5 rounded-full" title="The name suggests a brand that is not in the sending domain. Real companies often send through other domains, so verify it.">Name doesn't match domain: verify</span>}
                        <VerdictChip verdict={s.verify_verdict} title={s.verify_summary} />
                      </div>
                      {s.mixed_count > 0 && <span className="inline-block mt-1 text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full" title="Receipts, account or personal mail from this company was found. Unsubscribing could silence it.">Also sends you account mail</span>}
                    </td>
                    <td className="px-3 py-2 text-gray-700 whitespace-nowrap">
                      <button className="flex items-center gap-1 text-gray-600 hover:text-gray-900" onClick={e => { e.stopPropagation(); toggleOpen(s); }}>{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{s.email_count}</button>
                    </td>
                    <td className="px-3 py-2"><span className={`text-xs px-2 py-0.5 rounded-full font-medium ${m.cls}`}>{m.label}</span>
                      {!m.auto && href && <a href={href} onClick={e => e.stopPropagation()} target="_blank" rel="noopener noreferrer" className="block text-xs text-blue-600 underline mt-1">Open it yourself</a>}
                      {s.last_result && <p className="text-xs text-gray-400 mt-1">last: {s.last_result.replace(/_/g, " ")}</p>}</td>
                    <td className="px-3 py-2 text-right" onClick={e => e.stopPropagation()}>
                      <button disabled={done.isPending} onClick={() => done.mutate([s])} className="inline-flex items-center gap-1 whitespace-nowrap text-xs px-2 py-1 mb-1 border border-gray-200 rounded-md text-gray-600 hover:bg-gray-50" title="You unsubscribed yourself (opened their page or emailed them). Record it and remove it from this list.">Done by me</button><br />
                      <button disabled={makeSafe.isPending} onClick={() => makeSafe.mutate([s])} className="inline-flex items-center gap-1 whitespace-nowrap text-xs px-2 py-1 border border-gray-200 rounded-md text-gray-600 hover:bg-gray-50" title="Never mark this sender as spam or offer it for unsubscribe"><ShieldCheck size={12} /> Safe sender</button>
                    </td>
                  </tr>
                  {isOpen && <tr className="border-b border-gray-50 bg-gray-50/60"><td></td><td colSpan={4} className="px-3 py-2 text-xs text-gray-600">
                    <ul className="list-disc ml-4 space-y-0.5">{s.samples.map((x, i) => <li key={i}>{x.subject || "(no subject)"}</li>)}</ul>
                    {s.email_count > s.samples.length && <p className="text-gray-400 mt-1">…and {s.email_count - s.samples.length} more</p>}
                    <div className="mt-2"><VerifyPanel recordId={s.record_id} /></div>
                  </td></tr>}
                </Fragment>);
            })}
            {!isLoading && visible.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">{senders.length ? "No senders match the filter." : "Nothing waiting. Run a scan first."}</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="mt-6">
        <button onClick={() => setShowSafe(v => !v)} className="flex items-center gap-1 text-sm font-medium text-gray-700">{showSafe ? <ChevronDown size={15} /> : <ChevronRight size={15} />} Safe senders and "not spam" decisions ({safe.data?.length ?? 0})</button>
        {showSafe && (
          <div className="mt-2 bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
            {(safe.data ?? []).length === 0 && <p className="px-4 py-3 text-sm text-gray-400">None yet. Mark a sender safe from the list above or from the Emails page.</p>}
            {(safe.data ?? []).map(r => (
              <div key={r.id} className="px-4 py-2 flex items-center justify-between text-sm">
                <span className="text-gray-700"><span className="text-xs bg-gray-100 text-gray-600 rounded px-1.5 py-0.5 mr-2">{r.decision === "not_spam" ? "not spam" : "safe"}</span>{r.sender_name ? `${r.sender_name} · ` : ""}<span className="text-gray-500">{r.sender_email}</span></span>
                <button onClick={() => undo.mutate(r.id)} disabled={undo.isPending} className="text-xs text-blue-600 underline">Remove</button>
              </div>))}
          </div>)}
      </div>

      {confirming && (
        <div className="fixed inset-0 z-30 bg-black/40 flex items-center justify-center p-4" onClick={() => setConfirming(false)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-5 space-y-3" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
            <p className="text-base text-gray-900 font-semibold">{dryRun ? "Run a dry run" : "Send unsubscribe requests"} for {selected.length} sender{selected.length === 1 ? "" : "s"} ({selected.reduce((n, s) => n + s.email_count, 0)} emails)?</p>
            <p className="text-sm text-gray-600">{selected.filter(s => s.method === "one_click").length} one-click, {selected.filter(s => s.method === "web_link").length} plain web links. {dryRun ? "Nothing will be sent; you'll see what would happen." : "This contacts each sender's unsubscribe link from your computer and can't be undone."}</p>
            {mixedSelected.length > 0 && <p className="text-xs bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2">{mixedSelected.length} of these also send you account mail ({mixedSelected.map(s => s.sender_name || s.sender_email).join(", ")}). Unsubscribing may stop important notices from them. Deselect any you need.</p>}
            {!serverDry && <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={sendForReal} onChange={e => setSendForReal(e.target.checked)} /> Actually send the requests (leave unchecked for a dry run)</label>}
            <div className="flex items-center gap-3 pt-1">
              <button onClick={() => start.mutate()} disabled={start.isPending} className={`px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-50 ${dryRun ? "bg-blue-600" : "bg-red-600"}`}>{start.isPending ? "Starting…" : dryRun ? "Run dry run" : "Send requests"}</button>
              <button onClick={() => setConfirming(false)} className="text-sm text-gray-500">Cancel</button>
              {err && <span className="text-sm text-red-600">{err}</span>}
            </div>
          </div>
        </div>
      )}

      {selected.length > 0 && !confirming && !running && (
        <div className="fixed bottom-0 left-56 right-0 bg-white border-t border-gray-200 shadow-lg px-8 py-3 flex items-center gap-3 z-10">
          <span className="text-sm text-gray-700 font-medium">{selected.length} selected ({selected.reduce((n, s) => n + s.email_count, 0)} emails)</span>
          <div className="flex-1" />
          <button onClick={() => done.mutate(selected)} disabled={done.isPending} className="px-3 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm hover:bg-gray-50" title="You unsubscribed these yourself">Done by me</button>
          <button onClick={() => makeSafe.mutate(selected)} disabled={makeSafe.isPending} className="flex items-center gap-1 px-3 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm hover:bg-gray-50"><ShieldCheck size={14} /> Safe senders</button>
          <button onClick={() => setConfirming(true)} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium">Unsubscribe {selected.length}…</button>
        </div>
      )}
    </div>
  );
}
