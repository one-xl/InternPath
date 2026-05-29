import { useRef, useState, useCallback, useEffect } from "react";
import type { ReactNode } from "react";
import type { PageKey } from "../../types/navigation";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { useIsMobile } from "../../hooks/useIsMobile";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { Button } from "../ui/Button";
import { fetchActiveAnnouncements } from "../../services/adminService";
import type { AdminAnnouncement } from "../../services/adminService";

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

  // Active Announcements States
  const [activeAnnouncements, setActiveAnnouncements] = useState<AdminAnnouncement[]>([]);
  const [activePopupAnnouncements, setActivePopupAnnouncements] = useState<AdminAnnouncement[]>([]);
  const [currentAnnIndex, setCurrentAnnIndex] = useState(0);
  const [currentPopupIndex, setCurrentPopupIndex] = useState(0);
  const [showDetailModal, setShowDetailModal] = useState(false);

  // Shatter effect states
  const [isBreaking, setIsBreaking] = useState(false);
  const [shatterRect, setShatterRect] = useState<DOMRect | null>(null);
  const [shatterPieces, setShatterPieces] = useState<any[]>([]);

  useEffect(() => {
    async function loadActiveAnnouncements() {
      try {
        const list = await fetchActiveAnnouncements();
        const closedRaw = localStorage.getItem("closed_announcements");
        const closedIds: string[] = closedRaw ? JSON.parse(closedRaw) : [];
        const sessionClosedRaw = sessionStorage.getItem("closed_session_announcements");
        const sessionClosedIds: string[] = sessionClosedRaw ? JSON.parse(sessionClosedRaw) : [];
        
        const isClosed = (ann: AdminAnnouncement) => {
          if (!ann.id) return true;
          if (ann.show_behavior === 'always') {
            return false;
          }
          if (ann.show_behavior === 'every_login') {
            return sessionClosedIds.includes(ann.id);
          }
          return closedIds.includes(ann.id);
        };
        
        const filteredTop = list.filter(ann => (!ann.announcement_type || ann.announcement_type === 'top') && !isClosed(ann));
        const filteredPopup = list.filter(ann => ann.announcement_type === 'popup' && !isClosed(ann));
        
        setActiveAnnouncements(filteredTop);
        setActivePopupAnnouncements(filteredPopup);
      } catch (e) {
        console.error("Failed to load active announcements:", e);
      }
    }
    loadActiveAnnouncements();
    
    const timer = setInterval(loadActiveAnnouncements, 5 * 60 * 1000);
    return () => clearInterval(timer);
  }, []);

  const handleCloseAnnouncement = (id: string, isPopup: boolean = false) => {
    const targetAnn = [...activeAnnouncements, ...activePopupAnnouncements].find(a => a.id === id);
    const showBehavior = targetAnn?.show_behavior || 'once';

    if (showBehavior === 'every_login') {
      const closedRaw = sessionStorage.getItem("closed_session_announcements");
      const closedIds: string[] = closedRaw ? JSON.parse(closedRaw) : [];
      if (!closedIds.includes(id)) {
        closedIds.push(id);
        sessionStorage.setItem("closed_session_announcements", JSON.stringify(closedIds));
      }
    } else {
      const closedRaw = localStorage.getItem("closed_announcements");
      const closedIds: string[] = closedRaw ? JSON.parse(closedRaw) : [];
      if (!closedIds.includes(id)) {
        closedIds.push(id);
        localStorage.setItem("closed_announcements", JSON.stringify(closedIds));
      }
    }
    if (isPopup) {
      setActivePopupAnnouncements(prev => prev.filter(ann => ann.id !== id));
    } else {
      setActiveAnnouncements(prev => prev.filter(ann => ann.id !== id));
    }
  };

  const currentAnnouncement = activeAnnouncements[currentAnnIndex];
  const currentPopup = activePopupAnnouncements[currentPopupIndex];

  const triggerShatterAndClose = () => {
    if (!currentPopup || !currentPopup.id) return;
    
    const modalContentEl = document.querySelector(".popup-modal-content");
    if (modalContentEl) {
      const rect = modalContentEl.getBoundingClientRect();
      setShatterRect(rect);
      
      const rows = 8;
      const cols = 8;
      const pieceWidth = rect.width / cols;
      const pieceHeight = rect.height / rows;
      const pieces = [];
      
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          pieces.push({
            id: `${r}-${c}`,
            left: c * pieceWidth,
            top: r * pieceHeight,
            width: pieceWidth,
            height: pieceHeight,
            bgX: -c * pieceWidth,
            bgY: -r * pieceHeight
          });
        }
      }
      setShatterPieces(pieces);
      setIsBreaking(true);
      
      setTimeout(() => {
        gsap.to(".shatter-piece", {
          x: () => gsap.utils.random(-300, 300),
          y: () => gsap.utils.random(-300, 300),
          z: () => gsap.utils.random(-200, 200),
          rotation: () => gsap.utils.random(-360, 360),
          rotationX: () => gsap.utils.random(-360, 360),
          rotationY: () => gsap.utils.random(-360, 360),
          scale: 0.1,
          autoAlpha: 0,
          stagger: {
            amount: 0.3,
            from: "center"
          },
          duration: 0.9,
          ease: "power2.out",
          onComplete: () => {
            handleCloseAnnouncement(currentPopup.id!, true);
            setIsBreaking(false);
            setShatterRect(null);
            setShatterPieces([]);
          }
        });
      }, 30);
    } else {
      handleCloseAnnouncement(currentPopup.id, true);
    }
  };

  const renderPopupAnnouncement = () => {
    if (!currentPopup) return null;
    
    return (
      <div 
        style={{ 
          position: "fixed", 
          top: 0, 
          left: 0, 
          right: 0, 
          bottom: 0, 
          background: isBreaking ? "transparent" : "rgba(0,0,0,0.75)", 
          backdropFilter: isBreaking ? "none" : "blur(12px)", 
          display: "flex", 
          justifyContent: "center", 
          alignItems: "center", 
          zIndex: 1200,
          transition: "background 0.5s ease"
        }}
      >
        <div 
          className="popup-modal-content"
          style={{ 
            background: "linear-gradient(135deg, rgba(16, 22, 18, 0.97) 0%, rgba(8, 10, 9, 0.99) 100%)", 
            border: "1px solid rgba(29, 185, 84, 0.28)", 
            boxShadow: "0 0 50px rgba(29, 185, 84, 0.15)",
            borderRadius: "var(--radius-lg)", 
            padding: "28px", 
            width: "480px", 
            maxWidth: "90%", 
            display: "flex", 
            flexDirection: "column", 
            gap: "20px",
            position: "relative",
            opacity: isBreaking ? 0 : 1,
            pointerEvents: isBreaking ? "none" : "auto",
            transition: "opacity 0.1s ease"
          }}
        >
          <div style={{ position: "absolute", top: 0, left: "10%", right: "10%", height: "2px", background: "linear-gradient(90deg, transparent, #1db954, transparent)" }} />
          
          <div style={{ display: "flex", alignItems: "center", gap: "10px", borderBottom: "1px solid rgba(29, 185, 84, 0.15)", paddingBottom: "12px" }}>
            <span style={{ fontSize: "22px", filter: "drop-shadow(0 0 6px rgba(29,185,84,0.7))" }}>📢</span>
            <h3 style={{ color: "#fff", fontSize: "17px", fontWeight: "900", letterSpacing: "0.5px" }}>
              {currentPopup.title}
            </h3>
          </div>
          
          <div style={{ color: "rgba(255,255,255,0.85)", fontSize: "14px", lineHeight: "1.6", whiteSpace: "pre-wrap", maxHeight: "250px", overflowY: "auto" }}>
            {currentPopup.content}
          </div>
          
          <div style={{ display: "flex", justifyContent: "flex-end", borderTop: "1px solid rgba(255, 255, 255, 0.06)", paddingTop: "14px" }}>
            <button 
              type="button" 
              onClick={triggerShatterAndClose} 
              style={{ 
                background: "linear-gradient(135deg, #1db954 0%, #148f3e 100%)", 
                borderColor: "#1ed760",
                borderWidth: "1px",
                borderStyle: "solid",
                boxShadow: "0 4px 14px rgba(29, 185, 84, 0.35)",
                padding: "8px 24px",
                fontSize: "13px",
                fontWeight: "bold",
                color: "#fff",
                borderRadius: "var(--radius-sm)",
                cursor: "pointer",
                transition: "all 0.2s ease"
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.filter = "brightness(1.1)";
                e.currentTarget.style.transform = "scale(1.02)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.filter = "none";
                e.currentTarget.style.transform = "none";
              }}
            >
              我知道了，确悉
            </button>
          </div>
        </div>

        {isBreaking && shatterRect && (
          <div 
            style={{ 
              position: "absolute",
              left: shatterRect.left,
              top: shatterRect.top,
              width: shatterRect.width,
              height: shatterRect.height,
              pointerEvents: "none",
              perspective: "800px"
            }}
          >
            {shatterPieces.map((piece) => (
              <div 
                key={piece.id}
                className="shatter-piece"
                style={{
                  position: "absolute",
                  left: piece.left,
                  top: piece.top,
                  width: piece.width,
                  height: piece.height,
                  background: "linear-gradient(135deg, #101612 0%, #060807 100%)",
                  border: "1px solid rgba(29, 185, 84, 0.2)",
                  boxShadow: "0 0 8px rgba(29, 185, 84, 0.15)",
                  backgroundSize: `${shatterRect.width}px ${shatterRect.height}px`,
                  backgroundPosition: `${piece.bgX}px ${piece.bgY}px`,
                  boxSizing: "border-box"
                }}
              />
            ))}
          </div>
        )}
      </div>
    );
  };

  // GSAP animation for announcement banner
  useGSAP(() => {
    if (activeAnnouncements.length > 0) {
      gsap.fromTo(".announcement-banner", 
        { y: -15, opacity: 0, scale: 0.98 }, 
        { y: 0, opacity: 1, scale: 1, duration: 0.5, ease: "power2.out" }
      );
    }
  }, { scope: shellRef, dependencies: [activeAnnouncements.length] });

  const renderAnnouncementBanner = () => {
    if (!currentAnnouncement) return null;
    return (
      <div
        className="announcement-banner"
        style={{
          background: "linear-gradient(135deg, rgba(245, 158, 11, 0.15) 0%, rgba(239, 68, 68, 0.1) 100%)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(245, 158, 11, 0.25)",
          borderRadius: "var(--radius-md)",
          margin: isMobile ? "8px 12px 0 12px" : "12px 20px 0 20px",
          padding: "10px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          boxShadow: "0 4px 20px rgba(0, 0, 0, 0.2)",
          position: "relative",
          zIndex: 10,
          overflow: "hidden"
        }}
      >
        <div style={{ position: "absolute", top: "-50%", left: "-10%", width: "120px", height: "120px", background: "rgba(245, 158, 11, 0.15)", filter: "blur(40px)", borderRadius: "50%", pointerEvents: "none" }} />
        
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: "16px", display: "flex", alignItems: "center", color: "#f59e0b", filter: "drop-shadow(0 0 4px rgba(245,158,11,0.4))" }}>
            📢
          </span>
          <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
            <span style={{ fontWeight: "700", color: "#fff", fontSize: "13px" }}>{currentAnnouncement.title}</span>
            <span style={{ color: "rgba(255,255,255,0.7)", fontSize: "12px", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
              {currentAnnouncement.content}
            </span>
          </div>
          {currentAnnouncement.content.length > 30 && (
            <button
              type="button"
              onClick={() => setShowDetailModal(true)}
              style={{ background: "transparent", border: "none", color: "var(--accent)", fontSize: "11px", fontWeight: "bold", cursor: "pointer", textDecoration: "underline", marginLeft: "8px", whiteSpace: "nowrap" }}
            >
              详情
            </button>
          )}
        </div>

        {currentAnnouncement.show_behavior !== 'always' && (
          <button
            type="button"
            onClick={() => currentAnnouncement.id && handleCloseAnnouncement(currentAnnouncement.id)}
            style={{ background: "transparent", border: "none", color: "rgba(255,255,255,0.4)", cursor: "pointer", fontSize: "16px", padding: "4px 8px", transition: "color 0.2s" }}
            onMouseEnter={(e) => e.currentTarget.style.color = "#fff"}
            onMouseLeave={(e) => e.currentTarget.style.color = "rgba(255,255,255,0.4)"}
            aria-label="关闭公告"
          >
            ✕
          </button>
        )}
      </div>
    );
  };

  const renderDetailModal = () => {
    if (!showDetailModal || !currentAnnouncement) return null;
    return (
      <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)", display: "flex", justifyContent: "center", alignItems: "center", zIndex: 1100 }}>
        <div style={{ background: "#111", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "var(--radius-lg)", padding: "24px", width: "480px", maxWidth: "90%", display: "flex", flexDirection: "column", gap: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid rgba(255,255,255,0.08)", paddingBottom: "12px" }}>
            <h3 style={{ color: "#fff", fontSize: "16px", fontWeight: "800", display: "flex", alignItems: "center", gap: "8px" }}>
              <span>📢</span> {currentAnnouncement.title}
            </h3>
            <button type="button" onClick={() => setShowDetailModal(false)} style={{ background: "transparent", border: "none", color: "rgba(255,255,255,0.4)", cursor: "pointer", fontSize: "16px" }}>✕</button>
          </div>
          <div style={{ color: "rgba(255,255,255,0.85)", fontSize: "13px", lineHeight: "1.6", whiteSpace: "pre-wrap", maxHeight: "250px", overflowY: "auto", paddingRight: "4px" }}>
            {currentAnnouncement.content}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: "12px", fontSize: "11px", color: "rgba(255,255,255,0.4)" }}>
            <span>发布于 {new Date(currentAnnouncement.created_at || '').toLocaleString()}</span>
            <Button type="button" variant="primary" onClick={() => setShowDetailModal(false)} style={{ padding: "6px 16px", fontSize: "12px" }}>
              我知道了
            </Button>
          </div>
        </div>
      </div>
    );
  };

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
      { opacity: 1, y: 0, scale: 1, duration: dur, ease: "power2.out", clearProps: "transform" }
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
          {renderAnnouncementBanner()}
          {children}
        </div>
        {renderDetailModal()}
        {renderPopupAnnouncement()}
      </div>
    );
  }

  // ─── DESKTOP layout (original, unchanged) ───
  return (
    <div ref={shellRef} className="app-shell">
      <Sidebar activePage={activePage} onNavigate={onNavigate} onLogout={onLogout} userRole={userRole} generationLimit={generationLimit} />
      <div className="app-main">
        <Header onNewAnalysis={() => onNavigate("new")} onHistory={() => onNavigate("history")} />
        {renderAnnouncementBanner()}
        {children}
      </div>
      {renderDetailModal()}
      {renderPopupAnnouncement()}
    </div>
  );
}
