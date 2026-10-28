import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getScanRuns, getEmailCounts, getUnsubSenders, getSettings } from "../lib/api";
import { formatTime, duration, useTimezone } from "../lib/time";
import { Mail, CheckCircle, Clock, AlertCircle } from "lucide-react";

export default function Dashboard() {
  const { data: runs } = useQuery({ queryKey: ["scan-runs"], queryFn: getScanRuns });
  const tz = useTimezone();
  const { data: counts } = useQuery({ queryKey: ["email-counts"], queryFn: getEmailCounts });
  const { data: queue } = useQuery({ queryKey: ["unsub-senders"], queryFn: getUnsubSenders });
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: getSettings });
  const latestRun = runs?.[0];
  const senderCount = queue?.senders.length ?? 0;
  const emailCount = queue?.senders.reduce((n, s) => n + s.email_count, 0) ?? 0;
  const stats = [
    { label: "Looked at (last scan)", value: latestRun?.emails_scanned ?? 0, icon: Mail, color: "text-blue-600" },
    { label: "Senders to review", value: senderCount, icon: Clock, color: "text-yellow-600" },
    { label: "Emails unsubscribed", value: counts?.unsubscribed ?? 0, icon: CheckCircle, color: "text-green-600" },
    { label: "Unsubscribe failed", value: counts?.failed ?? 0, icon: AlertCircle, color: "text-red-500" },
  ];
  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-800 mb-1">Dashboard</h2>
      <p className="text-gray-500 text-sm mb-6">
        LLM: <span className="font-medium">{settings?.llm_provider ?? "…"}</span>
        {" · "}Dry-run: <span className={`font-medium ${settings?.dry_run ? "text-yellow-600" : "text-green-600"}`}>
          {settings?.dry_run ? "ON (safe mode)" : "OFF (live)"}
        </span>
      </p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {stats.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-5">
            <Icon className={`${color} mb-2`} size={22} />
            <div className="text-2xl font-bold text-gray-800">{value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>
      {senderCount > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4 mb-6 flex items-start gap-3">
          <Clock className="text-yellow-600 mt-0.5" size={18} />
          <div>
            <p className="font-medium text-yellow-800">{senderCount} sender{senderCount === 1 ? "" : "s"} waiting for your decision ({emailCount} email{emailCount === 1 ? "" : "s"})</p>
            <p className="text-sm text-yellow-700 mt-0.5">Open <Link to="/unsubscribe" className="underline">Review</Link> to decide.</p>
          </div>
        </div>
      )}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h3 className="font-semibold text-gray-700 mb-3">Latest Scan</h3>
        {latestRun ? (
          <div className="text-sm space-y-1 text-gray-600">
            <div>Status: <span className="font-medium capitalize">{latestRun.status}</span></div>
            <div>Started: {formatTime(latestRun.started_at, tz)}{latestRun.completed_at ? ` · took ${duration(latestRun.started_at, latestRun.completed_at)}` : ""}</div>
            <div>{latestRun.folder}: looked at {latestRun.emails_scanned} · to review {latestRun.emails_found}{latestRun.emails_spam > 0 ? ` · spam ${latestRun.emails_spam}` : ""}{latestRun.emails_kept > 0 ? ` · kept ${latestRun.emails_kept}` : ""}</div>
            {latestRun.error && <div className="text-red-600 text-xs">{latestRun.error}</div>}
          </div>
        ) : <p className="text-sm text-gray-400">No scans yet — go to Scan to start one.</p>}
      </div>
    </div>
  );
}
