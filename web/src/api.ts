// Fetch wrapper. Credentials live only in HttpOnly cookies; the CSRF token is kept in memory.

let csrf = "";

export function setCsrf(token: string): void {
  csrf = token;
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; timeoutMs?: number } = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined ? "POST" : "GET");
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    if (csrf) headers["X-RB-CSRF"] = csrf;
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 90_000);
  let resp: Response;
  try {
    resp = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      body: method === "GET" ? undefined : JSON.stringify(opts.body ?? {}),
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new ApiError("NETWORK", ctrl.signal.aborted ? "The laptop did not answer in time." : "Cannot reach the laptop.", 0);
  } finally {
    clearTimeout(timer);
  }
  let data: any = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }
  if (!resp.ok) {
    const err = data?.error ?? {};
    throw new ApiError(err.code ?? `HTTP_${resp.status}`, err.message ?? `Request failed (${resp.status})`, resp.status);
  }
  return data as T;
}
