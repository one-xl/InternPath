import { useState } from "react";
import type { ResumeChunk } from "../../types/resume";
import type { ResumeAdvice } from "../../types/analysis";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { formatIssue } from "../result/ResumeAdviceList";

interface ResumeChunkPreviewProps {
  chunks: ResumeChunk[];
  advice?: ResumeAdvice[];
  title?: string;
  description?: string;
  emptyText?: string;
  onGoToRewrite?: (adviceId: string) => void;
}

export function ResumeChunkPreview({
  chunks,
  advice = [],
  title = "本次分析参考的简历片段",
  description = "系统根据 JD 从你的简历中检索出最相关的经历片段，并基于这些内容生成投递决策和简历改造建议。",
  emptyText = "暂无检索片段。",
  onGoToRewrite,
}: ResumeChunkPreviewProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <Card title={title} description={description}>
      {chunks.length === 0 ? (
        <p className="muted-line">{emptyText}</p>
      ) : (
        <div className="chunk-list">
          {chunks.map((chunk) => {
            const expanded = expandedId === chunk.id;
            // Check if this chunk is criticized by any RAG advice
            const associatedAdvice = advice.filter((a) => a.basedOnChunkIds?.includes(chunk.id));
            const hasAdvice = associatedAdvice.length > 0;
            const highestPriority = associatedAdvice.some((a) => a.priority === "high")
              ? "high"
              : associatedAdvice.some((a) => a.priority === "medium")
              ? "medium"
              : "low";

            return (
              <article className="chunk-card" key={chunk.id} style={hasAdvice ? { borderLeft: `4px solid ${highestPriority === "high" ? "var(--accent-danger)" : "var(--accent-warning)"}` } : undefined}>
                <button type="button" onClick={() => setExpandedId(expanded ? null : chunk.id)} aria-expanded={expanded}>
                  <span style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", flex: 1 }}>
                    <strong>{chunk.section || "简历片段"}</strong>
                    <small>{chunk.metadata?.source || "上传简历"} · #{chunk.index + 1}</small>
                    {hasAdvice && (
                      <span
                        className="blink-text"
                        style={{
                          fontSize: "10px",
                          fontWeight: "700",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          background: highestPriority === "high" ? "rgba(239, 68, 68, 0.12)" : "rgba(245, 158, 11, 0.12)",
                          color: highestPriority === "high" ? "#ef4444" : "#f59e0b",
                          border: `1px solid ${highestPriority === "high" ? "rgba(239, 68, 68, 0.25)" : "rgba(245, 158, 11, 0.25)"}`
                        }}
                      >
                        ⚠️ 待改写优化 ({associatedAdvice.length} 项建议)
                      </span>
                    )}
                  </span>
                  <Badge tone="info">{Math.round(chunk.score ?? 0)}%</Badge>
                </button>
                <p>{expanded ? chunk.content : `${chunk.content.slice(0, 120)}${chunk.content.length > 120 ? "..." : ""}`}</p>
                
                {hasAdvice && expanded && onGoToRewrite && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "12px", padding: "10px", background: "rgba(0,0,0,0.02)", borderRadius: "var(--radius-sm)", border: "1px dashed var(--line)" }}>
                    <div style={{ fontSize: "11px", fontWeight: "700", color: "var(--muted)", marginBottom: "4px" }}>🎯 可选的智能改写项目建议：</div>
                    {associatedAdvice.map((adv) => (
                      <div key={adv.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "11.5px", gap: "12px", padding: "4px 0", borderBottom: "1px solid rgba(0,0,0,0.03)" }}>
                        <span style={{ color: "var(--text)", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap", flex: 1 }}>
                          <strong>{adv.priority === "high" ? "必须改" : "建议改"}</strong>: {formatIssue(adv.issue)}
                        </span>
                        <button
                          type="button"
                          onClick={() => onGoToRewrite(adv.id)}
                          style={{
                            background: "var(--accent)",
                            color: "var(--surface)",
                            border: "none",
                            borderRadius: "4px",
                            padding: "4px 10px",
                            fontSize: "11px",
                            fontWeight: "600",
                            cursor: "pointer",
                            flexShrink: 0,
                            transition: "opacity 0.2s ease"
                          }}
                          onMouseOver={(e) => e.currentTarget.style.opacity = "0.85"}
                          onMouseOut={(e) => e.currentTarget.style.opacity = "1"}
                        >
                          ✍️ 一键智能改写
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                
                {chunk.keywords?.length ? <div className="tag-row">{chunk.keywords.slice(0, 8).map((keyword) => <span key={keyword}>{keyword}</span>)}</div> : null}
              </article>
            );
          })}
        </div>
      )}
    </Card>
  );
}
