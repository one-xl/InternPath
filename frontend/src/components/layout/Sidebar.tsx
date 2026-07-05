import type { PageKey } from "../../types/navigation";

const navItems: { key: PageKey; label: string; icon: React.ReactNode }[] = [
  {
    key: "dashboard",
    label: "工作台",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="9" rx="1" />
        <rect x="14" y="3" width="7" height="5" rx="1" />
        <rect x="14" y="12" width="7" height="9" rx="1" />
        <rect x="3" y="16" width="7" height="5" rx="1" />
      </svg>
    ),
  },
  {
    key: "new",
    label: "新建分析",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="16" />
        <line x1="8" y1="12" x2="16" y2="12" />
      </svg>
    ),
  },
  {
    key: "history",
    label: "历史记录",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
  },
  {
    key: "profile",
    label: "个人材料",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
        <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
      </svg>
    ),
  },
  {
    key: "settings",
    label: "服务配置",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
  },
  {
    key: "agent-resume",
    label: "简历定向优化",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
        <line x1="12" y1="22.08" x2="12" y2="12" />
      </svg>
    ),
  },
];

export function Sidebar({
  activePage,
  onNavigate,
  onLogout,
  userRole,
  generationLimit,
  variant = "desktop",
}: {
  activePage: PageKey;
  onNavigate: (page: PageKey) => void;
  onLogout?: () => void;
  userRole?: string;
  generationLimit?: number;
  variant?: "desktop" | "drawer";
}) {
  const visibleItems = userRole === "admin"
    ? [
        ...navItems,
        {
          key: "admin" as PageKey,
          label: "管理员控制台",
          icon: (
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <circle cx="12" cy="11" r="3" />
              <path d="M12 14v4" />
            </svg>
          ),
        },
      ]
    : navItems;

  // ─── Drawer variant (mobile) ───
  if (variant === "drawer") {
    return (
      <div className="drawer-sidebar">
        <div className="drawer-sidebar-brand">
          <strong>InternPath</strong>
          <span>Personal Desk</span>
        </div>
        <div className="drawer-sidebar-nav">
          {visibleItems.map((item) => (
            <button
              key={item.key}
              type="button"
              className={item.key === activePage ? "active" : ""}
              onClick={() => onNavigate(item.key)}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>

        {/* Remaining Generation Limit Card */}
        {userRole !== "admin" && generationLimit !== undefined && (
          <div className="drawer-sidebar-limit">
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
              <span>剩余分析额度</span>
              <strong style={{ color: generationLimit > 0 ? "var(--accent)" : "var(--danger)" }}>
                {generationLimit} 次
              </strong>
            </div>
            <div style={{
              width: "100%",
              height: "4px",
              background: "var(--line)",
              borderRadius: "2px",
              overflow: "hidden"
            }}>
              <div style={{
                width: `${Math.min(100, (generationLimit / 5) * 100)}%`,
                height: "100%",
                background: generationLimit > 1 ? "var(--accent)" : "var(--danger)",
                transition: "width 300ms ease"
              }} />
            </div>
          </div>
        )}

        {onLogout && (
          <button
            type="button"
            className="drawer-sidebar-logout"
            onClick={onLogout}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            退出登录
          </button>
        )}
      </div>
    );
  }

  // ─── Desktop variant (original, unchanged) ───
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <strong>InternPath</strong>
        <span>Personal Desk</span>
      </div>
      <nav style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "2px", width: "100%" }}>
          {visibleItems.map((item) => (
            <button
              key={item.key}
              type="button"
              className={item.key === activePage ? "active" : ""}
              onClick={() => onNavigate(item.key)}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>

        {/* Remaining Generation Limit Card */}
        {userRole !== "admin" && generationLimit !== undefined && (
          <div style={{
            background: "rgba(255, 255, 255, 0.03)",
            border: "1px solid rgba(255, 255, 255, 0.06)",
            borderRadius: "var(--radius-md)",
            padding: "10px 12px",
            margin: "auto 0 12px 0",
            fontSize: "12px",
            color: "rgba(255, 255, 255, 0.7)",
            boxSizing: "border-box"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
              <span>剩余分析额度</span>
              <strong style={{ color: generationLimit > 0 ? "#fbbf24" : "#f87171" }}>
                {generationLimit} 次
              </strong>
            </div>
            <div style={{
              width: "100%",
              height: "4px",
              background: "rgba(255, 255, 255, 0.08)",
              borderRadius: "2px",
              overflow: "hidden"
            }}>
              <div style={{
                width: `${Math.min(100, (generationLimit / 5) * 100)}%`,
                height: "100%",
                background: generationLimit > 1 ? "#fbbf24" : "#f87171",
                transition: "width 300ms ease"
              }} />
            </div>
          </div>
        )}

        {onLogout && (
          <button
            type="button"
            className="sidebar-logout-btn"
            onClick={onLogout}
            style={{
              marginTop: userRole === "admin" || generationLimit === undefined ? "auto" : "0px",
              color: "rgba(239, 68, 68, 0.95)",
              background: "rgba(239, 68, 68, 0.08)",
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "10px 14px",
              borderRadius: "var(--radius-md)",
              border: "1px solid rgba(239, 68, 68, 0.15)",
              fontWeight: 600,
              fontSize: "13px",
              cursor: "pointer",
              transition: "all 150ms ease",
              width: "100%",
              boxSizing: "border-box"
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            退出登录
          </button>
        )}
      </nav>
    </aside>
  );
}
