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
export interface Robot {
  id: string;
  name: string;
  profile: string | null;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Contact {
  id: string;
  name: string;
  profile: string | null;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
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
  title: string | null;
  robot_id: string;
  contact_id: string;
  provider_config_id: string | null;
  status: string;
  adapter?: { thread_id: string };
  robot?: { id: string; name: string };
  contact?: { id: string; name: string };
  created_at: string;
  updated_at: string;
}

export interface PlannedReply {
  id: number;
  content: string;
  scheduled_for: string | null;
}

export interface Message {
  id: number;
  conversation_id: string;
  role: 'user' | 'robot';
  msg_type: string;
  content: string;
  created_at: string;
}

// --- Robots ---
export function getRobots(includeDeleted = false) {
  const query = includeDeleted ? '?include_deleted=true' : '';
  return request<Robot[]>(`${ROBOT_BASE}/robots${query}`);
}

export function createRobot(data: { name: string; profile?: string | null }) {
  return request<Robot>(`${ROBOT_BASE}/robots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateRobot(robotId: string, data: { name: string; profile?: string | null }) {
  return request<Robot>(`${ROBOT_BASE}/robots/${robotId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteRobot(robotId: string) {
  return request<void>(`${ROBOT_BASE}/robots/${robotId}`, { method: 'DELETE' });
}

export function restoreRobot(robotId: string) {
  return request<Robot>(`${ROBOT_BASE}/robots/${robotId}/restore`, { method: 'POST' });
}

// --- Contacts ---
export function getContacts(includeDeleted = false) {
  const query = includeDeleted ? '?include_deleted=true' : '';
  return request<Contact[]>(`${ROBOT_BASE}/contacts${query}`);
}

export function createContact(data: { name: string; profile?: string | null }) {
  return request<Contact>(`${ROBOT_BASE}/contacts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateContact(contactId: string, data: { name: string; profile?: string | null }) {
  return request<Contact>(`${ROBOT_BASE}/contacts/${contactId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteContact(contactId: string) {
  return request<void>(`${ROBOT_BASE}/contacts/${contactId}`, { method: 'DELETE' });
}

export function restoreContact(contactId: string) {
  return request<Contact>(`${ROBOT_BASE}/contacts/${contactId}/restore`, { method: 'POST' });
}

// --- Provider Configs ---
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

// --- Sessions ---
export function getSessions(includeDeleted = false) {
  const query = includeDeleted ? '?include_deleted=true' : '';
  return request<Session[]>(`${ROBOT_BASE}/sessions${query}`);
}

export function createSession(data: {
  robot_id: string;
  contact_id: string;
  title?: string | null;
  provider_config_id?: string | null;
}) {
  return request<Session>(`${ROBOT_BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function getSession(sessionId: string) {
  return request<Session>(`${ROBOT_BASE}/sessions/${sessionId}?include_deleted=true`);
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

export function restoreSession(sessionId: string) {
  return request<Session>(`${ROBOT_BASE}/sessions/${sessionId}/restore`, { method: 'POST' });
}

// --- Messages ---
export function sendMessage(conversationId: string, payload: { role: string; msg_type: string; content: string }) {
  return request<Message>(`${CHAT_BASE}/conversations/${conversationId}/messages`, {
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
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const payload = await res.json();
    return payload.messages || [];
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('请求超时，请检查网络连接');
    }
    throw err;
  }
}

export async function getPlannedReplies(
  sessionId: string,
  serverTimeout = 30,
  signal?: AbortSignal,
  lastCount = -1
): Promise<PlannedReply[]> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), serverTimeout > 0 ? 35000 : 10000);

  if (signal) {
    signal.addEventListener('abort', () => controller.abort());
  }

  try {
    const res = await fetch(
      `${ROBOT_BASE}/sessions/${sessionId}/planned-replies?timeout=${serverTimeout}&last_count=${lastCount}`,
      { signal: controller.signal }
    );
    clearTimeout(timeoutId);
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return await res.json();
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('请求超时，请检查网络连接');
    }
    throw err;
  }
}
