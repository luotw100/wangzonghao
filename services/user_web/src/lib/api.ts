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

export interface PersonaSummary {
  id: string;
  account_id: string;
  name: string;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface Persona extends PersonaSummary {
  persona_md: string;
}

export type BridgeStatus = 'online' | 'offline';

export interface Bridge {
  id: string;
  account_id: string;
  machine_id: string;
  status: BridgeStatus;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface Inbox {
  id: string;
  account_id: string;
  bridge_id: string | null;
  platform: string;
  display_name: string;
  platform_self_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderBrief {
  name: string;
}

export type ConversationKind = 'dm' | 'group' | 'unknown';

export interface ConversationMember {
  peer_platform_id: string;
  display_name: string;
  updated_at: string;
}

export interface ConversationSummary {
  id: string;
  inbox_id: string;
  platform_conversation_id: string;
  kind: ConversationKind;
  display_name: string;
  persona_id: string | null;
  provider: ProviderBrief;
  takeover: boolean;
  reply_policy: 'disabled' | 'autoreply';
  status: 'active' | 'archived';
  last_reply_round_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation extends ConversationSummary {
  card_md: string;
  members: ConversationMember[];
}

export interface Message {
  id: number;
  conversation_id: string;
  client_id: string;
  sender_id: string | null;
  msg_type: string;
  content: string;
  timestamp: string;
  created_at: string;
  from_self: boolean;
}

export interface ConversationListItem {
  conversation: ConversationSummary;
  inbox: Inbox;
  latest_message: Message | null;
  message_count: number;
  member_count: number;
}

export interface DistillJobProgress {
  conversations_total?: number;
  conversations_done?: number;
  windows_total?: number;
  windows_done?: number;
}

export interface DistillJobSummary {
  id: string;
  account_id: string;
  conversation_ids: string[];
  target_persona_id: string | null;
  provider: ProviderBrief;
  status: 'pending' | 'running' | 'done' | 'failed';
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface DistillJob extends DistillJobSummary {
  progress: DistillJobProgress;
  error_message: string | null;
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
  return request<null>('/auth/logout', { method: 'POST' });
}

export function authMe() {
  return request<Account>('/auth/me');
}

export function changeOwnPassword(data: { current_password: string; new_password: string }) {
  return request<null>('/auth/password', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Personas ---

export function getPersonas() { return request<PersonaSummary[]>('/personas'); }
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
  data: { name?: string; persona_md?: string; timezone?: string },
) {
  return request<Persona>(`/personas/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
export function deletePersona(id: string) {
  return request<null>(`/personas/${id}`, { method: 'DELETE' });
}

// --- Bridges (read-only + revoke; auto-provisioned by daemon handshake) ---

export function getBridges() { return request<Bridge[]>('/bridges'); }
export function deleteBridge(id: string) {
  return request<null>(`/bridges/${id}`, { method: 'DELETE' });
}

// --- Inboxes ---

export function getInboxes() { return request<Inbox[]>('/inboxes'); }
export function getInbox(id: string) { return request<Inbox>(`/inboxes/${id}`); }
export function updateInbox(
  id: string,
  data: {
    display_name?: string;
    bridge_id?: string | null;
  },
) {
  return request<Inbox>(`/inboxes/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Conversations ---

export function getConversations(inboxId?: string) {
  const qs = inboxId ? `?inbox_id=${encodeURIComponent(inboxId)}` : '';
  return request<ConversationListItem[]>(`/conversations${qs}`);
}
export function getConversation(conversationId: string) {
  return request<Conversation>(`/conversations/${conversationId}`);
}
export function getConversationMessages(conversationId: string, limit = 200) {
  return request<Message[]>(`/conversations/${conversationId}/messages?limit=${limit}`);
}
export function updateConversation(
  conversationId: string,
  data: {
    display_name?: string;
    card_md?: string;
    persona_id?: string | null;
    takeover?: boolean;
    reply_policy?: 'disabled' | 'autoreply';
    status?: 'active' | 'archived';
  },
) {
  return request<Conversation>(`/conversations/${conversationId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Distill ---

export function getDistillJobs() { return request<DistillJobSummary[]>('/distill-jobs'); }
export function getDistillJob(jobId: string) {
  return request<DistillJob>(`/distill-jobs/${jobId}`);
}
export function createDistillJob(data: {
  conversation_ids: string[]; target_persona_id?: string | null;
}) {
  return request<DistillJob>('/distill-jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
