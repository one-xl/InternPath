import { useRef } from "react";
import type { ReactNode } from "react";
import type { PageKey } from "../../types/navigation";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
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

  // 1. Initial mount entrance animation (Google Dashboard Assembly style)
  useGSAP(() => {
    // Sidebar glides in from left
    gsap.fromTo(".sidebar", 
      { x: -90, opacity: 0 }, 
      { x: 0, opacity: 1, duration: 0.8, ease: "power3.out" }
    );

    // Sidebar navigation buttons stagger slide-in
    gsap.fromTo(".sidebar button", 
      { x: -15, opacity: 0 }, 
      { x: 0, opacity: 1, duration: 0.45, stagger: 0.04, ease: "power2.out", delay: 0.25 }
    );

    // Header slides down and fades in
    gsap.fromTo(".top-header", 
      { y: -25, opacity: 0 }, 
      { y: 0, opacity: 1, duration: 0.6, ease: "power2.out", delay: 0.1 }
    );
  }, { scope: shellRef });

  // 2. Seamless page transition when activePage tab changes
  useGSAP(() => {
    gsap.fromTo(".app-main > *:not(.top-header)", 
      { opacity: 0, y: 15, scale: 0.99 }, 
      { opacity: 1, y: 0, scale: 1, duration: 0.45, ease: "power2.out" }
    );
  }, { dependencies: [activePage], scope: shellRef });

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
