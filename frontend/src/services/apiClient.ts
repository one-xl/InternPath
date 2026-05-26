export async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let message = `API ${res.status}`;
    let detail = "";
    try {
      const text = await res.text();
      try {
        const parsed = JSON.parse(text);
        detail = parsed.detail || "";
        if (detail) {
          message = detail;
        }
      } catch {
        detail = text;
      }
    } catch {}
    const err: any = new Error(message);
    err.status = res.status;
    err.responseBody = detail;
    throw err;
  }
  return res.json();
}
