import { useState } from "react";
import type { ResumeAdvice } from "../../types/analysis";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

const priorityLabel = {
  high: "必须改",
  medium: "推荐优化",
  low: "锦上添花",
};

const priorityTone = {
  high: "danger",
  medium: "warning",
  low: "neutral",
} as const;

export function formatIssue(issue: string): string {
  if (!issue) return "";
  let clean = issue;
  // Remove [evidence_insufficient]
  clean = clean.replace(/\[evidence_insufficient\]/gi, "");
  // Remove any 【...】 bracket headers like 【项目经历/工作经历】
  clean = clean.replace(/【[^】]+】/g, "");
  // Remove citation failure warning suffix
  clean = clean.replace(/\(模型返回的证据引用无效或缺少有效证据\)/g, "");
  return clean.replace(/\s+/g, " ").trim();
}

export function formatSuggestion(suggestion: string): string {
  if (!suggestion) return "";
  let clean = suggestion;
  // Remove fallback error warning prefix
  clean = clean.replace(/模型返回的证据引用无效或缺少有效证据，原建议暂无法关联有效简历片段。原建议：/g, "");
  return clean.trim();
}

function AdviceItem({ item, onShowEvidence }: { item: ResumeAdvice; onShowEvidence?: (chunkIds: string[]) => void }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(item.example);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <article className="advice-card">
      <div className="advice-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <Badge tone={priorityTone[item.priority]}>{priorityLabel[item.priority]}</Badge>
          <span className="advice-impact">预计收益：{item.impact}</span>
          {item.basedOnChunkIds && item.basedOnChunkIds.length > 0 && onShowEvidence && (
            <button
              type="button"
              onClick={() => onShowEvidence(item.basedOnChunkIds || [])}
              style={{
                background: "rgba(16, 185, 129, 0.12)",
                color: "#10b981",
                border: "1px solid rgba(16, 185, 129, 0.25)",
                borderRadius: "12px",
                padding: "2px 10px",
                fontSize: "11px",
                fontWeight: "600",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                transition: "all 0.2s ease"
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.background = "rgba(16, 185, 129, 0.2)";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.background = "rgba(16, 185, 129, 0.12)";
              }}
            >
              📄 证据链
            </button>
          )}
        </div>
      </div>
      <div className="advice-body">
        <div className="advice-issue">
          <strong>问题与分析</strong>
          <p>{formatIssue(item.issue)}</p>
        </div>
        <div className="advice-suggestion">
          <strong>改造建议</strong>
          <p>{formatSuggestion(item.suggestion)}</p>
        </div>
        {item.example && (
          <div className="advice-example">
            <div className="example-header">
              <strong>优化后示例表达</strong>
              <button
                type="button"
                className={`copy-btn ${copied ? "copied" : ""}`}
                onClick={handleCopy}
                title="复制示例"
              >
                {copied ? (
                  <>
                    <svg viewBox="0 0 20 20" fill="currentColor" width="13" height="13">
                      <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clipRule="evenodd" />
                    </svg>
                    <span>已复制</span>
                  </>
                ) : (
                  <>
                    <svg viewBox="0 0 20 20" fill="currentColor" width="13" height="13">
                      <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12a1.5 1.5 0 01.439 1.061V16.5A1.5 1.5 0 0115.5 18h-7A1.5 1.5 0 017 16.5v-13z" />
                      <path d="M5 5.5A1.5 1.5 0 003.5 7v10.5A1.5 1.5 0 005 19h7a1.5 1.5 0 001.5-1.5V17H5V5.5z" />
                    </svg>
                    <span>复制示例</span>
                  </>
                )}
              </button>
            </div>
            <blockquote>{item.example}</blockquote>
          </div>
        )}
      </div>
    </article>
  );
}

function AdviceSection({ title, items, onShowEvidence }: { title: string; items: ResumeAdvice[]; onShowEvidence?: (chunkIds: string[]) => void }) {
  if (!items.length) return null;
  return (
    <div className="advice-section">
      <h3>{title}</h3>
      {items.map((item) => (
        <AdviceItem key={item.id} item={item} onShowEvidence={onShowEvidence} />
      ))}
    </div>
  );
}

export function ResumeAdviceList({ advice, onShowEvidence }: { advice: ResumeAdvice[]; onShowEvidence?: (chunkIds: string[]) => void }) {
  return (
    <Card title="简历改造建议" description="按优先级分级处理，直接在下面对比修改前后的表述细节，支持一键复制。">
      <AdviceSection title="必须改 (高优先级)" items={advice.filter((item) => item.priority === "high")} onShowEvidence={onShowEvidence} />
      <AdviceSection title="推荐优化 (中优先级)" items={advice.filter((item) => item.priority === "medium")} onShowEvidence={onShowEvidence} />
      <AdviceSection title="锦上添花 (低优先级)" items={advice.filter((item) => item.priority === "low")} onShowEvidence={onShowEvidence} />
    </Card>
  );
}
