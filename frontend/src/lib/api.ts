const CHAT_BASE = '/api';
const ROBOT_BASE = '/api/robot';

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

async function request<T>(url: string, options: RequestInit = {}, timeout = 10000): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const res = await fetch(url, { ...options, signal: controller.signal, credentials: 'same-origin' });
    clearTimeout(timeoutId);
    if (res.status === 401) {
      let detail = 'HTTP 401';
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch { /* ignore */ }
      if (unauthorizedHandler) unauthorizedHandler();
      throw new UnauthorizedError(detail);
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch {
        /* ignore */
      }
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

// --- Chat-side types ---

export interface ChatUser {
  id: string;
  name: string;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  user_a_id: string;
  user_b_id: string;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  conversation_id: string;
  sender_id: string;
  msg_type: string;
  content: string;
  created_at: string;
}

// --- Robot-side types ---

export type AccountRole = 'admin' | 'operator_owner';
export type AccountStatus = 'pending' | 'active' | 'disabled';

export interface Account {
  id: string;
  role: AccountRole;
  status: AccountStatus;
  display_name: string | null;
  email: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface ProviderConfig {
  id: string;
  name: string;
  base_url: string;
  api_key_preview?: string;
  has_api_key?: boolean;
  default_model: string;
  created_at: string;
  updated_at: string;
}

export interface Character {
  id: string;
  account_id: string;
  name: string;
  persona_md: string | null;
  adapter_identities: { chat?: string; wechat_wxid_self?: string };
  provider_config_id: string | null;
  provider_config: ProviderConfig | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Contact {
  id: string;
  character_id: string;
  display_name: string;
  wechat_wxid: string | null;
  chat_user_id: string | null;
  card_md: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ChatArchive {
  id: string;
  character_id: string;
  filename: string;
  self_wxid: string;
  message_count: number;
  contact_count: number;
  uploaded_at: string;
}

export interface DistillJobProgress {
  contacts_total?: number;
  contacts_done?: number;
  windows_total?: number;
  windows_done?: number;
}

export interface DistillJob {
  id: string;
  character_id: string;
  status: 'pending' | 'running' | 'done' | 'failed';
  progress: DistillJobProgress;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RobotSession {
  id: string;
  contact_id: string;
  adapter_type: string;
  adapter_thread_id: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PlannedReply {
  id: number;
  content: string;
  status: 'scheduled' | 'sent' | 'canceled';
  scheduled_for: string | null;
}

// --- Robot Auth ---

export function authRequestCode(email: string) {
  return request<{ status: string; expires_in_seconds: number }>(`${ROBOT_BASE}/auth/request-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
}

export function authVerifyCode(email: string, code: string) {
  return request<{ status: string; new_account: boolean; account: Account }>(
    `${ROBOT_BASE}/auth/verify-code`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, code }),
    }
  );
}

export function authLogout() {
  return request<{ status: string }>(`${ROBOT_BASE}/auth/logout`, { method: 'POST' });
}

export function authMe() {
  return request<Account>(`${ROBOT_BASE}/auth/me`);
}

// --- Robot Admin ---

export function adminListAccounts(status?: AccountStatus) {
  const q = status ? `?status=${status}` : '';
  return request<Account[]>(`${ROBOT_BASE}/admin/accounts${q}`);
}

export function adminApproveAccount(id: string) {
  return request<Account>(`${ROBOT_BASE}/admin/accounts/${id}/approve`, { method: 'POST' });
}

export function adminRejectAccount(id: string) {
  return request<Account>(`${ROBOT_BASE}/admin/accounts/${id}/reject`, { method: 'POST' });
}

export function adminDisableAccount(id: string) {
  return request<Account>(`${ROBOT_BASE}/admin/accounts/${id}/disable`, { method: 'POST' });
}

export function adminListCharacters() {
  return request<Character[]>(`${ROBOT_BASE}/admin/characters`);
}

// --- Chat Users ---

export function getUsers(includeDeleted = false) {
  const query = includeDeleted ? '?include_deleted=true' : '';
  return request<ChatUser[]>(`${CHAT_BASE}/users${query}`);
}

export function createUser(data: { name: string }) {
  return request<ChatUser>(`${CHAT_BASE}/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateUser(userId: string, data: { name: string }) {
  return request<ChatUser>(`${CHAT_BASE}/users/${userId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteUser(userId: string) {
  return request<ChatUser>(`${CHAT_BASE}/users/${userId}`, { method: 'DELETE' });
}

export function restoreUser(userId: string) {
  return request<ChatUser>(`${CHAT_BASE}/users/${userId}/restore`, { method: 'POST' });
}

// --- Chat Conversations ---

export function getConversations(includeDeleted = false) {
  const query = includeDeleted ? '?include_deleted=true' : '';
  return request<Conversation[]>(`${CHAT_BASE}/conversations${query}`);
}

export function createConversation(data: { title?: string; user_a_id: string; user_b_id: string }) {
  return request<Conversation>(`${CHAT_BASE}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteConversation(convId: string) {
  return request<Conversation>(`${CHAT_BASE}/conversations/${convId}`, { method: 'DELETE' });
}

// --- Chat Messages ---

export function sendMessage(conversationId: string, payload: { sender_id: string; msg_type: string; content: string }) {
  return request<{ status: string; id: number }>(`${CHAT_BASE}/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function getMessages(
  conversationId: string,
  lastId: number,
  serverTimeout = 30,
  signal?: AbortSignal
): Promise<Message[]> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), serverTimeout > 0 ? 35000 : 10000);
  if (signal) signal.addEventListener('abort', () => controller.abort());

  try {
    const res = await fetch(
      `${CHAT_BASE}/conversations/${conversationId}/messages?last_id=${lastId}&timeout=${serverTimeout}`,
      { signal: controller.signal }
    );
    clearTimeout(timeoutId);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return data?.messages || [];
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') return [];
    throw err;
  }
}

// --- Robot: Provider Configs ---

export function getProviderConfigs() {
  return request<ProviderConfig[]>(`${ROBOT_BASE}/provider-configs`);
}

export function createProviderConfig(data: {
  name: string;
  base_url: string;
  api_key: string | null;
  default_model: string;
}) {
  return request<ProviderConfig>(`${ROBOT_BASE}/provider-configs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateProviderConfig(
  id: string,
  data: { name?: string; base_url?: string; api_key?: string; default_model?: string }
) {
  return request<ProviderConfig>(`${ROBOT_BASE}/provider-configs/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteProviderConfig(id: string) {
  return request<void>(`${ROBOT_BASE}/provider-configs/${id}`, { method: 'DELETE' });
}

// --- Robot: Characters ---

export function getCharacters() {
  return request<Character[]>(`${ROBOT_BASE}/characters`);
}

export function getCharacter(id: string) {
  return request<Character>(`${ROBOT_BASE}/characters/${id}`);
}

export function createCharacter(data: { name: string; provider_config_id?: string | null }) {
  return request<Character>(`${ROBOT_BASE}/characters`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateCharacter(
  id: string,
  data: { name?: string; persona_md?: string | null; provider_config_id?: string | null; status?: string }
) {
  return request<Character>(`${ROBOT_BASE}/characters/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteCharacter(id: string) {
  return request<{ status: string; id: string }>(`${ROBOT_BASE}/characters/${id}`, { method: 'DELETE' });
}

// --- Robot: Contacts ---

export function getContacts(characterId: string) {
  return request<Contact[]>(`${ROBOT_BASE}/characters/${characterId}/contacts`);
}

export function getContact(contactId: string) {
  return request<Contact>(`${ROBOT_BASE}/contacts/${contactId}`);
}

export function updateContact(
  contactId: string,
  data: { display_name?: string; card_md?: string | null; status?: string }
) {
  return request<Contact>(`${ROBOT_BASE}/contacts/${contactId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Robot: Chat Archives ---

export function getArchives(characterId: string) {
  return request<ChatArchive[]>(`${ROBOT_BASE}/characters/${characterId}/chat-archives`);
}

export async function uploadArchive(
  characterId: string,
  file: File,
  selfWxid: string
): Promise<ChatArchive> {
  const form = new FormData();
  form.append('self_wxid', selfWxid);
  form.append('file', file);
  const res = await fetch(`${ROBOT_BASE}/characters/${characterId}/chat-archives`, {
    method: 'POST',
    body: form,
    credentials: 'same-origin',
  });
  if (res.status === 401) {
    if (unauthorizedHandler) unauthorizedHandler();
    throw new UnauthorizedError('未登录');
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

// --- Robot: Distill Jobs ---

export function getDistillJobs(characterId: string) {
  return request<DistillJob[]>(`${ROBOT_BASE}/characters/${characterId}/distill-jobs`);
}

export function getDistillJob(jobId: string) {
  return request<DistillJob>(`${ROBOT_BASE}/distill-jobs/${jobId}`);
}

export function createDistillJob(characterId: string) {
  return request<DistillJob>(`${ROBOT_BASE}/characters/${characterId}/distill-jobs`, {
    method: 'POST',
  });
}

// --- Robot: Sessions (read-only) ---

export function getSessions(characterId: string) {
  return request<RobotSession[]>(`${ROBOT_BASE}/characters/${characterId}/sessions`);
}

// --- Planned Replies (long-poll) ---

export async function getPlannedReplies(
  sessionId: string,
  lastCount: number,
  serverTimeout = 30,
  signal?: AbortSignal
): Promise<PlannedReply[]> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), serverTimeout > 0 ? 35000 : 10000);
  if (signal) signal.addEventListener('abort', () => controller.abort());

  try {
    const res = await fetch(
      `${ROBOT_BASE}/sessions/${sessionId}/planned-replies?timeout=${serverTimeout}&last_count=${lastCount}`,
      { signal: controller.signal, credentials: 'same-origin' }
    );
    clearTimeout(timeoutId);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') return [];
    throw err;
  }
}
