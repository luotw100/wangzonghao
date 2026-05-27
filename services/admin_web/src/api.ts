const BASE = '/api/admin';

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b?.detail) detail = b.detail; } catch { /* */ }
    throw new Error(detail);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : (null as T);
}

// ---------- Types ----------

export interface Account {
  id: string;
  username: string;
  display_name: string;
  status: 'active' | 'disabled';
  distill_provider_id: string;
  distill_provider_name: string;
  created_at: string;
  updated_at: string;
}

export interface Provider {
  id: string;
  name: string;
  base_url: string;
  model: string;
  api_key_masked: string;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  account_username: string;
  inbox_platform: string;
  inbox_display_name: string;
  kind: string;
  display_name: string;
  persona_name: string | null;
  provider_id: string;
  provider_name: string;
  reply_policy: string;
  takeover: boolean;
  status: string;
  created_at: string;
}

// ---------- Accounts ----------

export const getAccounts = () => req<Account[]>('/accounts');

export const createAccount = (body: { username: string; password: string; display_name: string }) =>
  req<Account>('/accounts', { method: 'POST', body: JSON.stringify(body) });

export const resetPassword = (accountId: string, password: string) =>
  req<null>(`/accounts/${accountId}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  });

export const setDistillProvider = (accountId: string, providerId: string) =>
  req<null>(`/accounts/${accountId}/distill-provider`, {
    method: 'PATCH',
    body: JSON.stringify({ provider_id: providerId }),
  });

// ---------- Providers ----------

export const getProviders = () => req<Provider[]>('/providers');
export const getAllowedBaseUrls = () => req<string[]>('/allowed-base-urls');

export const createProvider = (body: { name: string; base_url: string; api_key?: string; model: string }) =>
  req<Provider>('/providers', { method: 'POST', body: JSON.stringify(body) });

export const updateProvider = (id: string, body: { name?: string; base_url?: string; api_key?: string; model?: string }) =>
  req<Provider>(`/providers/${id}`, { method: 'PATCH', body: JSON.stringify(body) });

export const deleteProvider = (id: string) =>
  req<null>(`/providers/${id}`, { method: 'DELETE' });

// ---------- Conversations ----------

export const getConversations = (account?: string) => {
  const qs = account ? `?account=${encodeURIComponent(account)}` : '';
  return req<Conversation[]>(`/conversations${qs}`);
};

export const setConversationProvider = (convId: string, providerId: string) =>
  req<null>(`/conversations/${convId}/provider`, {
    method: 'PATCH',
    body: JSON.stringify({ provider_id: providerId }),
  });

// ---------- Hosted bridges (dogfood chat-only) ----------

export interface HostedBridge {
  account_id: string;
  username: string;
  display_name: string;
  status: 'stopped' | 'starting' | 'running' | 'auth_error' | 'crashed';
  machine_id: string | null;
  last_started_at: string | null;
  last_error: string;
}

export const getHostedBridges = () => req<HostedBridge[]>('/hosted-bridges');

export const startHostedBridge = (accountId: string) =>
  req<HostedBridge>(`/hosted-bridges/${accountId}/start`, { method: 'POST' });

export const stopHostedBridge = (accountId: string) =>
  req<HostedBridge>(`/hosted-bridges/${accountId}/stop`, { method: 'POST' });

// ---------- Audit: chats / llm logs / distill jobs / persona timeline ----------

export interface ChatConversation {
  id: string;
  account_id: string;
  account_username: string;
  inbox_id: string;
  inbox_display_name: string;
  inbox_platform: string;
  kind: string;
  peer_display: string;
  persona_id: string | null;
  persona_name: string | null;
  takeover: boolean;
  reply_policy: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  ts: string;
  direction: 'self' | 'peer';
  sender_display: string;
  msg_type: string;
  content: string;
  llm_log_id: number | null;
}

export interface LlmLogSummary {
  id: number;
  purpose: 'reply' | 'distill';
  created_at: string;
  model: string | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  is_error: boolean | null;
  account_username: string | null;
  inbox_display_name: string | null;
  persona_name: string | null;
  conversation_peer_display: string | null;
  conversation_id: string | null;
  distill_job_id: string | null;
  window_index: number | null;
  windows_total: number | null;
}

export interface LlmLogDetail extends LlmLogSummary {
  request_messages: Array<{ role: string; content: string }>;
  response_raw: string;
  persona_md_snapshot: string | null;
  card_md_snapshot: string | null;
  persona_md_after: string | null;
  card_md_after: string | null;
  outbound_message_id: number | null;
}

export interface DistillJobSummary {
  id: string;
  account_id: string;
  account_username: string;
  persona_id: string | null;
  persona_name: string | null;
  provider_name: string;
  status: string;
  conversation_count: number;
  progress: Record<string, number>;
  error_message: string;
  created_at: string;
}

export interface DistillFoldRow {
  log_id: number;
  conversation_id: string;
  conversation_peer_display: string;
  window_index: number | null;
  windows_total: number | null;
  latency_ms: number | null;
  is_error: boolean | null;
  persona_changed: boolean;
  card_changed: boolean;
  created_at: string;
}

export interface DistillJobDetail extends DistillJobSummary {
  folds: DistillFoldRow[];
}

export interface PersonaListItem {
  id: string;
  name: string;
  account_id: string;
  account_username: string;
}

export interface PersonaTimelineEntry {
  log_id: number;
  distill_job_id: string | null;
  conversation_id: string | null;
  conversation_peer_display: string | null;
  window_index: number | null;
  windows_total: number | null;
  persona_md_before: string | null;
  persona_md_after: string | null;
  created_at: string;
}

export const getChats = (accountId?: string) => {
  const qs = accountId ? `?account_id=${encodeURIComponent(accountId)}` : '';
  return req<ChatConversation[]>(`/chats${qs}`);
};

export const getChatMessages = (convId: string, opts: { limit?: number; before_id?: number } = {}) => {
  const params = new URLSearchParams();
  if (opts.limit) params.set('limit', String(opts.limit));
  if (opts.before_id) params.set('before_id', String(opts.before_id));
  const qs = params.toString() ? `?${params.toString()}` : '';
  return req<ChatMessage[]>(`/chats/${convId}/messages${qs}`);
};

export const getLlmLogs = (filters: {
  account_id?: string; persona_id?: string; conversation_id?: string; distill_job_id?: string;
  purpose?: string; is_error?: boolean; limit?: number; before_id?: number;
} = {}) => {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v));
  }
  const qs = params.toString() ? `?${params.toString()}` : '';
  return req<LlmLogSummary[]>(`/llm-logs${qs}`);
};

export const getLlmLog = (id: number) => req<LlmLogDetail>(`/llm-logs/${id}`);

export const getDistillJobs = (accountId?: string) => {
  const qs = accountId ? `?account_id=${encodeURIComponent(accountId)}` : '';
  return req<DistillJobSummary[]>(`/distill-jobs${qs}`);
};

export const getDistillJob = (id: string) => req<DistillJobDetail>(`/distill-jobs/${id}`);

export const getPersonas = () => req<PersonaListItem[]>('/personas');
export const getPersonaTimeline = (id: string) =>
  req<PersonaTimelineEntry[]>(`/personas/${id}/timeline`);
