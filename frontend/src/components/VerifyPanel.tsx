import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldQuestion } from "lucide-react";
import { verifySender } from "../lib/api";

const VERDICT: Record<string, { label: string; cls: string }> = {
  legitimate: { label: "Authentic sender", cls: "bg-green-100 text-green-800" },
  unclear: { label: "Unclear", cls: "bg-amber-100 text-amber-800" },
  suspicious: { label: "Suspicious", cls: "bg-red-100 text-red-700" },
};
export const VerdictChip = ({ verdict, title }: { verdict?: string | null; title?: string | null }) => {
  const v = verdict ? VERDICT[verdict] : null;
  return v ? <span title={title ?? undefined} className={`text-xs px-2 py-0.5 rounded-full font-medium ${v.cls}`}>{v.label}</span> : null;
};

/** Runs the technical sender checks for one stored email and shows the evidence. Only the domain and DNS/registry facts are used. */
export default function VerifyPanel({ recordId }: { recordId: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const run = useMutation({ mutationFn: (explain: boolean) => verifySender(recordId, explain),
    onSuccess: () => ["emails", "unsub-senders"].forEach(k => qc.invalidateQueries({ queryKey: [k] })) });
  const err = (run.error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail;
  const r = run.data;
  if (!open) return <button onClick={() => { setOpen(true); run.mutate(false); }} className="inline-flex items-center gap-1 text-xs px-2 py-1 border border-gray-200 rounded-md text-gray-600 hover:bg-gray-50" title="Check who really sent this: signature, domain age, mail policies"><ShieldQuestion size={12} /> Verify sender</button>;
  return (
    <div className="mt-3 w-full bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs space-y-2">
      <div className="flex items-center justify-between"><span className="font-medium text-gray-800">Sender check{r ? ` for ${r.domain}` : ""}</span><button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">Close</button></div>
      {run.isPending && <p className="text-gray-500">Checking the signature, domain age and mail policies…</p>}
      {err && <p className="text-red-600">{err}</p>}
      {r && (<>
        <div className="flex items-center gap-2"><VerdictChip verdict={r.verdict} /><span className="text-gray-500">score {r.score}</span></div>
        <ul className="space-y-1">{r.reasons.map((x, i) => <li key={i} className="flex gap-2"><span className={x.ok === true ? "text-green-600" : x.ok === false ? "text-red-600" : "text-gray-400"}>{x.ok === true ? "✓" : x.ok === false ? "✗" : "•"}</span><span className="text-gray-700">{x.text}</span></li>)}</ul>
        {r.history.length > 0 && <p className="text-gray-500">Similar senders in your mailbox: {r.history.slice(0, 4).map(h => `${h.domain} (${h.count}${h.dkim_domain ? ", signed" : ""})`).join(" · ")}</p>}
        {r.notes.map((n, i) => <p key={i} className="text-amber-700">{n}</p>)}
        <p className="text-gray-400">{r.caveat}</p>
        {r.explanation ? <p className="bg-white border border-gray-200 rounded p-2 text-gray-700"><span className="font-medium">Model's read (from these facts only):</span> {r.explanation}</p> : (
          <button onClick={() => run.mutate(true)} disabled={run.isPending} className="px-2.5 py-1 border border-blue-200 text-blue-700 rounded-md hover:bg-blue-50 disabled:opacity-50" title="Sends only the domain and the technical facts above to your chosen model, never the email">Ask the model to weigh the evidence</button>)}
        {r.explanation_error && <p className="text-red-600">The model couldn't answer: {r.explanation_error}</p>}
      </>)}
    </div>
  );
}
