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
