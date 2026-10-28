import axios from "axios";
const api = axios.create({ baseURL: "/api" });

export interface Account { id: number; label: string; provider_type: string; email_address: string; }
export interface ScanRun { id: number; account_id: number; status: string; folder: string; batch_size: number | null; dry_run: boolean; emails_scanned: number; emails_found: number; emails_known: number; emails_no_link: number; emails_spam: number; emails_kept: number; emails_failed: number; error: string | null; started_at: string; completed_at: string | null; }
export interface EmailRecord { id: number; subject: string; sender_name: string; sender_email: string; action: string; confidence: number | null; category?: string | null; classification_reason: string | null; unsubscribe_url: string | null; account_id: number; brand_mismatch?: boolean; verify_verdict?: string | null; verify_summary?: string | null; unsubscribe_result?: string | null; unsubscribe_error?: string | null; }
export interface AppSettings { llm_provider: string; dry_run: boolean; scan_batch_size: number; }

export const getAccounts = () => api.get<Account[]>("/accounts/").then(r => r.data);
export const deleteAccount = (id: number) => api.delete(`/accounts/${id}`).then(r => r.data);
export const addImapAccount = (body: { label: string; host: string; port: number; username: string; password: string }) => api.post("/accounts/imap", body).then(r => r.data);
export const getScanRuns = () => api.get<ScanRun[]>("/scan/runs").then(r => r.data);
export const getFolders = (accountId: number) => api.get<{ folders: string[] }>(`/accounts/${accountId}/folders`).then(r => r.data.folders);
export const startScan = (body: { account_id: number; folder: string; batch_size: number; dry_run: boolean }) => api.post("/scan/start", body).then(r => r.data);
export const getEmails = (params: { action?: string; category?: string }) => api.get<EmailRecord[]>("/emails/", { params }).then(r => r.data);
export const getSettings = () => api.get<AppSettings>("/settings/").then(r => r.data);

export const login = (password: string) => api.post("/session/login", { password }).then(r => r.data);
export const logout = () => api.post("/session/logout").then(r => r.data);
export const getSession = () => api.get("/session/me").then(() => true).catch(() => false);

export interface LLMProfile { model: string; base_url: string; api_key_set: boolean; }
export interface LLMConfig { active: string; profiles: Record<string, LLMProfile>; providers: string[]; default_models: Record<string, string>; }
export interface LLMConfigInput { provider: string; model: string; base_url: string; api_key?: string; }
export const getLLM = () => api.get<LLMConfig>("/settings/llm").then(r => r.data);
export const saveLLM = (body: LLMConfigInput) => api.put<LLMConfig>("/settings/llm", body).then(r => r.data);
export const testLLM = (body: LLMConfigInput) => api.post<{ ok: boolean; reply?: string; error?: string }>("/settings/llm/test", body).then(r => r.data);

export interface AppSettingsData {
  dry_run: boolean; scan_batch_size: number; frontend_url: string; timezone: string; scan_retention_days: number; auto_verify: boolean; auto_link_check: boolean;
  microsoft_client_id: string; microsoft_client_secret_set: boolean; microsoft_tenant: string;
  google_client_id: string; google_client_secret_set: boolean;
}
export type AppSettingsInput = Partial<Omit<AppSettingsData, "microsoft_client_secret_set" | "google_client_secret_set">> & { microsoft_client_secret?: string; google_client_secret?: string };
export const getAppSettings = () => api.get<AppSettingsData>("/settings/app").then(r => r.data);
export const saveAppSettings = (body: AppSettingsInput) => api.put<AppSettingsData>("/settings/app", body).then(r => r.data);
export const changePassword = (current_password: string, new_password: string) => api.post("/session/change-password", { current_password, new_password }).then(r => r.data);
export const listLLMModels = (body: LLMConfigInput) => api.post<{ ok: boolean; models: string[]; error?: string }>("/settings/llm/models", body).then(r => r.data);

export const getAuthInfo = () => api.get<{ redirect_uri: string; configured: boolean }>("/auth/microsoft/redirect-uri").then(r => r.data);

export interface AuditEvent { id: number; at: string; type: string; success: boolean; actor: string; ip: string | null; detail: Record<string, unknown>; }
export const getAudit = (params: { event_type?: string; failures_only?: boolean; before_id?: number }) =>
  api.get<{ has_more: boolean; events: AuditEvent[] }>("/audit/", { params: { limit: 50, ...params } }).then(r => r.data);
export const getAuditTypes = () => api.get<string[]>("/audit/types").then(r => r.data);

export interface UnsubSender { account_id: number; sender_email: string; sender_name: string; email_count: number; confidence: number; category: string; reason: string | null; samples: { subject: string | null; received_at: string | null }[]; mixed_count: number; brand_mismatch: boolean; verify_verdict: string | null; verify_summary: string | null; record_id: number; sample_subject: string; method: "one_click" | "web_link" | "mailto" | "none"; target: string | null; last_result: string | null; }
export interface UnsubJob { id: number; status: string; dry_run: boolean; total: number; done: number; confirmed: number; unverified: number; manual: number; failed: number; simulated: number; error: string | null; }
export const getUnsubSenders = () => api.get<{ dry_run: boolean; senders: UnsubSender[] }>("/unsubscribe/senders").then(r => r.data);
export const startBulkUnsub = (senders: { account_id: number; sender_email: string }[], dry_run: boolean) => api.post<UnsubJob>("/unsubscribe/bulk", { senders, dry_run }).then(r => r.data);
export const getUnsubJob = (id: number) => api.get<UnsubJob>(`/unsubscribe/jobs/${id}`).then(r => r.data);

export interface EmailCounts { pending: number; unsubscribed: number; failed: number; kept: number; spam: number; all: number; }
export const getEmailCounts = () => api.get<EmailCounts>("/emails/counts").then(r => r.data);

export interface SafeSender { id: number; decision: string; account_id: number; sender_email: string; sender_name: string | null; created_at: string; }
export const keepSenders = (senders: { account_id: number; sender_email: string }[]) => api.post<{ senders: number; emails: number }>("/unsubscribe/keep", { senders }).then(r => r.data);
export const getSafeSenders = () => api.get<SafeSender[]>("/unsubscribe/keep").then(r => r.data);
export const undoSafeSender = (id: number) => api.delete<{ restored: number }>(`/unsubscribe/keep/${id}`).then(r => r.data);
export const deleteScanData = () => api.delete<{ emails: number; scans: number; unsubscribe_runs: number }>("/settings/data/scan").then(r => r.data);

export interface SpamCandidates { dry_run: boolean; count: number; more: number; items: { id: number; account_id: number; folder: string; sender_name: string | null; sender_email: string; subject: string | null }[]; }
export const getSpamCandidates = () => api.get<SpamCandidates>("/spam/candidates").then(r => r.data);
export const moveSpam = (ids: number[]) => api.post<{ dry_run: boolean; found: number; moved: number; not_found: number; junk_folder: string | null }>("/spam/move", { ids }).then(r => r.data);

export interface Broker { id: string; name: string; category: string; method: string; url: string; notes: string; recheck_months: number; search_domain: string | null; link_state: string; link_note: string | null; link_checked_at: string | null; link_moved_to: string | null; status: string; requested_at: string | null; confirmed_at: string | null; recheck_due: boolean; }
export interface BrokerMail { folder: string; from: string; subject: string; date: string; verified: boolean; }
export const getBrokers = () => api.get<{ links_checked_at: string; links_live: boolean; links_running: boolean; brokers: Broker[] }>("/privacy/brokers").then(r => r.data);
export const setBrokerStatus = (id: string, status: string) => api.put(`/privacy/brokers/${encodeURIComponent(id)}`, { status }).then(r => r.data);
export const checkBrokerMail = (account_id: number, days: number) => api.post<{ days: number; messages: number; by_broker: Record<string, BrokerMail[]> }>("/privacy/check-mailbox", { account_id, days }).then(r => r.data);

export const checkBrokerLinks = () => api.post("/privacy/links/check").then(r => r.data);
export interface PrivacyProfile { full_name: string; city: string; state: string; also_known_as: string[]; }
export const getPrivacyProfile = () => api.get<PrivacyProfile>("/privacy/profile").then(r => r.data);
export const savePrivacyProfile = (p: PrivacyProfile) => api.put<PrivacyProfile>("/privacy/profile", p).then(r => r.data);
export const deletePrivacyProfile = () => api.delete("/privacy/profile").then(r => r.data);
export interface RegistryItem { id: string; name: string; website: string | null; website_https: boolean; email: string | null; optout_text: string | null; date_added: string | null; search_domain: string | null; is_new: boolean; is_changed: boolean; is_removed: boolean; status: string; }
export interface RegistryList { synced: boolean; last_sync: { at: string; total: number; new: number; changed: number; removed: number; baseline: boolean } | null; total: number; has_more: boolean; items: RegistryItem[]; }
export const getRegistry = (params: { q?: string; filter?: string; offset?: number }) => api.get<RegistryList>("/privacy/registry", { params: { limit: 50, ...params } }).then(r => r.data);
export const syncRegistry = () => api.post<{ total: number; new: number; changed: number; removed: number; baseline: boolean }>("/privacy/registry/sync").then(r => r.data);

export const markNotSpam = (id: number) => api.post<{ emails: number }>(`/emails/${id}/not-spam`).then(r => r.data);
export const markDone = (senders: { account_id: number; sender_email: string }[]) => api.post<{ emails: number }>("/unsubscribe/mark-done", { senders }).then(r => r.data);
export interface VerifyResult { verdict: string; score: number; summary: string; reasons: { ok: boolean | null; text: string }[]; domain: string;
  facts: { registered: string | null; age_days: number | null; spf: { present: boolean; policy: string | null }; dmarc: { present: boolean; policy: string | null }; mx: string[] };
  history: { domain: string; dkim_domain: string | null; count: number; newest: string; oldest: string }[]; notes: string[]; caveat: string; explanation?: string; explanation_error?: string; }
export const verifySender = (id: number, explain = false) => api.post<VerifyResult>(`/emails/${id}/verify`, null, { params: { explain } }).then(r => r.data);
export const logoutEverywhere = () => api.post("/session/logout-all").then(r => r.data);
