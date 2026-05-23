import React, { Component, ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div className="card" style={{ padding: "24px", margin: "20px", background: "rgba(239, 68, 68, 0.08)", border: "1px solid rgba(239, 68, 68, 0.2)", borderRadius: "12px", color: "#fff" }}>
            <h3 style={{ color: "rgba(239, 68, 68, 0.95)", marginBottom: "8px" }}>工作台页面渲染出错</h3>
            <p style={{ fontSize: "14px", opacity: 0.9, marginBottom: "16px" }}>
              组件在渲染时遇到了一个错误。这可能是由于服务器返回的历史记录或本地缓存数据格式不完整导致的。
            </p>
            <div style={{ background: "rgba(0, 0, 0, 0.3)", padding: "12px", borderRadius: "6px", fontFamily: "monospace", fontSize: "12px", overflowX: "auto", whiteSpace: "pre-wrap", color: "rgba(239, 68, 68, 0.85)", marginBottom: "16px" }}>
              {this.state.error?.stack || this.state.error?.toString()}
            </div>
            <div style={{ display: "flex", gap: "12px" }}>
              <button
                onClick={() => {
                  window.location.reload();
                }}
                style={{ padding: "8px 16px", background: "rgba(255, 255, 255, 0.15)", border: "1px solid rgba(255, 255, 255, 0.2)", borderRadius: "6px", color: "#fff", cursor: "pointer", fontSize: "13px", fontWeight: 600 }}
              >
                刷新页面
              </button>
              <button
                onClick={() => {
                  if (confirm("这会清除你的本地 UI 配置缓存（如主题、部分未保存的临时草稿），确定吗？")) {
                    localStorage.clear();
                    window.location.reload();
                  }
                }}
                style={{ padding: "8px 16px", background: "rgba(239, 68, 68, 0.2)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: "6px", color: "#ff8b8b", cursor: "pointer", fontSize: "13px", fontWeight: 600 }}
              >
                清除本地缓存
              </button>
            </div>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
