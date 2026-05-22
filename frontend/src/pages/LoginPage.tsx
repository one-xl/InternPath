import { useEffect, useState } from "react";
import { Button } from "../components/ui/Button";

interface LoginPageProps {
  onLoginSuccess: (user: { id: number; username: string }) => void;
}

export function LoginPage({ onLoginSuccess }: LoginPageProps) {
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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    // Frontend validations
    if (!email.trim() || !password) {
      setError("请填写完整的邮箱和密码。");
      return;
    }

    if (!validateEmail(email)) {
      setError("请输入有效的电子邮箱地址。");
      return;
    }

    if (password.length < 8) {
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
      onLoginSuccess({
        id: user.id,
        username: user.username,
      });
    } catch (err: any) {
      setError(err.message || "连接服务器失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page-container">
      {/* Decorative gradient glowing spheres */}
      <div className="glow-sphere sphere-1"></div>
      <div className="glow-sphere sphere-2"></div>

      <div className="login-glass-card">
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
            <label className="field animate-fadeIn">
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
            <label className="field animate-fadeIn">
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
