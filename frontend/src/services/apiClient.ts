export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const err: any = new Error(`API ${res.status}`);
    err.status = res.status;
    try {
      err.responseBody = await res.text();
    } catch {}
    throw err;
  }
  return res.json();
}
