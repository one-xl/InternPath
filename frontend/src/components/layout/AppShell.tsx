import type { ReactNode } from "react";
import type { PageKey } from "../../types/navigation";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

interface AppShellProps {
  activePage: PageKey;
  onNavigate: (page: PageKey) => void;
  onLogout?: () => void;
  userRole?: string;
  children: ReactNode;
}

export function AppShell({ activePage, onNavigate, onLogout, userRole, children }: AppShellProps) {
  return (
    <div className="app-shell">
      <Sidebar activePage={activePage} onNavigate={onNavigate} onLogout={onLogout} userRole={userRole} />
      <div className="app-main">
        <Header onNewAnalysis={() => onNavigate("new")} onHistory={() => onNavigate("history")} />
        {children}
      </div>
    </div>
  );
}
