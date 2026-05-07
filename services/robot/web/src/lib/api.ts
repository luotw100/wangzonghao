const API_BASE = '/api';
const TOKEN_KEY = 'laborster-robot-token';

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
  last_login_at: string | null;
}

export interface LoginResponse {
  token: string;
  account: Account;
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
  wechat_wxid_self: string | null;
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

// --- Provider Configs ---

export function getProviderConfigs() {
  return request<ProviderConfig[]>('/provider-configs');
}

export function createProviderConfig(data: {
  name: string;
  base_url: string;
  api_key: string | null;
  default_model: string;
}) {
  return request<ProviderConfig>('/provider-configs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateProviderConfig(
  id: string,
  data: { name?: string; base_url?: string; api_key?: string; default_model?: string }
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

// --- Characters ---

export function getCharacters() {
  return request<Character[]>('/characters');
}

export function getCharacter(id: string) {
  return request<Character>(`/characters/${id}`);
}

export function createCharacter(data: {
  name: string;
  wechat_wxid_self?: string | null;
  provider_config_id?: string | null;
}) {
  return request<Character>('/characters', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function updateCharacter(
  id: string,
  data: {
    name?: string;
    persona_md?: string | null;
    wechat_wxid_self?: string | null;
    provider_config_id?: string | null;
    status?: string;
  }
) {
  return request<Character>(`/characters/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function deleteCharacter(id: string) {
  return request<{ status: string; id: string }>(`/characters/${id}`, { method: 'DELETE' });
}

// --- Contacts ---

export function getContacts(characterId: string) {
  return request<Contact[]>(`/characters/${characterId}/contacts`);
}

export function getContact(contactId: string) {
  return request<Contact>(`/contacts/${contactId}`);
}

export function updateContact(
  contactId: string,
  data: { display_name?: string; card_md?: string | null; status?: string }
) {
  return request<Contact>(`/contacts/${contactId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// --- Chat Archives ---

export function getArchives(characterId: string) {
  return request<ChatArchive[]>(`/characters/${characterId}/chat-archives`);
}

export async function uploadArchive(
  characterId: string,
  file: File,
  selfWxid: string
): Promise<ChatArchive> {
  const form = new FormData();
  form.append('self_wxid', selfWxid);
  form.append('file', file);
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(`${API_BASE}/characters/${characterId}/chat-archives`, {
    method: 'POST',
    headers,
    body: form,
  });
  if (res.status === 401) {
    setToken(null);
    if (unauthorizedHandler) unauthorizedHandler();
    throw new UnauthorizedError('未登录');
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

// --- Distill Jobs ---

export function getDistillJobs(characterId: string) {
  return request<DistillJob[]>(`/characters/${characterId}/distill-jobs`);
}

export function getDistillJob(jobId: string) {
  return request<DistillJob>(`/distill-jobs/${jobId}`);
}

export function createDistillJob(characterId: string) {
  return request<DistillJob>(`/characters/${characterId}/distill-jobs`, {
    method: 'POST',
  });
}
