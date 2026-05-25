import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui/Button";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(useGSAP);

interface LoginPageProps {
  onLoginSuccess: (user: { id: any; username: string; role?: string; generation_limit?: number }) => void;
}

export function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const prevHeightRef = useRef<number | null>(null);
  const firstRender = useRef(true);
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [codeMessage, setCodeMessage] = useState<string | null>(null);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const [sendingCode, setSendingCode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  // 1. Initial entrance animation
  useGSAP(() => {
    // Animate background glow spheres floating in
    gsap.fromTo(".glow-sphere", 
      { scale: 0.8, opacity: 0 }, 
      { scale: 1, opacity: 0.35, duration: 1.5, ease: "power2.out", stagger: 0.3 }
    );

    // Initial staggered intro animation timeline for card and elements
    const tl = gsap.timeline();
    tl.fromTo(cardRef.current, 
      { y: 50, scale: 0.95, opacity: 0 }, 
      { y: 0, scale: 1, opacity: 1, duration: 0.9, ease: "power3.out" }
    );
    
    tl.fromTo(".login-header > *", 
      { y: 15, opacity: 0 }, 
      { y: 0, opacity: 1, duration: 0.5, stagger: 0.1, ease: "power2.out" },
      "-=0.5" // overlap with card animation
    );

    tl.fromTo(".login-form .field", 
      { x: -20, opacity: 0 }, 
      { x: 0, opacity: 1, duration: 0.45, stagger: 0.08, ease: "power2.out" },
      "-=0.3"
    );

    tl.fromTo(".login-submit-btn", 
      { y: 15, opacity: 0 }, 
      { y: 0, opacity: 1, duration: 0.4, ease: "power2.out" },
      "-=0.2"
    );

    tl.fromTo([".login-footer-actions", ".login-security-notice"], 
      { y: 10, opacity: 0 }, 
      { y: 0, opacity: 1, duration: 0.4, stagger: 0.1, ease: "power2.out" },
      "-=0.15"
    );
  }, { scope: containerRef });

  // 2. Smooth height and field transitions when switching modes
  useGSAP(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }

    const card = cardRef.current;
    if (!card) return;

    const oldHeight = prevHeightRef.current;
    // Set overflow hidden to prevent scrollbars or content sticking out during animation
    card.style.overflow = "hidden";
    
    // Force DOM layout calculation to get the new natural height of the card
    const newHeight = card.clientHeight;

    if (oldHeight && oldHeight !== newHeight) {
      gsap.fromTo(card, 
        { height: oldHeight }, 
        { 
          height: newHeight, 
          duration: 0.45, 
          ease: "power3.out", 
          clearProps: "height",
          onComplete: () => {
            card.style.overflow = ""; // reset overflow
          }
        }
      );
    }

    // Animate the appearance of the new fields if switching to Register mode
    if (!isLogin) {
      gsap.fromTo(".new-field", 
        { opacity: 0, y: -15, scale: 0.95 }, 
        { opacity: 1, y: 0, scale: 1, duration: 0.4, stagger: 0.08, ease: "power2.out" }
      );
    }
  }, { dependencies: [isLogin], scope: containerRef });

  // Email format validation
  function validateEmail(val: string) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val);
  }

  async function handleSendCode() {
    setError(null);
    setCodeMessage(null);
    if (!email.trim()) {
      setError("请先填写邮箱。");
      return;
    }
    if (!validateEmail(email)) {
      setError("请输入有效的电子邮箱地址。");
      return;
    }

    setSendingCode(true);
    try {
      const response = await fetch("/api/auth/send-email-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: email }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "验证码发送失败，请稍后重试。");
      }
      setCodeCooldown(60);
      setCodeMessage(data.devCode ? `${data.message} 开发验证码：${data.devCode}` : data.message || "验证码已发送，请查收邮箱。");
    } catch (err: any) {
      setError(err.message || "验证码发送失败，请稍后重试。");
    } finally {
      setSendingCode(false);
    }
  }

  useEffect(() => {
    if (codeCooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCodeCooldown((current) => (current > 0 ? current - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [codeCooldown]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = container.clientWidth);
    let height = (canvas.height = container.clientHeight);

    const handleResize = () => {
      if (!container || !canvas) return;
      width = canvas.width = container.clientWidth;
      height = canvas.height = container.clientHeight;
    };
    window.addEventListener("resize", handleResize);

    interface Particle {
      angle: number;
      angularSpeed: number;
      baseRadius: number;
      currentRadius: number;
      radiusOffsetSpeed: number;
      radiusOffsetTime: number;
      size: number;
      color: string;
      alpha: number;
      pulseSpeed: number;
      pulseTime: number;
      ease: number;
      cx: number;
      cy: number;
    }

    let particles: Particle[] = [];
    const maxParticles = 60; // Reduced from 140 to heavily optimize canvas rendering performance

    const getSpotifyGreenVariation = () => {
      // Vary green hue between 120 (yellowish-green) and 160 (bluish-green)
      const hue = Math.floor(Math.random() * 41) + 120;
      const saturation = Math.floor(Math.random() * 21) + 70;
      const lightness = Math.floor(Math.random() * 21) + 40;
      return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    };

    const getRandomColor = () => {
      // Completely random vibrant neon hue (0 to 360)
      const hue = Math.floor(Math.random() * 360);
      const saturation = Math.floor(Math.random() * 21) + 80; // High saturation
      const lightness = Math.floor(Math.random() * 21) + 50; // High brightness
      return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    };

    // Pre-initialize orbital particles
    for (let i = 0; i < maxParticles; i++) {
      // Radial ring between 20px (inner) and 50px (outer) to spread them out while maintaining hollow center
      const baseRadius = Math.random() * 30 + 20;

      // Assign ease factors to distribute response latency across 3 distinct cohorts:
      // - 25% core tight followers (ease: 0.18 ~ 0.26)
      // - 35% mid-tail transition particles (ease: 0.10 ~ 0.17)
      // - 40% long-tail lagging particles (ease: 0.03 ~ 0.09)
      let ease = 0.15;
      const rand = Math.random();
      if (rand < 0.25) {
        ease = Math.random() * 0.08 + 0.18;
      } else if (rand < 0.6) {
        ease = Math.random() * 0.07 + 0.10;
      } else {
        ease = Math.random() * 0.06 + 0.03;
      }

      // 15% of the particles will have completely random colors (accents), 85% will remain Spotify greens
      const isAccentParticle = Math.random() < 0.15;
      const color = isAccentParticle ? getRandomColor() : getSpotifyGreenVariation();
      
      particles.push({
        angle: Math.random() * Math.PI * 2,
        angularSpeed: (Math.random() * 0.018 + 0.008) * (Math.random() > 0.5 ? 1 : -1),
        baseRadius: baseRadius,
        currentRadius: baseRadius,
        radiusOffsetSpeed: Math.random() * 0.03 + 0.01,
        radiusOffsetTime: Math.random() * Math.PI * 2,
        size: Math.random() * 3.0 + 2.0, // Increased size (2.0px ~ 5.0px) for visibility with fewer particles
        color: color,
        alpha: Math.random() * 0.4 + 0.5, // Base alpha 0.5 ~ 0.9
        pulseSpeed: Math.random() * 0.04 + 0.02,
        pulseTime: Math.random() * Math.PI * 2,
        ease: ease,
        cx: 0,
        cy: 0
      });
    }

    const mouse = { x: -1000, y: -1000 };
    let hasMoved = false;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;

      if (!hasMoved) {
        // Initialize particle orbit centers immediately to mouse coordinates on first movement
        for (let i = 0; i < particles.length; i++) {
          particles[i].cx = mouse.x;
          particles[i].cy = mouse.y;
        }
        hasMoved = true;
      }
    };

    container.addEventListener("mousemove", handleMouseMove);

    const animate = () => {
      ctx.clearRect(0, 0, width, height);

      if (hasMoved) {
        for (let i = 0; i < particles.length; i++) {
          const p = particles[i];

          // Rotate
          p.angle += p.angularSpeed;

          // Gentle breathing variation in radius
          p.radiusOffsetTime += p.radiusOffsetSpeed;
          const currentRadius = p.baseRadius + Math.sin(p.radiusOffsetTime) * 5;

          // Breath fade-in/out
          p.pulseTime += p.pulseSpeed;
          const baseAlpha = p.alpha * (0.6 + 0.4 * Math.sin(p.pulseTime));

          // Interpolate orbit center towards mouse coordinate with its assigned ease factor
          p.cx += (mouse.x - p.cx) * p.ease;
          p.cy += (mouse.y - p.cy) * p.ease;

          // Performance: Calculate lag using Math.sqrt to avoid Math.hypot function call overhead
          const dx = mouse.x - p.cx;
          const dy = mouse.y - p.cy;
          const lag = Math.sqrt(dx * dx + dy * dy);
          const maxLag = 110; // Max distance for full tapering effect
          const lagRatio = Math.min(1, lag / maxLag);

          // Taper orbit radius so trailing particles converge to a thin tail line
          const renderRadius = currentRadius * (1 - lagRatio * 0.85);

          // Taper size and opacity as particle lags further behind
          const renderSize = Math.max(0.6, p.size * (1 - lagRatio * 0.65));
          const renderAlpha = baseAlpha * (1 - lagRatio * 0.82);

          // Calculate coordinates relative to the lagging orbit center and tapered radius
          const x = p.cx + renderRadius * Math.cos(p.angle);
          const y = p.cy + renderRadius * Math.sin(p.angle);

          // Extreme Performance Optimization:
          // 1. Avoid shadowBlur & shadowColor: Canvas shadow filters are very heavy on CPU/GPU and trigger lag.
          //    Instead, we draw two concentric vector circles (outer faint aura + inner solid core) which GPUs draw instantly.
          // 2. Avoid save() & restore() within the loop: Modifying canvas state stacks 60 times/frame causes lag.
          //    Instead, we directly change globalAlpha and fillStyle, resetting globalAlpha once after the loop.
          
          // Pass 1: Draw outer soft glow aura
          ctx.globalAlpha = renderAlpha * 0.28;
          ctx.fillStyle = p.color;
          ctx.beginPath();
          ctx.arc(x, y, renderSize * 2.3, 0, Math.PI * 2);
          ctx.fill();

          // Pass 2: Draw solid inner core
          ctx.globalAlpha = renderAlpha;
          ctx.beginPath();
          ctx.arc(x, y, renderSize, 0, Math.PI * 2);
          ctx.fill();
        }
        
        // Reset globalAlpha to default
        ctx.globalAlpha = 1.0;
      }

      animationFrameId = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      window.removeEventListener("resize", handleResize);
      container.removeEventListener("mousemove", handleMouseMove);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    // Frontend validations
    if (!email.trim() || !password) {
      setError("请填写完整的邮箱和密码。");
      return;
    }

    if (!isLogin && !validateEmail(email)) {
      setError("请输入有效的电子邮箱地址。");
      return;
    }

    if (!isLogin && password.length < 8) {
      setError("密码长度必须至少为 8 位。");
      return;
    }

    if (!isLogin && password !== confirmPassword) {
      setError("两次输入的密码不一致，请重新输入。");
      return;
    }

    if (!isLogin && !/^\d{6}$/.test(verificationCode.trim())) {
      setError("请输入 6 位邮箱验证码。");
      return;
    }

    setLoading(true);

    try {
      const url = isLogin ? "/api/auth/login" : "/api/auth/register";
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          username: email,
          password: password,
          verification_code: verificationCode.trim(),
        }),
      });

      if (!response.ok) {
        let errorMsg = isLogin ? "邮箱或密码错误，请重新输入。" : "注册失败，请稍后重试。";
        try {
          const resBody = await response.json();
          if (resBody && resBody.detail) {
            errorMsg = resBody.detail;
          }
        } catch {
          // Fallback to default
        }
        throw new Error(errorMsg);
      }

      const payload = await response.json();
      const user = payload.user ?? payload;
      
      // Google-style Exit transition: zoom, shrink, and fade out the card and background components
      const card = cardRef.current;
      const canvas = canvasRef.current;
      const spheres = document.querySelectorAll(".glow-sphere");
      
      const tl = gsap.timeline({
        onComplete: () => {
          onLoginSuccess({
            id: user.id,
            username: user.username,
            role: user.role,
            generation_limit: user.generation_limit,
          });
        }
      });
      
      if (card) {
        tl.to(card, { 
          y: -40, 
          scale: 0.94, 
          opacity: 0, 
          duration: 0.45, 
          ease: "power2.inOut" 
        });
      }
      if (spheres.length) {
        tl.to(spheres, { 
          scale: 0.8,
          opacity: 0, 
          duration: 0.35, 
          stagger: 0.05,
          ease: "power2.in" 
        }, "-=0.35");
      }
      if (canvas) {
        tl.to(canvas, { 
          opacity: 0, 
          duration: 0.35, 
          ease: "power2.in" 
        }, "-=0.35");
      }
    } catch (err: any) {
      setError(err.message || "连接服务器失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div ref={containerRef} className="login-page-container">
      {/* Interactive mouse-follower particle canvas */}
      <canvas
        ref={canvasRef}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
          zIndex: 1,
        }}
      />
      {/* Decorative gradient glowing spheres */}
      <div className="glow-sphere sphere-1"></div>
      <div className="glow-sphere sphere-2"></div>

      <div ref={cardRef} className="login-glass-card" style={{ zIndex: 2 }}>
        <div className="login-header">
          <div className="login-logo">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </svg>
            <strong>InternPath</strong>
          </div>
          <h2>{isLogin ? "登录求职决策台" : "注册新账号"}</h2>
          <p className="login-subtitle">
            {isLogin ? "进入你的私有求职决策空间，安全托管个人数据" : "创建一个全新的个人工作空间，开始理性求职决策"}
          </p>
        </div>

        {error && (
          <div className="login-error-alert animate-shake">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="login-form">
          <label className="field">
            <span className="field-label-text">邮箱</span>
            <div className="input-with-icon">
              <svg className="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                <polyline points="22,6 12,13 2,6" />
              </svg>
              <input
                type="email"
                placeholder="name@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading}
                required
                autoComplete="email"
              />
            </div>
          </label>

          <label className="field">
            <span className="field-label-text">密码</span>
            <div className="input-with-icon">
              <svg className="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <input
                type={showPassword ? "text" : "password"}
                placeholder="请输入密码（至少 8 位）"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
                required
                autoComplete={isLogin ? "current-password" : "new-password"}
              />
              <button
                type="button"
                className="password-toggle-btn"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
              >
                {showPassword ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
          </label>

          {!isLogin && (
            <label className="field new-field">
              <span className="field-label-text">确认密码</span>
              <div className="input-with-icon">
                <svg className="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
                <input
                  type={showPassword ? "text" : "password"}
                  placeholder="请再次输入密码进行确认"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={loading}
                  required
                  autoComplete="new-password"
                />
              </div>
            </label>
          )}

          {!isLogin && (
            <label className="field new-field">
              <span className="field-label-text">邮箱验证码</span>
              <div className="input-with-icon">
                <svg className="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a4 4 0 0 1-4 4H7l-4 4V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
                </svg>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  placeholder="输入 6 位验证码"
                  value={verificationCode}
                  onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  disabled={loading}
                  required
                  autoComplete="one-time-code"
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={handleSendCode}
                  disabled={loading || sendingCode || codeCooldown > 0}
                  style={{ width: "auto", minWidth: "92px", fontSize: "12px", padding: "0 10px" }}
                >
                  {sendingCode ? "发送中" : codeCooldown > 0 ? `${codeCooldown}s` : "发送验证码"}
                </button>
              </div>
              {codeMessage && <small style={{ color: "#22c55e", fontSize: "12px" }}>{codeMessage}</small>}
            </label>
          )}

          <Button
            type="submit"
            variant="primary"
            disabled={loading}
            className="login-submit-btn"
          >
            {loading ? "正在处理..." : isLogin ? "登录" : "注册并登录"}
          </Button>
        </form>

        <div className="login-footer-actions">
          <span>{isLogin ? "还没有账号？" : "已有账号？"}</span>
          <button
            type="button"
            className="toggle-mode-btn"
            onClick={() => {
              const card = cardRef.current;
              if (card) {
                prevHeightRef.current = card.clientHeight;
              }
              setIsLogin(!isLogin);
              setError(null);
              setPassword("");
              setConfirmPassword("");
              setVerificationCode("");
              setCodeMessage(null);
            }}
            disabled={loading}
          >
            {isLogin ? "立即注册" : "立即登录"}
          </button>
        </div>

        <div className="login-security-notice">
          <p>🔒 所有求职数据与 API 密钥均在服务器高强度加密存储，前端从不保存真实密钥。</p>
        </div>
      </div>
    </div>
  );
}
