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

export interface Account {
  id: string;
  username: string;
  display_name: string | null;
  status: AccountStatus;
  created_at: string;
}

export interface LoginResponse {
  token: string;
  account: Account;
}

export interface Persona {
  id: string;
  account_id: string;
  name: string;
  persona_md: string | null;
  timezone: string;
  status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
}

export type BridgeStatus = 'online' | 'offline' | 'revoked';

export interface Bridge {
  id: string;
  account_id: string;
  machine_id: string;
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
  takeover: boolean;
  reply_policy: 'disabled' | 'autoreply';
  pending_reply: boolean;
  status: 'active' | 'archived';
  last_seen_platform_msg_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  contact_id: string;
  external_id: string;
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
  contact_ids: string[];
  target_persona_id: string | null;
  provider_config_id: string;
  status: 'pending' | 'running' | 'done' | 'failed';
  progress: DistillJobProgress;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
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

// --- Personas ---

export function getPersonas() { return request<Persona[]>('/personas'); }
export function getPersona(id: string) { return request<Persona>(`/personas/${id}`); }
export function createPersona(data: { name: string; persona_md: string | null; timezone?: string }) {
  return request<Persona>('/personas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
export function updatePersona(
  id: string,
  data: { name?: string; persona_md?: string | null; timezone?: string; status?: 'active' | 'archived' },
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
    takeover?: boolean;
    reply_policy?: 'disabled' | 'autoreply';
    status?: 'active' | 'archived';
  },
) {
  return request<Contact>(`/contacts/${contactId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Distill ---

export function getDistillJobs() { return request<DistillJob[]>('/distill-jobs'); }
export function getDistillJob(jobId: string) {
  return request<DistillJob>(`/distill-jobs/${jobId}`);
}
export function createDistillJob(data: {
  contact_ids: string[]; target_persona_id?: string | null;
}) {
  return request<DistillJob>('/distill-jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
