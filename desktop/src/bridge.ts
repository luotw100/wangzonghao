declare global {
  interface Window {
    bridge?: { baseUrl: string; token: string };
  }
}

const bridge = window.bridge;

export const bridgeReady = Boolean(bridge?.baseUrl && bridge?.token);

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  if (!bridge) throw new Error("bridge preload missing");
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${bridge.token}`);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const res = await fetch(bridge.baseUrl + path, { ...init, headers });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

// POST a /local/<method> call: JSON body becomes the Api method's kwargs.
export function post<T = unknown>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
