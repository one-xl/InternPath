import type { AnalysisResult } from "../types/analysis";
import { DecisionCard } from "../components/result/DecisionCard";
import { LearningPlanPanel } from "../components/result/LearningPlanPanel";
import { MatchScorePanel } from "../components/result/MatchScorePanel";
import { NextActionBar } from "../components/result/NextActionBar";
import { ResumeAdviceList } from "../components/result/ResumeAdviceList";
import { ResumeChunkPreview } from "../components/resume/ResumeChunkPreview";
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { formatDateTime } from "../utils/format";
import { formatFileSize } from "../utils/fileValidation";

interface ResultPageProps {
  result: AnalysisResult | null;
  isSaved: boolean;
  onNewAnalysis: () => void;
  onSave: () => void;
  onCopyAdvice: () => void;
  onMarkApplied: () => void;
  onAbandon: () => void;
  onGoToRewrite?: (jdId: string, adviceId: string) => void;
}

function ResumeEvidenceCard({ result }: { result: AnalysisResult }) {
  if (result.resumeFile) {
    return (
      <Card title="简历文件、检索和模型使用" description={result.retrievalSummary || "本次结果基于上传简历解析后的片段检索生成。"}>
        <div className="resume-evidence-grid">
          <div>
            <span>文件名</span>
            <strong>{result.resumeFile.name}</strong>
          </div>
          <div>
            <span>文件大小</span>
            <strong>{formatFileSize(result.resumeFile.size)}</strong>
          </div>
          <div>
            <span>解析时间</span>
            <strong>{formatDateTime(result.resumeFile.uploadedAt)}</strong>
          </div>
          <div>
            <span>向量模型</span>
            <strong>{result.modelUsage ? `${result.modelUsage.embeddingProvider} / ${result.modelUsage.embeddingModelId}` : "未记录"}</strong>
          </div>
          <div>
            <span>大语言模型</span>
            <strong>{result.modelUsage ? `${result.modelUsage.chatProvider} / ${result.modelUsage.chatModelId}` : "未记录"}</strong>
          </div>
          <div>
            <span>命中片段</span>
            <strong>{result.retrievedResumeChunks?.length ?? 0}</strong>
          </div>
        </div>
        {result.retrievalScore !== undefined && <p className="muted-line">平均检索相似度：{result.retrievalScore}</p>}
      </Card>
    );
  }

  return (
    <Card title="旧版文本输入记录" description="这条历史记录来自旧版手动输入材料流程，因此没有上传文件 and RAG 检索片段。">
      <Badge tone="info">兼容旧数据</Badge>
      {result.candidateMaterial || result.draft?.resumeText ? <p className="legacy-material">{result.candidateMaterial || result.draft?.resumeText}</p> : null}
    </Card>
  );
}

function AdviceEvidenceCard({ result }: { result: AnalysisResult }) {
  const linked = (result.resumeAdvice ?? []).filter((item) => item.basedOnChunkIds?.length);
  if (!linked.length) return null;
  return (
    <Card title="简历建议引用关系" description="Gemini 返回的简历建议与检索片段引用关系。">
      <div className="advice-evidence-list">
        {linked.map((item) => (
          <article key={item.id}>
            <strong>{item.issue}</strong>
            <div className="tag-row">
              {item.basedOnChunkIds?.map((id) => (
                <span key={id}>{id}</span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </Card>
  );
}

function CitationsAndEvidenceCheckPanel({ result }: { result: AnalysisResult }) {
  const claimsMapping: any[] = [];
  const res = result as any;
  
  if (res.citations && Array.isArray(res.citations)) {
    res.citations.forEach((cite: any) => {
      const score = typeof cite.retrievalScore === "number" ? cite.retrievalScore : 0.90;
      const isWeak = score < 0.50;
      claimsMapping.push({
        claimText: cite.claimText || "模型事实论断",
        status: isWeak ? "WEAK" : "SUPPORTED",
        confidenceScore: score,
        sectionTitle: cite.sectionTitle || "未指定 Section",
        sectionType: cite.sectionType || "generic_section",
        hierarchy: cite.hierarchy || [],
        fileName: cite.fileName || "上传简历",
        evidenceText: cite.evidenceText || "",
        reasons: cite.retrievalReasons || []
      });
    });
  }
  
  const unsupportedItems = res.lowSupportNotice || res.hallucinationControl?.rewrittenItems || [];
  if (Array.isArray(unsupportedItems)) {
    unsupportedItems.forEach((item: string) => {
      const cleanText = item
        .replace("证据不足，不能作为事实输出：", "")
        .replace("证据较弱，建议降级表述：", "")
        .trim();
        
      if (!claimsMapping.some(c => c.claimText === cleanText)) {
        claimsMapping.push({
          claimText: cleanText,
          status: "UNSUPPORTED",
          confidenceScore: 0.0,
          sectionTitle: "无匹配经历段",
          sectionType: "none",
          hierarchy: ["未找到支持经历"],
          fileName: "",
          evidenceText: "简历中未找到支持该事实的可靠项目/工作经历段落。",
          reasons: ["no_experience_section_matched"]
        });
      }
    });
  }

  if (claimsMapping.length === 0) return null;

  const statusColors: Record<string, { bg: string; color: string; border: string }> = {
    SUPPORTED: { bg: "rgba(16, 185, 129, 0.12)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.25)" },
    WEAK: { bg: "rgba(245, 158, 11, 0.12)", color: "#f59e0b", border: "1px solid rgba(245, 158, 11, 0.25)" },
    UNSUPPORTED: { bg: "rgba(239, 68, 68, 0.12)", color: "#ef4444", border: "1px solid rgba(239, 68, 68, 0.25)" }
  };

  return (
    <Card title="🎓 可信度审查 & Claim Evidence 证据映射" description="对模型分析报告中的核心事实论断进行证据可信度审查与溯源（Section-level Evidence Check）。">
      <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        {claimsMapping.map((item, idx) => {
          const style = statusColors[item.status] || statusColors.SUPPORTED;
          const hierarchyPath = item.hierarchy && item.hierarchy.length > 0 ? item.hierarchy.join(" > ") : item.sectionTitle;
          
          return (
            <article key={idx} style={{
              background: "var(--surface)",
              border: "1px solid var(--line)",
              borderRadius: "8px",
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: "10px"
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "8px" }}>
                <strong style={{ fontSize: "14px", color: "var(--text)", flex: 1, marginRight: "12px" }}>
                  "{item.claimText}"
                </strong>
                <span style={{
                  fontSize: "11px",
                  fontWeight: "700",
                  padding: "4px 10px",
                  borderRadius: "6px",
                  background: style.bg,
                  color: style.color,
                  border: style.border,
                  flexShrink: 0
                }}>
                  {item.status}
                </span>
              </div>

              {item.status !== "UNSUPPORTED" && (
                <div style={{ fontSize: "12.5px", color: "var(--text-light)", display: "flex", flexDirection: "column", gap: "4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span>📍 证据出处：</span>
                    <strong style={{ color: "var(--accent)" }}>{hierarchyPath}</strong>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span>📊 检索置信度 (Retrieval Score)：</span>
                    <strong style={{ color: "var(--text)" }}>
                      {(item.confidenceScore > 1 ? item.confidenceScore / 100 : item.confidenceScore).toFixed(2)}{" "}
                      ({Math.round(item.confidenceScore > 1 ? item.confidenceScore : item.confidenceScore * 100)}%)
                    </strong>
                  </div>
                </div>
              )}

              <div style={{
                background: "rgba(0, 0, 0, 0.02)",
                padding: "10px 12px",
                borderRadius: "var(--radius-sm)",
                fontSize: "12px",
                lineHeight: "1.5",
                color: "var(--muted)",
                borderLeft: `3px solid ${item.status === "SUPPORTED" ? "#10b981" : item.status === "WEAK" ? "#f59e0b" : "#ef4444"}`
              }}>
                <span style={{ fontWeight: "700", display: "block", marginBottom: "4px", fontSize: "11.5px" }}>
                  {item.status === "UNSUPPORTED" ? "⚠️ 审查结论" : "📝 简历原文证据"}
                </span>
                {item.evidenceText}
              </div>

              {item.reasons && item.reasons.length > 0 && (
                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginTop: "4px" }}>
                  {item.reasons.map((r: string) => (
                    <span key={r} style={{
                      fontSize: "10px",
                      background: "rgba(255, 255, 255, 0.04)",
                      border: "1px solid var(--line)",
                      color: "var(--muted)",
                      padding: "2px 6px",
                      borderRadius: "4px"
                    }}>
                      {r}
                    </span>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </Card>
  );
}

export function ResultPage({
  result,
  isSaved,
  onNewAnalysis,
  onSave,
  onCopyAdvice,
  onMarkApplied,
  onAbandon,
  onGoToRewrite
}: ResultPageProps) {
  if (!result) {
    return (
      <EmptyState
        title="还没有分析结果"
        description="先创建一次岗位分析，结果会按决策、匹配、简历改造、学习建议和检索证据分层展示。"
        actionLabel="新建分析"
        onAction={onNewAnalysis}
      />
    );
  }

  return (
    <div className="page-stack result-page">
      <div className="page-title">
        <span className="section-kicker">分析结果</span>
        <h2>
          {result.draft?.company || "未知公司"} · {result.draft?.title || "未命名岗位"}
        </h2>
        <p>{result.draft?.location || "地点未注明"} · {(result.detectedKeywords ?? []).join(" / ") || "未识别关键词"}</p>
      </div>
      <DecisionCard result={result} />
      <MatchScorePanel result={result} />
      <ResumeEvidenceCard result={result} />
      <ResumeChunkPreview
        chunks={result.retrievedResumeChunks ?? []}
        advice={result.resumeAdvice ?? []}
        onGoToRewrite={onGoToRewrite ? (adviceId) => onGoToRewrite(result.id, adviceId) : undefined}
      />
      <ResumeAdviceList
        advice={result.resumeAdvice ?? []}
        onGoToRewrite={onGoToRewrite ? (adviceId) => onGoToRewrite(result.id, adviceId) : undefined}
      />
      <CitationsAndEvidenceCheckPanel result={result} />
      <AdviceEvidenceCard result={result} />
      <LearningPlanPanel suggestions={result.learningSuggestions ?? []} />
      <Card title="下一步行动">
        <ol className="action-list">
          {(result.nextActions ?? []).map((action) => (
            <li key={action}>{action}</li>
          ))}
        </ol>
      </Card>
      <NextActionBar
        result={result}
        isSaved={isSaved}
        onSave={onSave}
        onCopyAdvice={onCopyAdvice}
        onMarkApplied={onMarkApplied}
        onAbandon={onAbandon}
      />
    </div>
  );
}
