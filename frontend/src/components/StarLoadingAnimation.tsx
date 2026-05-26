import { useRef, useEffect, useState } from "react";
import { gsap } from "gsap";

interface StarLoadingAnimationProps {
  isLoading: boolean;
  loadingText?: string;
}

const STAR_LETTERS = [
  { letter: "S", label: "Situation", color: "#b45309" },
  { letter: "T", label: "Task", color: "#78350f" },
  { letter: "A", label: "Action", color: "#92400e" },
  { letter: "R", label: "Result", color: "#a16207" },
];

const PROGRESS_TIPS = [
  "正在理解项目上下文...",
  "正在拆解 STAR 结构...",
  "正在分析背景与任务...",
  "正在梳理行动细节...",
  "正在提炼量化成果...",
  "正在润色表达风格...",
  "正在打磨简历话术...",
  "即将完成，请稍候...",
];

export function StarLoadingAnimation({ isLoading, loadingText }: StarLoadingAnimationProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<gsap.core.Timeline | null>(null);
  const tipIndexRef = useRef(0);
  const [currentTip, setCurrentTip] = useState(PROGRESS_TIPS[0]);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  // Main animation timeline
  useEffect(() => {
    if (!isLoading || !containerRef.current) {
      if (timelineRef.current) {
        timelineRef.current.kill();
        timelineRef.current = null;
      }
      return;
    }

    const letters = containerRef.current.querySelectorAll(".star-anim-letter");
    const glow = containerRef.current.querySelectorAll(".star-anim-glow");
    const underlines = containerRef.current.querySelectorAll(".star-anim-underline");

    // Reset
    gsap.set(letters, { scale: 1, y: 0, opacity: 0.4 });
    gsap.set(glow, { opacity: 0, scale: 0.5 });
    gsap.set(underlines, { scaleX: 0 });

    const tl = gsap.timeline({ repeat: -1 });

    // Entrance - letters fly in
    tl.to(letters, {
      opacity: 1,
      y: 0,
      stagger: 0.12,
      duration: 0.5,
      ease: "back.out(1.7)",
    });

    // Sequential pulse for each letter
    STAR_LETTERS.forEach((_, i) => {
      tl.to(letters[i], {
        scale: 1.3,
        duration: 0.35,
        ease: "power2.out",
      }, `pulse_${i}`)
      .to(glow[i], {
        opacity: 0.6,
        scale: 1.2,
        duration: 0.35,
        ease: "power2.out",
      }, `pulse_${i}`)
      .to(underlines[i], {
        scaleX: 1,
        duration: 0.3,
        ease: "power2.out",
      }, `pulse_${i}+=0.1`)
      .to(letters[i], {
        scale: 1,
        duration: 0.3,
        ease: "power2.inOut",
      }, `pulse_${i}+=0.35`)
      .to(glow[i], {
        opacity: 0,
        scale: 0.5,
        duration: 0.3,
        ease: "power2.inOut",
      }, `pulse_${i}+=0.35`);
    });

    // Breathing pause
    tl.to(letters, {
      opacity: 0.5,
      duration: 0.6,
      ease: "power1.inOut",
    }, "+=0.3");

    // Reset underlines for next cycle
    tl.to(underlines, {
      scaleX: 0,
      duration: 0.3,
      ease: "power2.in",
    }, "-=0.3");

    timelineRef.current = tl;

    return () => {
      tl.kill();
    };
  }, [isLoading]);

  // Rotating tips
  useEffect(() => {
    if (!isLoading) {
      tipIndexRef.current = 0;
      setCurrentTip(PROGRESS_TIPS[0]);
      return;
    }

    const interval = setInterval(() => {
      tipIndexRef.current = (tipIndexRef.current + 1) % PROGRESS_TIPS.length;
      setCurrentTip(PROGRESS_TIPS[tipIndexRef.current]);
    }, 3000);

    return () => clearInterval(interval);
  }, [isLoading]);

  // Hover interaction
  const handleLetterHover = (idx: number) => {
    setHoveredIdx(idx);
    if (!containerRef.current) return;
    const letter = containerRef.current.querySelectorAll(".star-anim-letter")[idx];
    if (letter) {
      gsap.to(letter, {
        y: -12,
        scale: 1.4,
        duration: 0.25,
        ease: "back.out(2)",
        overwrite: "auto",
      });
    }
  };

  const handleLetterLeave = (idx: number) => {
    setHoveredIdx(null);
    if (!containerRef.current) return;
    const letter = containerRef.current.querySelectorAll(".star-anim-letter")[idx];
    if (letter) {
      gsap.to(letter, {
        y: 0,
        scale: 1,
        duration: 0.3,
        ease: "power2.out",
        overwrite: "auto",
      });
    }
  };

  if (!isLoading) return null;

  return (
    <div ref={containerRef} className="star-loading-container">
      <style>{`
        .star-loading-container {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 48px 24px;
          gap: 28px;
          min-height: 280px;
        }
        .star-loading-letters {
          display: flex;
          gap: 24px;
          align-items: flex-end;
        }
        .star-letter-group {
          display: flex;
          flex-direction: column;
          align-items: center;
          cursor: pointer;
          user-select: none;
          position: relative;
        }
        .star-anim-glow {
          position: absolute;
          width: 56px;
          height: 56px;
          border-radius: 50%;
          top: -4px;
          pointer-events: none;
          filter: blur(12px);
        }
        .star-anim-letter {
          font-size: 42px;
          font-weight: 900;
          font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
          width: 56px;
          height: 56px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 14px;
          background: var(--surface);
          border: 2px solid var(--line-strong);
          position: relative;
          z-index: 2;
          transition: border-color 0.2s ease;
        }
        .star-letter-group:hover .star-anim-letter {
          border-color: var(--accent);
        }
        .star-anim-underline {
          height: 3px;
          width: 40px;
          border-radius: 2px;
          margin-top: 6px;
          transform-origin: center;
        }
        .star-letter-label {
          font-size: 10px;
          font-weight: 600;
          color: var(--subtle);
          margin-top: 4px;
          letter-spacing: 0.5px;
        }
        .star-loading-tip {
          font-size: 13px;
          color: var(--muted);
          text-align: center;
          min-height: 20px;
          animation: starTipFade 3s ease-in-out infinite;
        }
        @keyframes starTipFade {
          0%, 100% { opacity: 0.7; }
          50% { opacity: 1; }
        }
        .star-loading-dots {
          display: flex;
          gap: 6px;
          align-items: center;
        }
        .star-loading-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--accent);
          animation: starDotBounce 1.4s ease-in-out infinite;
        }
        .star-loading-dot:nth-child(2) { animation-delay: 0.2s; }
        .star-loading-dot:nth-child(3) { animation-delay: 0.4s; }
        @keyframes starDotBounce {
          0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
          40% { opacity: 1; transform: scale(1.2); }
        }
      `}</style>

      <div className="star-loading-letters">
        {STAR_LETTERS.map((item, idx) => (
          <div
            key={item.letter}
            className="star-letter-group"
            onMouseEnter={() => handleLetterHover(idx)}
            onMouseLeave={() => handleLetterLeave(idx)}
          >
            <div
              className="star-anim-glow"
              style={{ background: item.color }}
            />
            <div
              className="star-anim-letter"
              style={{ color: hoveredIdx === idx ? item.color : "var(--text)" }}
            >
              {item.letter}
            </div>
            <div
              className="star-anim-underline"
              style={{ background: item.color }}
            />
            <span className="star-letter-label">{item.label}</span>
          </div>
        ))}
      </div>

      <div className="star-loading-dots">
        <span className="star-loading-dot" />
        <span className="star-loading-dot" />
        <span className="star-loading-dot" />
      </div>

      <div className="star-loading-tip">
        {loadingText || currentTip}
      </div>
    </div>
  );
}
