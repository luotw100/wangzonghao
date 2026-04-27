const CHAT_BASE = '/api';
const ROBOT_BASE = '/api/robot';

async function request<T>(url: string, options: RequestInit = {}, timeout = 10000): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timeoutId);
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

// --- Types ---

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

export interface ProviderConfig {
  id: string;
  name: string;
  base_url: string;
  api_key_preview?: string;
  default_model: string;
  created_at: string;
  updated_at: string;
}

export interface Session {
  id: string;
  adapter_type: string;
  adapter_thread_id: string;
  takeover_user_id: string;
  profile: string | null;
  counterpart_profile: string | null;
  provider_config_id: string | null;
  provider_config: ProviderConfig | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PlannedReply {
  id: number;
  content: string;
  status: 'scheduled' | 'locked';
  scheduled_for: string | null;
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

export function updateConversation(convId: string, data: { title: string }) {
  return request<Conversation>(`${CHAT_BASE}/conversations/${convId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteConversation(convId: string) {
  return request<Conversation>(`${CHAT_BASE}/conversations/${convId}`, { method: 'DELETE' });
}

export function restoreConversation(convId: string) {
  return request<Conversation>(`${CHAT_BASE}/conversations/${convId}/restore`, { method: 'POST' });
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

  if (signal) {
    signal.addEventListener('abort', () => controller.abort());
  }

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

// --- Robot Provider Configs ---

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
  data: { name: string; base_url: string; api_key?: string; default_model: string }
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

// --- Robot Sessions ---

export function getRobotConversations() {
  return request<Conversation[]>(`${ROBOT_BASE}/conversations`);
}

export function getSessions() {
  return request<Session[]>(`${ROBOT_BASE}/sessions`);
}

export function createSession(data: {
  adapter_thread_id: string;
  takeover_user_id: string;
  profile?: string | null;
  counterpart_profile?: string | null;
  provider_config_id?: string | null;
}) {
  return request<Session>(`${ROBOT_BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function getSession(sessionId: string) {
  return request<Session>(`${ROBOT_BASE}/sessions/${sessionId}`);
}

export function updateSession(sessionId: string, data: Record<string, unknown>) {
  return request<Session>(`${ROBOT_BASE}/sessions/${sessionId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteSession(sessionId: string) {
  return request<void>(`${ROBOT_BASE}/sessions/${sessionId}`, { method: 'DELETE' });
}

// --- Planned Replies ---

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
      { signal: controller.signal }
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
