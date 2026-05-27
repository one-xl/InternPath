import { useRef, useState, useCallback } from "react";
import type { ReactNode } from "react";
import type { PageKey } from "../../types/navigation";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useIsMobile } from "../../hooks/useIsMobile";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(useGSAP);

interface AppShellProps {
  activePage: PageKey;
  onNavigate: (page: PageKey) => void;
  onLogout?: () => void;
  userRole?: string;
  generationLimit?: number;
  children: ReactNode;
}

export function AppShell({ activePage, onNavigate, onLogout, userRole, generationLimit, children }: AppShellProps) {
  const shellRef = useRef<HTMLDivElement | null>(null);
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  const handleNavigate = useCallback((page: PageKey) => {
    onNavigate(page);
    closeDrawer();
  }, [onNavigate, closeDrawer]);

  // ─── Desktop: original GSAP entrance animations (unchanged) ───
  useGSAP(() => {
    if (isMobile) return; // skip sidebar animations on mobile
    gsap.fromTo(".sidebar", 
      { x: -90, opacity: 0 }, 
      { x: 0, opacity: 1, duration: 0.8, ease: "power3.out" }
    );
    gsap.fromTo(".sidebar button", 
      { x: -15, opacity: 0 }, 
      { x: 0, opacity: 1, duration: 0.45, stagger: 0.04, ease: "power2.out", delay: 0.25 }
    );
    gsap.fromTo(".top-header", 
      { y: -25, opacity: 0 }, 
      { y: 0, opacity: 1, duration: 0.6, ease: "power2.out", delay: 0.1 }
    );
  }, { scope: shellRef, dependencies: [isMobile] });

  // Page transition animation
  useGSAP(() => {
    const dur = isMobile ? 0.3 : 0.45;
    gsap.fromTo(".app-main > *:not(.top-header):not(.mobile-topbar)", 
      { opacity: 0, y: isMobile ? 8 : 15, scale: 0.995 }, 
      { opacity: 1, y: 0, scale: 1, duration: dur, ease: "power2.out" }
    );
  }, { dependencies: [activePage, isMobile], scope: shellRef });

  // ─── MOBILE layout ───
  if (isMobile) {
    return (
      <div ref={shellRef} className="app-shell app-shell--mobile">
        {/* Fixed Top Bar */}
        <header className="mobile-topbar">
          <button
            type="button"
            className="mobile-topbar__burger"
            onClick={() => setDrawerOpen(true)}
            aria-label="打开导航菜单"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <span className="mobile-topbar__brand">InternPath</span>
          <div className="mobile-topbar__spacer" />
        </header>

        {/* Drawer overlay */}
        <div
          className={`mobile-drawer-overlay${drawerOpen ? " open" : ""}`}
          onClick={closeDrawer}
          aria-hidden="true"
        />

        {/* Drawer panel */}
        <nav className={`mobile-drawer-panel${drawerOpen ? " open" : ""}`} aria-label="主导航">
          <Sidebar
            variant="drawer"
            activePage={activePage}
            onNavigate={handleNavigate}
            onLogout={onLogout}
            userRole={userRole}
            generationLimit={generationLimit}
          />
        </nav>

        {/* Main content */}
        <div className="app-main app-main--mobile">
          <Header isMobile onNewAnalysis={() => onNavigate("new")} onHistory={() => onNavigate("history")} />
          {children}
        </div>
      </div>
    );
  }

  // ─── DESKTOP layout (original, unchanged) ───
  return (
    <div ref={shellRef} className="app-shell">
      <Sidebar activePage={activePage} onNavigate={onNavigate} onLogout={onLogout} userRole={userRole} generationLimit={generationLimit} />
      <div className="app-main">
        <Header onNewAnalysis={() => onNavigate("new")} onHistory={() => onNavigate("history")} />
        {children}
      </div>
    </div>
  );
}
