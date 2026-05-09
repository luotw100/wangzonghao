const API_BASE = '/api';
const TOKEN_KEY = 'laborster-studio-token';

export class UnauthorizedError extends Error {
  detail: string;
  constructor(detail: string) {
    super(detail);
    this.detail = detail;
    this.name = 'UnauthorizedError';
  }
}

let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options: RequestInit = {}, timeout = 15000): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  try {
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers, signal: controller.signal });
    clearTimeout(timeoutId);
    if (res.status === 401) {
      let detail = 'HTTP 401';
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch { /* ignore */ }
      setToken(null);
      if (unauthorizedHandler) unauthorizedHandler();
      throw new UnauthorizedError(detail);
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    const text = await res.text();
    return text ? JSON.parse(text) : (null as T);
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('请求超时，请检查网络连接');
    }
    throw err;
  }
}

// --- Types ---

export type AccountStatus = 'active' | 'disabled';
export type AccountRole = 'admin' | 'user';

export interface Account {
  id: string;
  username: string;
  display_name: string | null;
  role: AccountRole;
  status: AccountStatus;
  created_at: string;
  last_login_at: string | null;
}

export interface LoginResponse {
  token: string;
  account: Account;
}

export interface ProviderConfig {
  id: string;
  owner_account_id: string;
  name: string;
  base_url: string;
  api_key_preview?: string;
  has_api_key?: boolean;
  default_model: string;
  scope: 'global';
  status: 'active' | 'disabled';
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface Persona {
  id: string;
  account_id: string;
  name: string;
  persona_md: string | null;
  status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
}

export type BridgeStatus = 'online' | 'offline' | 'revoked';

export interface Bridge {
  id: string;
  account_id: string;
  display_name: string;
  hostname: string;
  status: BridgeStatus;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Inbox {
  id: string;
  account_id: string;
  bridge_id: string | null;
  platform: string;
  display_name: string;
  default_persona_id: string | null;
  reply_provider_config_id: string | null;
  enabled: boolean;
  platform_self_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Contact {
  id: string;
  inbox_id: string;
  peer_platform_id: string;
  display_name: string;
  card_md: string | null;
  persona_id: string | null;
  reply_provider_config_id: string | null;
  autoreply_enabled: boolean;
  pending_reply: boolean;
  status: 'active' | 'archived';
  last_seen_platform_msg_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Archive {
  id: string;
  account_id: string;
  inbox_id: string;
  filename: string;
  self_wxid: string;
  message_count: number;
  contact_count: number;
  uploaded_at: string;
}

export interface Message {
  id: number;
  contact_id: string;
  archive_id: string | null;
  external_id: string;
  source: 'archive' | 'live';
  role: 'self' | 'counterpart';
  sender_name: string | null;
  content: string;
  timestamp: string;
  created_at: string;
}

export interface ConversationSummary {
  contact: Contact;
  inbox: Inbox;
  latest_message: Message | null;
  message_count: number;
}

export interface DistillJobProgress {
  contacts_total?: number;
  contacts_done?: number;
  windows_total?: number;
  windows_done?: number;
}

export interface DistillJob {
  id: string;
  account_id: string;
  source_inbox_id: string;
  target_persona_id: string;
  provider_config_id: string;
  status: 'pending' | 'running' | 'done' | 'failed';
  progress: DistillJobProgress;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AdminOverviewTotals {
  accounts: number;
  admins: number;
  users: number;
  bridges_online: number;
  bridges_offline: number;
  inboxes: number;
  personas: number;
  contacts: number;
  contacts_autoreply: number;
  messages: number;
  providers: number;
  outbound_pending: number;
}

export interface AdminOverviewAccount {
  account: Account;
  bridges_online: number;
  bridges_offline: number;
  bridges_revoked: number;
  inboxes: number;
  personas: number;
  contacts: number;
  contacts_autoreply: number;
  messages: number;
}

export interface AdminOverview {
  totals: AdminOverviewTotals;
  accounts: AdminOverviewAccount[];
}

// --- Auth ---

export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export function authLogout() {
  return request<{ status: string }>('/auth/logout', { method: 'POST' });
}

export function authMe() {
  return request<Account>('/auth/me');
}

export function changeOwnPassword(data: { current_password: string; new_password: string }) {
  return request<{ status: string }>('/auth/password', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Admin overview ---

export function getAdminOverview() {
  return request<AdminOverview>('/admin/overview');
}

// --- Account Admin ---

export function getAccounts() {
  return request<Account[]>('/accounts');
}

export function createAccount(data: {
  username: string; password: string; display_name: string | null; role: AccountRole;
}) {
  return request<Account>('/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateAccount(
  id: string,
  data: { display_name?: string | null; role?: AccountRole; status?: AccountStatus },
) {
  return request<Account>(`/accounts/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function resetAccountPassword(id: string, password: string) {
  return request<{ status: string; id: string }>(`/accounts/${id}/password`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
}

// --- Provider Configs ---

export function getProviderConfigs() {
  return request<ProviderConfig[]>('/provider-configs');
}

export function createProviderConfig(data: {
  name: string; base_url: string; api_key: string | null; default_model: string;
}) {
  return request<ProviderConfig>('/provider-configs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateProviderConfig(
  id: string,
  data: { name?: string; base_url?: string; api_key?: string; default_model?: string },
) {
  return request<ProviderConfig>(`/provider-configs/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteProviderConfig(id: string) {
  return request<void>(`/provider-configs/${id}`, { method: 'DELETE' });
}

// --- Personas ---

export function getPersonas() { return request<Persona[]>('/personas'); }
export function getPersona(id: string) { return request<Persona>(`/personas/${id}`); }
export function createPersona(data: { name: string; persona_md: string | null }) {
  return request<Persona>('/personas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
export function updatePersona(
  id: string,
  data: { name?: string; persona_md?: string | null; status?: 'active' | 'archived' },
) {
  return request<Persona>(`/personas/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
export function deletePersona(id: string) {
  return request<{ status: string; id: string }>(`/personas/${id}`, { method: 'DELETE' });
}

// --- Bridges (read-only + revoke; auto-provisioned by daemon handshake) ---

export function getBridges() { return request<Bridge[]>('/bridges'); }
export function deleteBridge(id: string) {
  return request<{ status: string; id: string }>(`/bridges/${id}`, { method: 'DELETE' });
}

// --- Inboxes (read + edit defaults; never created/deleted from UI) ---

export function getInboxes() { return request<Inbox[]>('/inboxes'); }
export function updateInbox(
  id: string,
  data: {
    display_name?: string;
    default_persona_id?: string;
    reply_provider_config_id?: string;
    clear_reply_provider?: boolean;
    enabled?: boolean;
  },
) {
  return request<Inbox>(`/inboxes/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Contacts ---

export function getConversations() {
  return request<ConversationSummary[]>('/conversations');
}
export function getContactMessages(contactId: string, limit = 200) {
  return request<Message[]>(`/contacts/${contactId}/messages?limit=${limit}`);
}
export function updateContact(
  contactId: string,
  data: {
    display_name?: string;
    card_md?: string | null;
    persona_id?: string;
    reply_provider_config_id?: string;
    clear_reply_provider?: boolean;
    autoreply_enabled?: boolean;
    status?: 'active' | 'archived';
  },
) {
  return request<Contact>(`/contacts/${contactId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Archives ---

export function getArchives() { return request<Archive[]>('/archives'); }
export async function uploadArchive(
  inboxId: string, selfWxid: string, file: File,
): Promise<Archive> {
  const form = new FormData();
  form.append('inbox_id', inboxId);
  form.append('self_wxid', selfWxid);
  form.append('file', file);
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(`${API_BASE}/archives`, { method: 'POST', headers, body: form });
  if (res.status === 401) {
    setToken(null);
    if (unauthorizedHandler) unauthorizedHandler();
    throw new UnauthorizedError('未登录');
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const body = await res.json(); if (body?.detail) detail = body.detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

// --- Distill ---

export function getDistillJobs() { return request<DistillJob[]>('/distill-jobs'); }
export function getDistillJob(jobId: string) {
  return request<DistillJob>(`/distill-jobs/${jobId}`);
}
export function createDistillJob(data: {
  source_inbox_id: string; target_persona_id: string; provider_config_id?: string | null;
}) {
  return request<DistillJob>('/distill-jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
