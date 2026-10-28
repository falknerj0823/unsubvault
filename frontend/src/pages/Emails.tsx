import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getEmails, getEmailCounts, keepSenders, getSpamCandidates, moveSpam, markNotSpam } from "../lib/api";
import VerifyPanel, { VerdictChip } from "../components/VerifyPanel";
import { ShieldCheck, ExternalLink } from "lucide-react";
import type { EmailRecord } from "../lib/api";

const TABS = [{key:"unsubscribe_pending",label:"Needs review",count:"pending"},{key:"unsubscribed",label:"Unsubscribed",count:"unsubscribed"},{key:"unsubscribe_failed",label:"Failed",count:"failed"},{key:"none",label:"Kept",count:"kept"},{key:"spam",label:"Spam",count:"spam"},{key:"",label:"All",count:"all"}] as const;
const PAGE = 30;
const BADGE: Record<string,string> = { spam:"bg-red-50 text-red-600", kept:"bg-green-50 text-green-700", none:"bg-gray-100 text-gray-600", unsubscribed:"bg-green-100 text-green-700", unsubscribe_pending:"bg-yellow-100 text-yellow-700", unsubscribe_failed:"bg-red-100 text-red-600" };

function SpamCleanup() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["spam-candidates"], queryFn: getSpamCandidates });
  const [confirming, setConfirming] = useState(false);
  const move = useMutation({
    mutationFn: () => moveSpam(data!.items.map(i => i.id)),
    onSuccess: () => { setConfirming(false); ["spam-candidates", "emails", "email-counts"].forEach(k => qc.invalidateQueries({ queryKey: [k] })); },
  });
  const err = (move.error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;
  if (!data) return null;
  return (
    <div className="mb-4 bg-white border border-gray-200 rounded-xl p-4 space-y-2">
      <p className="text-sm font-medium text-gray-800">Clean up spam in your mailbox</p>
      {data.count === 0 ? (
        <p className="text-xs text-gray-500">No spam is sitting in your normal folders. Spam found in Junk is already where it belongs. Moving spam to Junk (never deleting) is how your mail provider learns to catch it.</p>
      ) : (<>
        <p className="text-xs text-gray-500">{data.count} spam message{data.count === 1 ? " is" : "s are"} in a normal folder (not Junk). Moving them to Junk trains your provider's filter and is reversible; nothing is deleted. Spam can't be unsubscribed from.
          {data.more > 0 && ` Showing the first ${data.items.length}; run it again for the rest.`}</p>
        <ul className="text-xs text-gray-600 list-disc ml-5">{data.items.slice(0, 4).map(i => <li key={i.id} className="truncate">{i.subject || i.sender_email} <span className="text-gray-400">({i.folder})</span></li>)}{data.items.length > 4 && <li className="text-gray-400">…and {data.items.length - 4} more</li>}</ul>
        {data.dry_run && <p className="text-xs text-yellow-800 bg-yellow-50 border border-yellow-200 rounded-lg px-2 py-1">Dry-run mode is on: this only checks that the messages are there and moves nothing. Turn it off in Settings → General to really move them.</p>}
        {!confirming ? (
          <button onClick={() => setConfirming(true)} className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg">{data.dry_run ? "Check what would move…" : `Move ${data.items.length} to Junk…`}</button>
        ) : (
          <div className="flex items-center gap-3">
            <button onClick={() => move.mutate()} disabled={move.isPending} className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg disabled:opacity-50">{move.isPending ? "Working…" : data.dry_run ? "Run the check" : "Yes, move to Junk"}</button>
            <button onClick={() => setConfirming(false)} className="text-sm text-gray-500">Cancel</button>
          </div>)}
        {err && <p className="text-xs text-red-600">{err}</p>}
      </>)}
      {move.data && <p className="text-xs text-green-700">{move.data.dry_run ? `Dry run: ${move.data.found} message${move.data.found === 1 ? "" : "s"} found and would move to "${move.data.junk_folder}"` : `Moved ${move.data.moved} to "${move.data.junk_folder}"`}{move.data.not_found > 0 ? `; ${move.data.not_found} no longer in the folder.` : "."}</p>}
    </div>
  );
}

export default function Emails() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<string>("unsubscribe_pending");
  const [shown, setShown] = useState(PAGE);
  const { data: counts } = useQuery({ queryKey: ["email-counts"], queryFn: getEmailCounts });
  const [search, setSearch] = useState("");
  const { data: emails = [] } = useQuery({ queryKey: ["emails", tab], queryFn: () => getEmails(tab === "spam" ? { category: "spam" } : tab === "none" ? { action: "none", category: "!spam" } : tab ? { action: tab } : {}) });
  const notSpam = useMutation({
    mutationFn: (e: EmailRecord) => markNotSpam(e.id),
    onSuccess: () => { ["emails", "email-counts", "unsub-senders", "safe-senders", "spam-candidates"].forEach(k => qc.invalidateQueries({ queryKey: [k] })); },
  });
  const safe = useMutation({
    mutationFn: (e: EmailRecord) => keepSenders([{ account_id: e.account_id, sender_email: e.sender_email }]),
    onSuccess: () => { ["emails", "email-counts", "unsub-senders", "safe-senders"].forEach(k => qc.invalidateQueries({ queryKey: [k] })); },
  });
  const visible = search ? emails.filter((e: EmailRecord) => e.subject?.toLowerCase().includes(search.toLowerCase()) || e.sender_email?.toLowerCase().includes(search.toLowerCase())) : emails;
  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-800 mb-1">Emails</h2>
      <p className="text-xs text-gray-500 mb-4">What scans found. Decide per sender on the <Link to="/unsubscribe" className="underline">Review &amp; unsubscribe</Link> page. Wrong label? Use <b>Safe sender</b>.</p>
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {TABS.map(t => (
          <button key={t.key} onClick={() => { setTab(t.key); setShown(PAGE); }}
            className={`px-4 py-2 text-sm font-medium transition-colors ${tab===t.key?"border-b-2 border-blue-600 text-blue-700":"text-gray-500 hover:text-gray-700"}`}>
            {t.label}{counts && <span className="ml-1.5 text-xs text-gray-400">{counts[t.count]}</span>}
          </button>
        ))}
      </div>
      {tab === "spam" && <SpamCleanup />}
      <input placeholder="Search sender or subject…" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-blue-300"
        value={search} onChange={e => setSearch(e.target.value)} />
      <div className="space-y-2">
        {visible.length === 0 && <p className="text-gray-400 text-sm">No emails found.</p>}
        {visible.slice(0, shown).map((email: EmailRecord) => (
          <div key={email.id} className="bg-white border border-gray-200 rounded-xl px-5 py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-800 truncate">{email.subject || (email.sender_email.startsWith("@") ? "Receipt or personal mail (details not stored)" : "(no subject)")}</p>
                <p className="text-xs text-gray-500 mt-0.5">{email.sender_name ? `${email.sender_name} <${email.sender_email}>` : email.sender_email}</p>
                {email.classification_reason && <p className="text-xs text-gray-400 mt-1 italic">"{email.classification_reason}"</p>}
                {(email.brand_mismatch && !email.verify_verdict) && <p className="text-xs text-amber-700 mt-1">Name doesn't match the sending domain: verify this sender.</p>}
                {email.verify_verdict && <div className="mt-1"><VerdictChip verdict={email.verify_verdict} title={email.verify_summary} /></div>}
                {email.unsubscribe_result && <p className="text-xs text-gray-500 mt-1">Unsubscribe: {email.unsubscribe_result.replace(/_/g," ")}{email.unsubscribe_error ? ` — ${email.unsubscribe_error}` : ""}</p>}
              </div>
              <div className="flex flex-col items-end gap-2 shrink-0">
                <span className={`text-xs px-2 py-0.5 rounded-full capitalize font-medium ${BADGE[email.category === "spam" ? "spam" : email.category === "kept" ? "kept" : email.action]??"bg-gray-100 text-gray-600"}`}>{email.category === "spam" ? "spam: don't unsubscribe" : email.category === "kept" ? "safe sender" : email.category === "transactional" ? "receipt / notice" : email.category === "personal" ? "personal" : email.action.replace(/_/g," ")}</span>
                {email.confidence && !email.sender_email.startsWith("@") && <span className="text-xs text-gray-400">{Math.round(email.confidence*100)}% confidence</span>}
                <div className="flex gap-1.5">
                  {email.category === "spam" && !email.sender_email.startsWith("@") && (
                    <button onClick={() => notSpam.mutate(email)} disabled={notSpam.isPending} title="The model got this wrong. Treat the sender as ordinary marketing: it moves to the Review list."
                      className="flex items-center gap-1 text-xs px-2 py-1 border border-gray-200 text-gray-600 rounded-md hover:bg-gray-50">Not spam</button>
                  )}
                  {!email.sender_email.startsWith("@") && email.category !== "kept" && email.action !== "unsubscribed" && (
                    <button onClick={() => safe.mutate(email)} disabled={safe.isPending} title="Never mark this sender as spam or offer it for unsubscribe"
                      className="flex items-center gap-1 text-xs px-2 py-1 border border-gray-200 text-gray-600 rounded-md hover:bg-gray-50">
                      <ShieldCheck size={12} /> Safe sender
                    </button>
                  )}
                  {email.category !== "spam" && email.unsubscribe_url && /^(https:\/\/|mailto:)/i.test(email.unsubscribe_url) && (
                    <a href={email.unsubscribe_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-xs px-2 py-1 border border-gray-200 text-gray-600 rounded-md hover:bg-gray-50">
                      <ExternalLink size={12} /> Link
                    </a>
                  )}
                </div>
              </div>
            </div>
            {!email.sender_email.startsWith("@") && <div className="mt-2"><VerifyPanel recordId={email.id} /></div>}
          </div>
        ))}
      </div>
      {visible.length > shown && <button onClick={() => setShown(n => n + PAGE)} className="mt-4 px-4 py-2 text-sm border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50">Show more ({visible.length - shown} left)</button>}
    </div>
  );
}
