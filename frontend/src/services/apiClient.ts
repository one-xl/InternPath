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
      detail = text;
      try {
        const parsed = JSON.parse(text);
        if (parsed && parsed.detail) {
          if (typeof parsed.detail === "string") {
            message = parsed.detail;
          } else if (Array.isArray(parsed.detail)) {
            message = parsed.detail.map((err: any) => {
              const loc = err.loc ? `[${err.loc.join(".")}] ` : "";
              return `${loc}${err.msg || JSON.stringify(err)}`;
            }).join("; ");
          } else {
            message = JSON.stringify(parsed.detail);
          }
        } else if (parsed && parsed.message) {
          message = parsed.message;
        }
      } catch {
        // Not a JSON response
        if (text && text.length < 200 && !text.includes("<html") && !text.includes("<HTML")) {
          message = text;
        } else if (text) {
          // Try to extract title/heading from HTML
          const titleMatch = text.match(/<title>([\s\S]*?)<\/title>/i);
          const h1Match = text.match(/<h1>([\s\S]*?)<\/h1>/i);
          if (h1Match && h1Match[1]) {
            message = h1Match[1].trim();
          } else if (titleMatch && titleMatch[1]) {
            message = titleMatch[1].trim();
          }
        }
      }
    } catch {}
    const err: any = new Error(message);
    err.status = res.status;
    err.responseBody = detail;
    throw err;
  }
  return res.json();
}
