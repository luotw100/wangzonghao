const API_BASE = '/api';
const TOKEN_KEY = 'laborster-chat-token';

export interface Account {
  id: string;
  username: string;
  nickname: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Contact {
  id: string;
  account_id: string;
  username: string;
  nickname: string;
  remark_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  account_id: string;
  contact_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  contact: Contact;
}

export type MessageType = 'text' | 'image' | 'audio' | 'video' | 'file';

export interface Message {
  id: number;
  account_id: string;
  conversation_id: string;
  sender_id: string | null;
  msg_type: MessageType;
  content: string;
  created_at: string;
}

export interface UploadPresignResponse {
  storage_key: string;
  upload_url: string;
  fields: Record<string, string>;
}

export interface LoginResponse {
  token: string;
  account: Account;
}

export function contactDisplayName(contact: Contact): string {
  return contact.remark_name || contact.nickname;
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

export function updateMe(payload: { nickname: string }): Promise<Account> {
  return request<Account>('/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function createContact(payload: {
  nickname: string;
  username?: string;
  remark_name?: string;
}): Promise<Contact> {
  return request<Contact>('/contacts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function updateContact(contactId: string, payload: { remark_name?: string }): Promise<Contact> {
  return request<Contact>(`/contacts/${contactId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function listConversations(): Promise<Conversation[]> {
  return request<Conversation[]>('/conversations');
}

export function sendMessage(
  conversationId: string,
  payload: { sender_id: string | null; msg_type: MessageType; content: string; created_at?: string }
) {
  return request<{ status: string; count: number }>(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: [payload] }),
  });
}

export function bulkSendMessages(
  conversationId: string,
  messages: Array<{ sender_id: string | null; msg_type: MessageType; content: string; created_at: string }>
) {
  return request<{ status: string; count: number }>(
    `/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    },
    60000,
  );
}

export function presignUpload(filename: string, mimeType: string): Promise<UploadPresignResponse> {
  return request<UploadPresignResponse>('/uploads/presign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, mime_type: mimeType }),
  });
}

export async function uploadPresignedFile(presign: UploadPresignResponse, file: File): Promise<void> {
  const form = new FormData();
  for (const [k, v] of Object.entries(presign.fields)) form.append(k, v);
  form.append('file', file);
  const res = await fetch(presign.upload_url, { method: 'POST', body: form });
  if (!res.ok) {
    throw new Error(`文件上传失败: HTTP ${res.status}`);
  }
}

export function mediaUrl(storageKey: string): string {
  const token = getToken();
  const base = `${API_BASE}/media/${storageKey}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export async function getMessagesBefore(
  conversationId: string,
  beforeId?: number,
  limit = 100,
): Promise<Message[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (beforeId !== undefined) params.set('before_id', String(beforeId));
  const data = await request<{ messages: Message[] }>(
    `/conversations/${conversationId}/messages/before?${params}`
  );
  return data?.messages || [];
}

export async function getMessagesAfter(
  conversationId: string,
  lastId: number,
  limit = 0,
  serverTimeout = 30,
): Promise<Message[]> {
  const token = getToken();
  const controller = new AbortController();
  const clientTimeout = serverTimeout > 0 ? serverTimeout * 1000 + 5000 : 10000;
  const timeoutId = setTimeout(() => controller.abort(), clientTimeout);
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const params = new URLSearchParams({
    last_id: String(lastId),
    timeout: String(serverTimeout),
  });
  if (limit > 0) params.set('limit', String(limit));

  try {
    const res = await fetch(
      `${API_BASE}/conversations/${conversationId}/messages/after?${params}`,
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
