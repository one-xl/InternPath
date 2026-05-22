/**
 * Generates a UUID v4 string safely.
 * Detects if crypto.randomUUID is available (secure contexts/HTTPS/localhost).
 * Falls back to a high-quality Math.random() generator in unsecure HTTP contexts (IP server deployments).
 */
export function safeUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  
  // RFC 4122 compliant UUID v4 fallback
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
