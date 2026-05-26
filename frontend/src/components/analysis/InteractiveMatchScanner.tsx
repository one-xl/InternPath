import React, { useRef, useMemo } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import type { AnalysisRunStatus } from "../../types/analysis";

// Register the GSAP React plugin
gsap.registerPlugin(useGSAP);

interface InteractiveMatchScannerProps {
  status: AnalysisRunStatus;
  subState?: "checking_constraints" | "deep_analyzing" | "generating_advice" | "building_roadmap" | "completed" | string;
  subProgress?: number;
}

interface FloatingNode {
  id: number;
  label: string;
  x: string;
  y: string;
  baseColor: string;
  activeColor: string;
  scale: number;
}

export function InteractiveMatchScanner({ status, subState, subProgress = 0 }: InteractiveMatchScannerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const beamRef = useRef<HTMLDivElement>(null);
  const nodesContainerRef = useRef<HTMLDivElement>(null);

  // Dynamic state configurations based on active sub-stage
  const theme = useMemo(() => {
    switch (subState) {
      case "checking_constraints":
        return {
          glowColor: "rgba(59, 130, 246, 0.4)", // Blue
          activeBg: "var(--accent-glow)",
          textColor: "#3b82f6",
          pulseDuration: 1.5,
          beamColor: "linear-gradient(to bottom, transparent, #3b82f6, transparent)",
          beamSpeed: 2.2,
          particleSpeedScale: 1.0,
        };
      case "deep_analyzing":
        return {
          glowColor: "rgba(168, 85, 247, 0.5)", // Violet
          activeBg: "rgba(168, 85, 247, 0.15)",
          textColor: "#a855f7",
          pulseDuration: 0.8,
          beamColor: "linear-gradient(to bottom, transparent, #a855f7, transparent)",
          beamSpeed: 1.2, // Very fast and active
          particleSpeedScale: 2.2,
        };
      case "generating_advice":
        return {
          glowColor: "rgba(245, 158, 11, 0.45)", // Amber/Gold
          activeBg: "rgba(245, 158, 11, 0.15)",
          textColor: "#f59e0b",
          pulseDuration: 1.2,
          beamColor: "linear-gradient(to bottom, transparent, #f59e0b, transparent)",
          beamSpeed: 1.8,
          particleSpeedScale: 1.5,
        };
      case "building_roadmap":
        return {
          glowColor: "rgba(20, 184, 166, 0.45)", // Teal
          activeBg: "rgba(20, 184, 166, 0.15)",
          textColor: "#14b8a6",
          pulseDuration: 1.4,
          beamColor: "linear-gradient(to bottom, transparent, #14b8a6, transparent)",
          beamSpeed: 2.0,
          particleSpeedScale: 1.2,
        };
      case "completed":
      case "success":
        return {
          glowColor: "rgba(16, 185, 129, 0.4)", // Green
          activeBg: "rgba(16, 185, 129, 0.1)",
          textColor: "#10b981",
          pulseDuration: 2.0,
          beamColor: "linear-gradient(to bottom, transparent, #10b981, transparent)",
          beamSpeed: 4.0,
          particleSpeedScale: 0.5,
        };
      default:
        return {
          glowColor: "rgba(99, 102, 241, 0.3)", // Default Indigo
          activeBg: "rgba(99, 102, 241, 0.1)",
          textColor: "#6366f1",
          pulseDuration: 1.8,
          beamColor: "linear-gradient(to bottom, transparent, #6366f1, transparent)",
          beamSpeed: 2.5,
          particleSpeedScale: 1.0,
        };
    }
  }, [subState]);

  // Static floating nodes definitions
  const floatingNodes: FloatingNode[] = useMemo(() => [
    { id: 1, label: "React", x: "25%", y: "25%", baseColor: "#61dafb", activeColor: "#00d2ff", scale: 1.0 },
    { id: 2, label: "TypeScript", x: "32%", y: "65%", baseColor: "#3178c6", activeColor: "#00a2ff", scale: 0.95 },
    { id: 3, label: "Python", x: "42%", y: "15%", baseColor: "#3776ab", activeColor: "#ffd43b", scale: 1.05 },
    { id: 4, label: "SQL", x: "50%", y: "75%", baseColor: "#00758f", activeColor: "#00f0ff", scale: 0.9 },
    { id: 5, label: "System Design", x: "58%", y: "28%", baseColor: "#ff4f00", activeColor: "#ff7f00", scale: 1.1 },
    { id: 6, label: "RAG Engine", x: "68%", y: "62%", baseColor: "#a855f7", activeColor: "#d8b4fe", scale: 1.15 },
    { id: 7, label: "Algorithms", x: "75%", y: "20%", baseColor: "#10b981", activeColor: "#34d399", scale: 0.95 },
  ], []);

  // GSAP animations implementation
  useGSAP(
    () => {
      // 1. Loop sweep scanning beam back and forth
      if (beamRef.current) {
        gsap.killTweensOf(beamRef.current);
        gsap.to(beamRef.current, {
          left: "82%",
          duration: theme.beamSpeed,
          yoyo: true,
          repeat: -1,
          ease: "power1.inOut",
        });
      }

      // 2. Animate floating/drifting movement for each node bubble
      const children = nodesContainerRef.current?.childNodes;
      if (children) {
        children.forEach((child, index) => {
          gsap.killTweensOf(child);
          const element = child as HTMLElement;
          // Random offset limits for drifting
          const xMax = 12 + (index % 3) * 6;
          const yMax = 10 + (index % 2) * 8;
          const duration = 4 + (index % 4) * 1.5;

          // Infinite drifting animation
          gsap.to(element, {
            x: `+=${xMax}`,
            y: `+=${yMax}`,
            duration: duration / theme.particleSpeedScale,
            yoyo: true,
            repeat: -1,
            ease: "sine.inOut",
            delay: index * 0.3,
          });

          // Soft ambient scaling
          gsap.to(element, {
            scale: "*=1.05",
            duration: 2 + (index % 3) * 0.7,
            yoyo: true,
            repeat: -1,
            ease: "sine.inOut",
            delay: index * 0.5,
          });
        });
      }

      // 3. Ambient node pulse animations (pulse rings on Resume & JD nodes)
      gsap.to(".scanner-node-pulse-ring", {
        scale: 1.8,
        opacity: 0,
        duration: theme.pulseDuration,
        repeat: -1,
        ease: "power1.out",
        stagger: 0.4,
      });
    },
    { dependencies: [theme, floatingNodes], scope: containerRef }
  );

  // Micro-interaction handlers for interactive nodes
  const handleMouseEnter = (event: React.MouseEvent<HTMLDivElement>) => {
    gsap.to(event.currentTarget, {
      scale: 1.3,
      boxShadow: `0 8px 24px ${theme.glowColor}, 0 0 16px ${theme.textColor}`,
      borderColor: theme.textColor,
      duration: 0.3,
      ease: "back.out(1.7)",
      overwrite: "auto",
    });
  };

  const handleMouseLeave = (event: React.MouseEvent<HTMLDivElement>) => {
    const scale = Number(event.currentTarget.getAttribute("data-base-scale") || 1);
    gsap.to(event.currentTarget, {
      scale: scale,
      boxShadow: "0 4px 12px rgba(0,0,0,0.1), 0 0 0px transparent",
      borderColor: "var(--line)",
      duration: 0.4,
      ease: "power2.out",
      overwrite: "auto",
    });
  };

  const handleNodeClick = (event: React.MouseEvent<HTMLDivElement>) => {
    // Fun kinetic trigger: quick spin and pop bounce
    gsap.to(event.currentTarget, {
      rotation: "+=360",
      y: "-=12",
      yoyo: true,
      repeat: 1,
      duration: 0.5,
      ease: "back.out(1.5)",
    });
  };

  return (
    <div 
      className="interactive-match-scanner-container" 
      ref={containerRef}
      style={{ "--glow-color": theme.glowColor } as React.CSSProperties}
    >
      {/* Background Grid & Ambient Glows */}
      <div className="scanner-bg-grid" />
      <div className="scanner-glow-overlay" />

      {/* Main Matching Pipeline Node Visualization */}
      <div className="scanner-pipeline-track">
        {/* Left Node: Resume */}
        <div className="scanner-terminal-node left-node">
          <div className="scanner-node-pulse-ring ring-1" />
          <div className="scanner-node-pulse-ring ring-2" />
          <div className="scanner-node-core">
            <svg className="node-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span className="node-label">RESUME</span>
          </div>
        </div>

        {/* Center Tunnel / RAG Quantum Bridge */}
        <div className="scanner-quantum-bridge">
          {/* Glowing laser bridge line */}
          <div className="quantum-bridge-line" />
          
          {/* Interactive Floating Nodes Layer */}
          <div className="floating-nodes-layer" ref={nodesContainerRef}>
            {floatingNodes.map((node) => (
              <div
                key={node.id}
                className="floating-skill-bubble"
                style={{
                  left: node.x,
                  top: node.y,
                  transform: `scale(${node.scale})`,
                  "--node-base-color": node.baseColor,
                  "--node-active-color": node.activeColor,
                } as React.CSSProperties}
                data-base-scale={node.scale}
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
                onClick={handleNodeClick}
              >
                <span className="bubble-bullet" style={{ backgroundColor: node.baseColor }} />
                <span className="bubble-text">{node.label}</span>
              </div>
            ))}
          </div>

          {/* Sweeping Laser Scanner Beam */}
          <div className="scanner-beam-track">
            <div className="scanner-laser-beam" ref={beamRef} style={{ background: theme.beamColor }} />
          </div>
        </div>

        {/* Right Node: Job Description Target */}
        <div className="scanner-terminal-node right-node">
          <div className="scanner-node-pulse-ring ring-1" />
          <div className="scanner-node-pulse-ring ring-2" />
          <div className="scanner-node-core">
            <svg className="node-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <span className="node-label">JOB TARGET</span>
          </div>
        </div>
      </div>

      {/* Embedded Substate Indicator & Progress HUD */}
      {status === "analyzing" && (
        <div className="scanner-hud-overlay">
          <div className="hud-metric-row">
            <span className="hud-metric-label">PIPELINE ANALYSIS STATUS</span>
            <span className="hud-metric-value blink-text" style={{ color: theme.textColor }}>
              {subState === "checking_constraints" && "CHECKING CORE ELIGIBILITY"}
              {subState === "deep_analyzing" && "RUNNING MULTI-ROUND SKILL CROSS MATCH"}
              {subState === "generating_advice" && "COMPUTING RESUME SUGGESTIONS"}
              {subState === "building_roadmap" && "CONSTRUCTING ROADMAP SUGGESTIONS"}
              {!subState && "RUNNING REASONING PIPELINE"}
            </span>
          </div>
          <div className="hud-progress-container">
            <div className="hud-progress-bg">
              <div 
                className="hud-progress-fill" 
                style={{ 
                  width: `${subProgress}%`,
                  backgroundColor: theme.textColor,
                  boxShadow: `0 0 8px ${theme.textColor}`
                }} 
              />
            </div>
            <span className="hud-progress-text font-mono" style={{ color: theme.textColor }}>
              {subProgress}%
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
