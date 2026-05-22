import type { ReactNode } from "react";
import type { PageKey } from "../../types/navigation";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

interface AppShellProps {
  activePage: PageKey;
  onNavigate: (page: PageKey) => void;
  onLogout?: () => void;
  children: ReactNode;
}

export function AppShell({ activePage, onNavigate, onLogout, children }: AppShellProps) {
  return (
    <div className="app-shell">
      <Sidebar activePage={activePage} onNavigate={onNavigate} onLogout={onLogout} />
      <div className="app-main">
        <Header onNewAnalysis={() => onNavigate("new")} onHistory={() => onNavigate("history")} />
        {children}
      </div>
    </div>
  );
}
