const API_BASE = '/api';
const TOKEN_KEY = 'laborster-chat-token';

export interface Account {
  id: string;
  username: string;
  display_name: string;
  avatar_url: string | null;
  status: string;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}

export interface Contact {
  id: string;
  account_id: string;
  platform_contact_id: string;
  display_name: string;
  avatar_url: string | null;
  note: string | null;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  account_id: string;
  contact_id: string;
  title: string;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  contact: Contact;
}

export interface Message {
  id: number;
  account_id: string;
  conversation_id: string;
  sender_type: 'self' | 'contact';
  sender_contact_id: string | null;
  msg_type: string;
  content: string;
  source: string;
  created_at: string;
}

export interface LoginResponse {
  token: string;
  account: Account;
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
  const token = getToken();
  const headers = new Headers(options.headers || {});
  if (token) headers.set('Authorization', `Bearer ${token}`);

  try {
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers, signal: controller.signal });
    clearTimeout(timeoutId);
    if (res.status === 401) {
      setToken(null);
      throw new Error('登录已失效，请重新登录');
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    const text = await res.text();
    return text ? JSON.parse(text) : (null as T);
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') throw new Error('请求超时');
    throw err;
  }
}

export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export function me(): Promise<Account> {
  return request<Account>('/auth/me');
}

export function logout(): Promise<void> {
  return request<void>('/auth/logout', { method: 'POST' });
}

export function listContacts(): Promise<Contact[]> {
  return request<Contact[]>('/contacts');
}

export function createContact(payload: {
  display_name: string;
  platform_contact_id?: string;
  note?: string;
}): Promise<Contact> {
  return request<Contact>('/contacts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function deleteContact(contactId: string): Promise<Contact> {
  return request<Contact>(`/contacts/${contactId}`, { method: 'DELETE' });
}

export function listConversations(): Promise<Conversation[]> {
  return request<Conversation[]>('/conversations');
}

export function sendMessage(
  conversationId: string,
  payload: { sender_type: 'self' | 'contact'; msg_type: string; content: string }
) {
  return request<{ status: string; id: number }>(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/**
 * Fetch messages newer than `lastId`.
 *
 * Server-side long-polling: `serverTimeout` (seconds) tells the server how long
 * to wait for new messages before returning an empty list. Pass `0` for an
 * immediate, non-blocking fetch (used for the initial load). Pass e.g. `30`
 * for the live tail.
 */
export async function getMessages(
  conversationId: string,
  lastId: number,
  serverTimeout = 30
): Promise<Message[]> {
  const token = getToken();
  const controller = new AbortController();
  // Client abort guard: server timeout + 5s, capped at 10s minimum for the
  // immediate (timeout=0) case.
  const clientTimeout = serverTimeout > 0 ? serverTimeout * 1000 + 5000 : 10000;
  const timeoutId = setTimeout(() => controller.abort(), clientTimeout);
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  try {
    const res = await fetch(
      `${API_BASE}/conversations/${conversationId}/messages?last_id=${lastId}&timeout=${serverTimeout}`,
      { headers, signal: controller.signal }
    );
    clearTimeout(timeoutId);
    if (res.status === 401) {
      setToken(null);
      throw new Error('登录已失效，请重新登录');
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return data?.messages || [];
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') return [];
    throw err;
  }
}

export function bulkImportMessages(
  conversationId: string,
  payload: {
    filename?: string;
    messages: Array<{
      sender_type: 'self' | 'contact';
      msg_type: string;
      content: string;
      created_at: string;
    }>;
  }
) {
  return request<{ status: string; imported: number; ids: number[] }>(
    `/conversations/${conversationId}/messages/bulk`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }
  );
}
