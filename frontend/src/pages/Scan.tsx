import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, RefreshCw } from "lucide-react";
import { getAccounts, getFolders, getScanRuns, getAppSettings, startScan } from "../lib/api";
import { duration, formatTime, useTimezone } from "../lib/time";

const STATUS_COLOR: Record<string, string> = { pending: "text-gray-400", running: "text-blue-600", complete: "text-green-600", failed: "text-red-500" };
const inputCls = "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm";
const detail = (e: unknown) => (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;

export default function Scan() {
  const qc = useQueryClient();
  const tz = useTimezone();
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: getAccounts });
  const { data: appSettings } = useQuery({ queryKey: ["app-settings"], queryFn: getAppSettings });
  const { data: runs = [], isFetching } = useQuery({ queryKey: ["scan-runs"], queryFn: getScanRuns, refetchInterval: 5000 });
  const [accountId, setAccountId] = useState("");
  const [folder, setFolder] = useState("INBOX");
  const [batch, setBatch] = useState<number | "">("");
  const labelFor = (id: number) => accounts.find(a => a.id === id)?.label ?? `Account ${id}`;

  const folders = useQuery({ queryKey: ["folders", accountId], queryFn: () => getFolders(Number(accountId)), enabled: !!accountId, retry: false, staleTime: 5 * 60_000 });
  useEffect(() => { setFolder("INBOX"); }, [accountId]);
  useEffect(() => { if (!accountId && accounts.length === 1) setAccountId(String(accounts[0].id)); }, [accounts, accountId]);
  useEffect(() => { if (batch === "" && appSettings) setBatch(appSettings.scan_batch_size); }, [appSettings, batch]);
  const folderList = folders.data ?? [];
  // servers disagree on casing (Outlook says "Inbox"); pick the real name once the list is known
  useEffect(() => { const real = folderList.find(f => f.toUpperCase() === "INBOX"); if (real && folder.toUpperCase() === "INBOX" && folder !== real) setFolder(real); }, [folderList, folder]);

  const scan = useMutation({
    mutationFn: () => startScan({ account_id: Number(accountId), folder, batch_size: Number(batch) || 50, dry_run: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scan-runs"] }),
  });
  const running = runs.some(r => r.status === "pending" || r.status === "running");

  return (
    <div className="max-w-4xl">
      <h2 className="text-2xl font-bold text-gray-800 mb-2">Scan</h2>
      <p className="text-sm text-gray-500 mb-6">A scan only reads mail and finds senders to review. It never unsubscribes. Do that from <Link to="/unsubscribe" className="underline">Unsubscribe</Link>.</p>
      <div className="bg-white border border-gray-200 rounded-xl p-5 mb-8">
        <h3 className="font-semibold text-gray-700 mb-4">Start a New Scan</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Account</label>
            <select className={inputCls} value={accountId} onChange={e => setAccountId(e.target.value)}>
              <option value="">Select account…</option>
              {accounts.map(a => <option key={a.id} value={a.id}>{a.label} ({a.email_address})</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1 flex items-center justify-between">Folder
              {accountId && <button type="button" onClick={() => folders.refetch()} className="text-gray-400 hover:text-blue-500" title="Reload folders"><RefreshCw size={12} className={folders.isFetching ? "animate-spin" : ""} /></button>}
            </label>
            {folderList.length > 0 ? (
              <select className={inputCls} value={folder} onChange={e => setFolder(e.target.value)}>
                {!folderList.includes(folder) && <option value={folder}>{folder}</option>}
                {folderList.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
            ) : (
              <input className={inputCls} value={folder} onChange={e => setFolder(e.target.value)} placeholder="INBOX" disabled={!accountId} />
            )}
            {accountId && folders.isFetching && <p className="text-xs text-gray-400 mt-1">Loading folders…</p>}
            {folders.isError && <p className="text-xs text-amber-700 mt-1 break-words">Couldn't list folders ({detail(folders.error) ?? "server error"}). You can type the name instead.</p>}
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">How many recent emails to look at</label>
            <input type="number" min={1} max={1000} className={inputCls} value={batch} onChange={e => setBatch(e.target.value === "" ? "" : Number(e.target.value))} />
          </div>
        </div>
        {/junk|spam|bulk/i.test(folder) && <p className="mt-3 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">This looks like a junk folder. Most of it is spam: the scan detects spam and leaves it alone (unsubscribing from spam only confirms your address is live). Only legitimate-looking senders are offered for unsubscribe.</p>}
        <div className="flex items-center gap-3 mt-4">
          <button onClick={() => scan.mutate()} disabled={!accountId || scan.isPending || running}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            <Play size={15} />{scan.isPending ? "Starting…" : running ? "A scan is running…" : "Start Scan"}
          </button>
          {scan.isError && <span className="text-sm text-red-600">{detail(scan.error) ?? "Couldn't start the scan."}</span>}
        </div>
      </div>

      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-700">Scan history</h3>
        <button onClick={() => qc.invalidateQueries({ queryKey: ["scan-runs"] })} className="text-gray-400 hover:text-blue-500" title="Refresh"><RefreshCw size={15} className={isFetching ? "animate-spin" : ""} /></button>
      </div>
      <div className="space-y-2">
        {runs.length === 0 && <p className="text-gray-400 text-sm">No scans yet.</p>}
        {runs.map(run => (
          <div key={run.id} className="bg-white border border-gray-200 rounded-xl px-5 py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <span className={`font-medium capitalize text-sm ${STATUS_COLOR[run.status] ?? ""}`}>{run.status}</span>
                <span className="text-xs text-gray-400 ml-3">{formatTime(run.started_at, tz)}</span>
                {run.completed_at && <span className="text-xs text-gray-400 ml-2">· took {duration(run.started_at, run.completed_at)}</span>}
                <p className="text-xs text-gray-500 mt-0.5">{labelFor(run.account_id)} · {run.folder}{run.batch_size ? ` · last ${run.batch_size}` : ""}</p>
              </div>
              <div className="text-xs text-gray-600 text-right">
                <div>Looked at <b>{run.emails_scanned}</b> · To review <b className="text-green-700">{run.emails_found}</b>{run.emails_spam > 0 && <> · Spam <b className="text-red-600">{run.emails_spam}</b></>}{run.emails_kept > 0 && <> · Kept <b>{run.emails_kept}</b></>}</div>
                <div className="text-gray-400">
                  {run.emails_known > 0 && <>already seen {run.emails_known} · </>}no unsubscribe link {run.emails_no_link}
                  {run.emails_failed > 0 && <span className="text-red-500"> · LLM failures {run.emails_failed}</span>}
                </div>
              </div>
            </div>
            {run.error && <p className="text-xs text-red-600 mt-2 break-words">{run.error}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
