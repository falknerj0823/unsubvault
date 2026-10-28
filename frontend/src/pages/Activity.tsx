import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { formatTime, useTimezone } from "../lib/time";
import { getAudit, getAuditTypes, AuditEvent } from "../lib/api";

const LABELS: Record<string, string> = {
  app_started: "App started", login: "Signed in", login_failed: "Failed sign-in", login_blocked: "Sign-in blocked (too many attempts)",
  logout: "Signed out", password_changed: "Admin password changed", password_change_failed: "Password change failed",
  settings_changed: "Settings changed", llm_config_changed: "LLM settings changed", llm_test: "LLM connection test",
  account_added: "Account added", account_removed: "Account removed", account_connected: "Account connected", account_reconnected: "Account reconnected",
  microsoft_signin_started: "Microsoft sign-in started", microsoft_signin_failed: "Microsoft sign-in failed",
  broker_status_changed: "Data broker status changed", broker_mailbox_checked: "Checked mailbox for broker emails", spam_moved_to_junk: "Spam moved to Junk",
  safe_sender_added: "Safe sender added", safe_sender_removed: "Safe sender removed", scan_data_deleted: "All scan data deleted", scan_data_purged: "Old scan data purged",
  scan_started: "Scan started", scan_completed: "Scan finished", scan_failed: "Scan failed",
  unsubscribe_attempt: "Unsubscribe request", bulk_unsubscribe_started: "Bulk unsubscribe started", bulk_unsubscribe_completed: "Bulk unsubscribe finished", unsubscribe_approved: "Unsubscribe approved", email_dismissed: "Email dismissed",
};

const isPrivateIp = (ip: string | null) => !ip || /^(10\.|127\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|fe80:)/.test(ip);
const summarize = (e: AuditEvent) => Object.entries(e.detail)
  .map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ");

export default function Activity() {
  const tz = useTimezone();
  const [type, setType] = useState(""); const [failuresOnly, setFailuresOnly] = useState(false);
  const { data: types = [] } = useQuery({ queryKey: ["audit-types"], queryFn: getAuditTypes });
  const q = useInfiniteQuery({
    queryKey: ["audit", type, failuresOnly],
    queryFn: ({ pageParam }) => getAudit({ event_type: type || undefined, failures_only: failuresOnly || undefined, before_id: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: last => last.has_more ? last.events[last.events.length - 1].id : undefined,
  });
  const events = q.data?.pages.flatMap(p => p.events) ?? [];
  return (
    <div className="max-w-5xl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="text-2xl font-bold text-gray-800">Activity</h2>
        <div className="flex flex-wrap items-center gap-3">
          <select value={type} onChange={e => setType(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white">
            <option value="">All events</option>
            {types.map(t => <option key={t} value={t}>{LABELS[t] ?? t}</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-sm text-gray-600"><input type="checkbox" checked={failuresOnly} onChange={e => setFailuresOnly(e.target.checked)} />Failures only</label>
          <button onClick={() => q.refetch()} className="p-2 text-gray-500 hover:text-gray-800" title="Refresh"><RefreshCw size={16} className={q.isFetching ? "animate-spin" : ""} /></button>
        </div>
      </div>
      <p className="text-xs text-gray-400 mb-4">Append-only record of sign-ins, setting changes, account changes and scans. Passwords, keys, tokens and email content are never stored here. Events are kept for 180 days. IP addresses are shown only when they are not local.</p>
      <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-gray-500 border-b border-gray-100">
            <th className="px-4 py-2 font-medium">When</th><th className="px-4 py-2 font-medium">Event</th><th className="px-4 py-2 font-medium">Details</th><th className="px-4 py-2 font-medium">IP</th>
          </tr></thead>
          <tbody>
            {events.map(e => (
              <tr key={e.id} className="border-b border-gray-50 align-top">
                <td className="px-4 py-2 whitespace-nowrap text-gray-500">{formatTime(e.at, tz)}</td>
                <td className="px-4 py-2 whitespace-nowrap">
                  <span className={`inline-block w-2 h-2 rounded-full mr-2 ${e.success ? "bg-green-500" : "bg-red-500"}`} />
                  <span className={e.success ? "text-gray-800" : "text-red-700 font-medium"}>{LABELS[e.type] ?? e.type}</span>
                  {e.actor !== "admin" && <span className="ml-2 text-xs text-gray-400">({e.actor})</span>}
                </td>
                <td className="px-4 py-2 text-gray-600 break-words max-w-md">{summarize(e)}</td>
                <td className="px-4 py-2 text-gray-400 whitespace-nowrap">{isPrivateIp(e.ip) ? "—" : e.ip}</td>
              </tr>
            ))}
            {events.length === 0 && !q.isLoading && <tr><td colSpan={4} className="px-4 py-6 text-center text-gray-400">No events{type || failuresOnly ? " match these filters" : " yet"}.</td></tr>}
          </tbody>
        </table>
      </div>
      {q.hasNextPage && <button onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}
        className="mt-4 px-4 py-2 text-sm border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-50">{q.isFetchingNextPage ? "Loading…" : "Load more"}</button>}
    </div>
  );
}
