import { useState, useEffect } from "react";

const MOBILE_QUERY = "(max-width: 768px)";

/**
 * Returns true when the viewport is ≤ 768 px (mobile / small tablet).
 * Uses CSS matchMedia so it auto-updates on resize and is cheap to poll.
 */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia(MOBILE_QUERY).matches;
  });

  useEffect(() => {
    const mql = window.matchMedia(MOBILE_QUERY);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return isMobile;
}
