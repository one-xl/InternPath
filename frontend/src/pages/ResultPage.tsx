import React, { useState, useEffect, useRef } from "react";
import type { AnalysisResult } from "../types/analysis";
import { DecisionCard } from "../components/result/DecisionCard";
import { LearningPlanPanel } from "../components/result/LearningPlanPanel";
import { MatchScorePanel } from "../components/result/MatchScorePanel";
import { NextActionBar } from "../components/result/NextActionBar";
import { ResumeAdviceList } from "../components/result/ResumeAdviceList";
import { ResumeChunkPreview } from "../components/resume/ResumeChunkPreview";
import { ResumeDiffView } from "../components/resume/ResumeDiffView";
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
  onUpdateResult: (result: AnalysisResult) => void;
  onOpenResumeAdvisor: (context: { resumeId?: string; jdText?: string }) => void;
}

const taskStatusLabels: Record<string, string> = {
  PENDING: "准备中",
  RUNNING: "处理中",
  COMPLETED: "已完成",
  FAILED: "失败",
  WAITING_FOR_HUMAN: "待确认",
};

const processFilterLabels: Record<"all" | "thought" | "tool", string> = {
  all: "全部",
  thought: "核对",
  tool: "调用",
};

const claimStatusLabels: Record<string, string> = {
  SUPPORTED: "依据充分",
  WEAK: "依据较弱",
  UNSUPPORTED: "缺少依据",
};

function ResumeEvidenceCard({ result }: { result: AnalysisResult }) {
  if (result.resumeFile) {
    return (
      <Card title="简历文件和依据来源" description={result.retrievalSummary || "本次结果基于上传简历解析后的片段生成。"}>
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
            <span>检索服务</span>
            <strong>{result.modelUsage ? `${result.modelUsage.embeddingProvider} / ${result.modelUsage.embeddingModelId}` : "未记录"}</strong>
          </div>
          <div>
            <span>生成服务</span>
            <strong>{result.modelUsage ? `${result.modelUsage.chatProvider} / ${result.modelUsage.chatModelId}` : "未记录"}</strong>
          </div>
          <div>
            <span>命中片段</span>
            <strong>{result.retrievedResumeChunks?.length ?? 0}</strong>
          </div>
        </div>
        {result.retrievalScore !== undefined && <p className="muted-line">平均匹配度：{result.retrievalScore}</p>}
      </Card>
    );
  }

  return (
    <Card title="旧版文本输入记录" description="这条历史记录来自旧版手动输入材料流程，因此没有上传文件和依据片段。">
      <Badge tone="info">兼容旧记录</Badge>
      {result.candidateMaterial || result.draft?.resumeText ? <p className="legacy-material">{result.candidateMaterial || result.draft?.resumeText}</p> : null}
    </Card>
  );
}

function AdviceEvidenceCard({ result }: { result: AnalysisResult }) {
  const linked = (result.resumeAdvice ?? []).filter((item) => item.basedOnChunkIds?.length);
  if (!linked.length) return null;
  return (
    <Card title="简历建议引用关系" description="简历建议和依据片段的对应关系。">
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

function ProjectRecommendationsCard({ result }: { result: AnalysisResult }) {
  const recommendations = result.projectRecommendations ?? result.projectRerank?.recommendations ?? [];
  if (!recommendations.length) return null;
  const rerank = result.projectRerank;

  return (
    <Card
      title="项目知识库推荐"
      description={rerank?.rerankMode === "fallback" ? "模型重排不可用，已显示可追溯的确定性排序。" : "结合 JD、当前简历和项目证据重排。"}
    >
      <div className="project-recommendations">
        {recommendations.map((recommendation) => (
          <article key={recommendation.documentId} className="project-recommendation">
            <div className="project-recommendation__head">
              <strong>{recommendation.documentId}</strong>
              <Badge tone="success">{Math.round(recommendation.score)} 分</Badge>
            </div>
            <p>{recommendation.matchReason}</p>
            <div className="project-recommendation__fact">
              <span>建议写入简历</span>
              <strong>{recommendation.resumeSuggestion}</strong>
            </div>
            <details>
              <summary>查看知识库证据（{recommendation.chunkIds.length} 个片段）</summary>
              {recommendation.evidence.map((evidence, index) => <p key={`${recommendation.chunkIds[index]}-${index}`}>{evidence}</p>)}
            </details>
          </article>
        ))}
      </div>
      {rerank?.fallbackReason && <p className="muted-line">降级原因：{rerank.fallbackReason}</p>}
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
        claimText: cite.claimText || "待核对表述",
        status: isWeak ? "WEAK" : "SUPPORTED",
        confidenceScore: score,
        sectionTitle: cite.sectionTitle || "未指定位置",
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
    <Card title="依据核对" description="对分析报告中的核心表述做依据核对和来源追踪。">
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
                  {claimStatusLabels[item.status] || item.status}
                </span>
              </div>

              {item.status !== "UNSUPPORTED" && (
                <div style={{ fontSize: "12.5px", color: "var(--text-light)", display: "flex", flexDirection: "column", gap: "4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span>依据出处：</span>
                    <strong style={{ color: "var(--accent)" }}>{hierarchyPath}</strong>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span>匹配度：</span>
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
                borderLeft: `3px solid ${item.status === "SUPPORTED" ? "var(--success)" : item.status === "WEAK" ? "var(--warning)" : "var(--danger)"}`
              }}>
                <span style={{ fontWeight: "700", display: "block", marginBottom: "4px", fontSize: "11.5px" }}>
                  {item.status === "UNSUPPORTED" ? "核对结论" : "简历原文依据"}
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
  onUpdateResult,
  onOpenResumeAdvisor,
}: ResultPageProps) {
  const [activeEvidenceChunk, setActiveEvidenceChunk] = useState<any | null>(null);
  const [activeTab, setActiveTab] = useState<"analysis" | "diff" | "preview">("analysis");
  const [copied, setCopied] = useState(false);

  // Resume optimization states
  const [showOptimizeModal, setShowOptimizeModal] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<any | null>(null);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [showConsole, setShowConsole] = useState(false);
  const [terminalFilter, setTerminalFilter] = useState<"all" | "thought" | "tool">("all");
  const autoPromptedRef = useRef<string | null>(null);
  const terminalEndRef = useRef<HTMLDivElement | null>(null);

  // Resume comparison editor states
  const [selectedEditIdx, setSelectedEditIdx] = useState<number>(0);
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [editText, setEditText] = useState<string>("");
  const [isSavingEdit, setIsSavingEdit] = useState<boolean>(false);

  const currentEditItem = result?.modification_log?.[selectedEditIdx];

  // New analysis results should not trigger legacy artifact generation.
  useEffect(() => {
    autoPromptedRef.current = result?.id || null;
    setShowOptimizeModal(false);
  }, [result]);

  // Sync edit text with selected paragraph
  useEffect(() => {
    if (currentEditItem) {
      setEditText(currentEditItem.new || "");
      setIsEditing(false);
    }
  }, [selectedEditIdx, currentEditItem]);

  // Scroll terminal logs to bottom
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [activeTask?.logs]);

  // Polling optimization task status
  useEffect(() => {
    if (!activeTaskId) return;

    const intervalId = setInterval(async () => {
      try {
        const res = await fetch(`/api/agent/resume/tasks/${activeTaskId}`);
        if (!res.ok) {
          clearInterval(intervalId);
          return;
        }
        const data = await res.json();

        const taskData = {
          task_id: data.taskId,
          status: data.status,
          resume_id: data.resumeId,
          original_resume_name: data.originalResumeName,
          jd_text: data.jdText,
          logs: data.logs || [],
          optimized_resume_md: data.optimizedResumeMd || "",
          error_message: data.errorMessage || "",
          created_at: data.createdAt,
          updated_at: data.updatedAt,
          modification_diff_md: data.modificationDiffMd || "",
          has_docx: data.hasDocx || false,
          modification_log: data.modificationLog || []
        };

        setActiveTask(taskData);

        if (data.status === "COMPLETED" || data.status === "FAILED") {
          clearInterval(intervalId);
          setActiveTaskId(null);
          setIsOptimizing(false);

          // Fetch updated record and reload
          const refreshRes = await fetch(`/api/history/${result?.id}`);
          if (refreshRes.ok) {
            const refreshData = await refreshRes.json();
            if (refreshData.record) {
              onUpdateResult(refreshData.record);
              setActiveTab("diff"); // Automatically switch to Diff tab on completion
            }
          }
        }
      } catch (err) {
        console.error("Error polling optimization task:", err);
        clearInterval(intervalId);
        setIsOptimizing(false);
      }
    }, 1500);

    return () => clearInterval(intervalId);
  }, [activeTaskId, result?.id, onUpdateResult]);

  const handleStartOptimize = () => {
    if (!result) return;
    onOpenResumeAdvisor({ resumeId: result.resumeFile?.id, jdText: result.draft?.jdText });
  };

  const handleSaveEdit = async () => {
    if (!result || !currentEditItem) return;
    setIsSavingEdit(true);
    try {
      const res = await fetch(`/api/agent/resume/tasks/${result.id}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          section_index: currentEditItem.section_index,
          new_text: editText
        })
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "保存修改失败");
      }

      // Fetch updated record
      const refreshRes = await fetch(`/api/history/${result.id}`);
      if (refreshRes.ok) {
        const refreshData = await refreshRes.json();
        if (refreshData.record) {
          onUpdateResult(refreshData.record);
          setIsEditing(false);
          alert("修改保存成功！Word & PDF 原地排版保留重构完成。");
        }
      }
    } catch (err: any) {
      alert(err.message || "请求失败");
    } finally {
      setIsSavingEdit(false);
    }
  };

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

  const handleShowEvidence = (chunkIds: string[]) => {
    if (!result || !result.retrievedResumeChunks) return;
    const chunk = result.retrievedResumeChunks.find((c) => chunkIds.includes(c.id));
    if (chunk) {
      setActiveEvidenceChunk(chunk);
    }
  };

  const hasAgentResult = Boolean(result.optimized_resume_md);

  const handleCopyMarkdown = () => {
    if (!result.optimized_resume_md) return;
    navigator.clipboard.writeText(result.optimized_resume_md);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const renderMarkdown = (text: string) => {
    if (!text) return null;
    const lines = text.split("\n");
    return (
      <div className="markdown-preview-content" style={{ lineHeight: "1.6", color: "var(--text)" }}>
        {lines.map((line, idx) => {
          let trimmed = line.trim();
          if (trimmed.startsWith("# ")) {
            return <h2 key={idx} style={{ marginTop: "18px", marginBottom: "8px", color: "var(--text)", fontSize: "20px", fontWeight: "800", borderBottom: "1px solid var(--line)", paddingBottom: "6px" }}>{trimmed.replace(/^#\s*/, "")}</h2>;
          }
          if (trimmed.startsWith("## ")) {
            return <h3 key={idx} style={{ marginTop: "16px", marginBottom: "6px", color: "var(--text)", fontSize: "16px", fontWeight: "700" }}>{trimmed.replace(/^##\s*/, "")}</h3>;
          }
          if (trimmed.startsWith("### ")) {
            return <h4 key={idx} style={{ marginTop: "14px", marginBottom: "6px", color: "var(--accent)", fontSize: "14.5px", fontWeight: "700" }}>{trimmed.replace(/^###\s*/, "")}</h4>;
          }
          if (trimmed.startsWith("**") && trimmed.endsWith("**")) {
            return <p key={idx} style={{ fontWeight: 700, color: "var(--text)", marginBottom: "6px" }}>{trimmed.replace(/\*\*/g, "")}</p>;
          }
          if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
            let boldParsed = trimmed.replace(/^[-*]\s*/, "");
            const parts = boldParsed.split("**");
            return (
              <li key={idx} style={{ marginLeft: "18px", listStyleType: "disc", marginBottom: "6px", color: "var(--text)" }}>
                {parts.map((p, i) => i % 2 === 1 ? <strong key={i} style={{ color: "var(--accent)", fontWeight: "700" }}>{p}</strong> : p)}
              </li>
            );
          }
          if (!trimmed) return <div key={idx} style={{ height: "8px" }} />;
          const parts = trimmed.split("**");
          return (
            <p key={idx} style={{ marginBottom: "6px", lineHeight: "1.6", color: "var(--text)" }}>
              {parts.map((p, i) => i % 2 === 1 ? <strong key={i} style={{ color: "var(--accent)", fontWeight: "700" }}>{p}</strong> : p)}
            </p>
          );
        })}
      </div>
    );
  };

  return (
    <div className="page-stack result-page" style={{ position: "relative", paddingBottom: showConsole ? "380px" : "40px" }}>
      <div className="page-title">
        <span className="section-kicker">分析结果</span>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2>
            {result.draft?.company || "未知公司"} · {result.draft?.title || "未命名岗位"}
          </h2>
          <div style={{ display: "flex", gap: "10px" }}>
            {!hasAgentResult && !isOptimizing && (
              <button
                type="button"
                onClick={handleStartOptimize}
                style={{
                  background: "linear-gradient(180deg, var(--accent), var(--accent-hover, var(--accent)))",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 16px",
                  borderRadius: "8px",
                  fontWeight: "700",
                  fontSize: "13px",
                  cursor: "pointer",
                  boxShadow: "var(--shadow-sm)"
                }}
              >
                与简历 Agent 讨论
              </button>
            )}
            {isOptimizing && (
              <button
                type="button"
                onClick={() => setShowConsole(true)}
                style={{
                  background: "var(--surface-soft, #2e2e2e)",
                  color: "var(--text)",
                  border: "1px solid var(--line)",
                  padding: "8px 16px",
                  borderRadius: "8px",
                  fontWeight: "600",
                  fontSize: "13px",
                  cursor: "pointer"
                }}
              >
                查看过程记录
              </button>
            )}
          </div>
        </div>
        <p>{result.draft?.location || "地点未注明"} · {(result.detectedKeywords ?? []).join(" / ") || "未识别关键词"}</p>
      </div>

      {hasAgentResult && (
        <div className="tabs" style={{ marginBottom: "20px" }}>
          <button
            type="button"
            className={activeTab === "analysis" ? "active" : ""}
            onClick={() => setActiveTab("analysis")}
          >
            岗位匹配度分析
          </button>
          <button
            type="button"
            className={activeTab === "diff" ? "active" : ""}
            onClick={() => setActiveTab("diff")}
          >
            简历修改对照
          </button>
          <button
            type="button"
            className={activeTab === "preview" ? "active" : ""}
            onClick={() => setActiveTab("preview")}
          >
            优化后简历预览
          </button>
        </div>
      )}

      {activeTab === "analysis" && (
        <>
          <DecisionCard result={result} />
          <MatchScorePanel result={result} />
          <ProjectRecommendationsCard result={result} />
          <ResumeEvidenceCard result={result} />
          <ResumeChunkPreview
            chunks={result.retrievedResumeChunks ?? []}
            advice={result.resumeAdvice ?? []}
          />
          <ResumeAdviceList
            advice={result.resumeAdvice ?? []}
            onShowEvidence={handleShowEvidence}
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
        </>
      )}

      {activeTab === "diff" && (
        <Card title="旧版简历修改对照" description="这是历史下载型任务留下的只读对照；新的修改请进入简历 Agent 会话。">
          <div style={{
            display: "grid",
            gridTemplateColumns: "300px 1fr",
            gap: "20px",
            alignItems: "stretch",
            minHeight: "500px",
            background: "var(--surface)",
            borderRadius: "12px",
            border: "1px solid var(--line)",
            overflow: "hidden"
          }}>
            {/* Left Column: Sidebar Cards List */}
            <div style={{
              borderRight: "1px solid var(--line)",
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              maxHeight: "650px",
              overflowY: "auto",
              background: "rgba(255,255,255,0.01)"
            }}>
              {(result.modification_log || []).map((item, idx) => {
                const isSelected = selectedEditIdx === idx;
                return (
                  <div
                    key={idx}
                    onClick={() => setSelectedEditIdx(idx)}
                    style={{
                      padding: "12px",
                      borderRadius: "8px",
                      border: isSelected ? "1px solid var(--accent-border)" : "1px solid var(--line)",
                      background: isSelected ? "var(--accent-bg)" : "transparent",
                      cursor: "pointer",
                      transition: "all 0.2s"
                    }}
                  >
                    <div style={{ fontWeight: "700", fontSize: "14px", color: "var(--text)", marginBottom: "4px" }}>
                      {item.section_name}
                    </div>
                    <div style={{ fontSize: "12px", color: "var(--text-muted)", textOverflow: "ellipsis", whiteSpace: "nowrap", overflow: "hidden" }}>
                      {item.new}
                    </div>
                    {item.reason && (
                      <div style={{ fontSize: "11px", color: "var(--accent)", marginTop: "6px", display: "flex", alignItems: "center", gap: "4px" }}>
                        <span>理由</span>
                        <span style={{ textOverflow: "ellipsis", whiteSpace: "nowrap", overflow: "hidden" }}>
                          {item.reason}
                        </span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Right Column: Comparison & Editor */}
            <div style={{ padding: "20px", display: "flex", flexDirection: "column", gap: "16px", maxHeight: "650px", overflowY: "auto" }}>
              {currentEditItem ? (
                <>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--line)", paddingBottom: "12px" }}>
                    <h4 style={{ margin: 0, fontSize: "16px", fontWeight: "700" }}>{currentEditItem.section_name}</h4>
                    <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>历史记录只读</span>
                  </div>

                  {currentEditItem.reason && (
                    <div style={{
                      padding: "10px 14px",
                      background: "var(--accent-bg)",
                      borderLeft: "4px solid var(--accent)",
                      fontSize: "12.5px",
                      color: "var(--text)",
                      lineHeight: "1.5"
                    }}>
                      <strong>修改理由：</strong> {currentEditItem.reason}
                    </div>
                  )}

                  {/* Side by Side Diff Panels */}
                  <div style={{ display: "flex", gap: "16px", flex: 1 }}>
                    {/* Original (Left) */}
                    <div style={{
                      flex: 1,
                      display: "flex",
                      flexDirection: "column",
                      gap: "8px"
                    }}>
                      <div style={{ fontSize: "12px", fontWeight: "700", color: "var(--danger)" }}>修改前</div>
                      <div style={{
                        flex: 1,
                        background: "rgba(239, 68, 68, 0.04)",
                        border: "1px solid rgba(239, 68, 68, 0.15)",
                        borderRadius: "8px",
                        padding: "14px",
                        fontSize: "13px",
                        lineHeight: "1.6",
                        color: "var(--danger)",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-all"
                      }}>
                        {currentEditItem.original}
                      </div>
                    </div>

                    {/* Optimized / Editor (Right) */}
                    <div style={{
                      flex: 1,
                      display: "flex",
                      flexDirection: "column",
                      gap: "8px"
                    }}>
                      <div style={{ fontSize: "12px", fontWeight: "700", color: "var(--success)" }}>修改后</div>
                      {isEditing ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: "10px", flex: 1 }}>
                          <textarea
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            style={{
                              flex: 1,
                              minHeight: "200px",
                              background: "var(--surface-soft, #2e2e2e)",
                              border: "1px solid var(--accent)",
                              borderRadius: "8px",
                              padding: "14px",
                              fontSize: "13px",
                              lineHeight: "1.6",
                              color: "var(--text)",
                              outline: "none",
                              resize: "vertical",
                              fontFamily: "inherit"
                            }}
                          />
                          <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
                            <button
                              type="button"
                              onClick={() => setIsEditing(false)}
                              disabled={isSavingEdit}
                              style={{
                                background: "transparent",
                                border: "1px solid var(--line)",
                                color: "var(--text-muted)",
                                padding: "6px 12px",
                                borderRadius: "6px",
                                fontSize: "12.5px",
                                cursor: "pointer"
                              }}
                            >
                              取消
                            </button>
                            <button
                              type="button"
                              onClick={handleSaveEdit}
                              disabled={isSavingEdit}
                              style={{
                                background: "var(--accent)",
                                border: "none",
                                color: "#ffffff",
                                padding: "6px 12px",
                                borderRadius: "6px",
                                fontSize: "12.5px",
                                fontWeight: "600",
                                cursor: "pointer"
                              }}
                            >
                              {isSavingEdit ? "保存中..." : "保存修改"}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div
                          style={{
                            flex: 1,
                            background: "rgba(16, 185, 129, 0.04)",
                            border: "1px solid rgba(16, 185, 129, 0.15)",
                            borderRadius: "8px",
                            padding: "14px",
                            fontSize: "13px",
                            lineHeight: "1.6",
                            color: "var(--success)",
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-all",
                            cursor: "default"
                          }}
                        >
                          {currentEditItem.new}
                        </div>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1, color: "var(--text-muted)" }}>
                  请从左侧选择需要查看的修改模块
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      {activeTab === "preview" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "var(--surface)", border: "1px solid var(--line)", padding: "12px 18px", borderRadius: "12px" }}>
            <span style={{ fontSize: "14px", fontWeight: "600", color: "var(--text-muted)" }}>
              历史任务生成的文件产物（只读）：
            </span>
            <div style={{ display: "flex", gap: "10px" }}>
              <button
                type="button"
                onClick={handleCopyMarkdown}
                style={{
                  background: copied ? "#10b981" : "var(--surface-muted)",
                  color: copied ? "#ffffff" : "var(--text-main)",
                  border: "1px solid var(--line)",
                  padding: "6px 14px",
                  borderRadius: "8px",
                  fontSize: "13px",
                  fontWeight: "600",
                  cursor: "pointer",
                  transition: "all 0.2s"
                }}
              >
                {copied ? "已复制" : "复制 MD"}
              </button>
              <a
                href={`/api/agent/resume/tasks/${result.id}/download`}
                style={{
                  background: "var(--accent)",
                  color: "#ffffff",
                  textDecoration: "none",
                  padding: "6px 14px",
                  borderRadius: "8px",
                  fontSize: "13px",
                  fontWeight: "700",
                  cursor: "pointer"
                }}
              >
                下载 MD
              </a>
              {result.has_docx && (
                <a
                  href={`/api/agent/resume/tasks/${result.id}/download?format=docx`}
                  style={{
                    background: "#10b981",
                    color: "#ffffff",
                    textDecoration: "none",
                    padding: "6px 14px",
                    borderRadius: "8px",
                    fontSize: "13px",
                    fontWeight: "700",
                    cursor: "pointer"
                  }}
                >
                  下载 DOCX
                </a>
              )}
              {result.has_docx && (
                <a
                  href={`/api/agent/resume/tasks/${result.id}/download?format=pdf`}
                  style={{
                    background: "#ef4444",
                    color: "#ffffff",
                    textDecoration: "none",
                    padding: "6px 14px",
                    borderRadius: "8px",
                    fontSize: "13px",
                    fontWeight: "700",
                    cursor: "pointer"
                  }}
                >
                  下载 PDF
                </a>
              )}
            </div>
          </div>

          <Card title="优化后简历排版预览">
            <div style={{
              background: "var(--surface)",
              border: "1px solid var(--line)",
              borderRadius: "12px",
              padding: "24px",
              maxHeight: "750px",
              overflowY: "auto"
            }}>
              {renderMarkdown(result.optimized_resume_md || "")}
            </div>
          </Card>
        </div>
      )}

      <NextActionBar
        result={result}
        isSaved={isSaved}
        onSave={onSave}
        onCopyAdvice={onCopyAdvice}
        onMarkApplied={onMarkApplied}
        onAbandon={onAbandon}
      />

      {/* iOS style Onboarding Optimize Modal */}
      {showOptimizeModal && (
        <div style={{
          position: "fixed",
          top: 0,
          left: 0,
          width: "100vw",
          height: "100vh",
          background: "rgba(0, 0, 0, 0.6)",
          backdropFilter: "blur(8px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 2000,
          animation: "fadeIn 0.25s ease-out"
        }}>
          <div style={{
            background: "var(--surface, #1e1e1e)",
            border: "1px solid var(--line, #2e2e2e)",
            borderRadius: "20px",
            padding: "24px",
            width: "420px",
            boxShadow: "0 10px 40px rgba(0,0,0,0.3)",
            display: "flex",
            flexDirection: "column",
            gap: "16px",
            fontFamily: "var(--font-sans, system-ui, sans-serif)",
            color: "var(--text, #fff)",
            textAlign: "center"
          }}>
            <div style={{ fontSize: "12px", fontWeight: "800", color: "var(--accent)", letterSpacing: "0.08em" }}>简历定向优化</div>
            <h3 style={{ margin: 0, fontSize: "18px", fontWeight: "700" }}>为这个岗位生成投递版简历</h3>
            <p style={{ margin: 0, fontSize: "14px", color: "var(--text-muted, #8e8e93)", lineHeight: "1.5" }}>
              当前简历和岗位要求还有一些差距。可以基于已有修改建议生成一版投递简历，并尽量保留原简历的字体和排版。
            </p>
            <div style={{ display: "flex", gap: "12px", marginTop: "8px" }}>
              <button
                type="button"
                onClick={() => setShowOptimizeModal(false)}
                style={{
                  flex: 1,
                  background: "rgba(255, 255, 255, 0.05)",
                  color: "var(--text, #fff)",
                  border: "1px solid var(--line, #2e2e2e)",
                  padding: "12px",
                  borderRadius: "10px",
                  fontSize: "14px",
                  fontWeight: "600",
                  cursor: "pointer",
                  transition: "all 0.15s"
                }}
              >
                稍后再说
              </button>
              <button
                type="button"
                onClick={handleStartOptimize}
                style={{
                  flex: 1,
                  background: "linear-gradient(180deg, var(--accent), var(--accent-hover, var(--accent)))",
                  color: "#fff",
                  border: "none",
                  padding: "12px",
                  borderRadius: "10px",
                  fontSize: "14px",
                  fontWeight: "600",
                  cursor: "pointer",
                  transition: "all 0.15s",
                  boxShadow: "var(--shadow-sm)"
                }}
              >
                开始优化
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Resume optimization process drawer */}
      {showConsole && activeTask && (
        <div style={{
          position: "fixed",
          bottom: 0,
          left: 0,
          right: 0,
          height: "360px",
          background: "var(--surface)",
          borderTop: "1px solid var(--line)",
          boxShadow: "0 -18px 56px rgba(0,0,0,0.32)",
          zIndex: 998,
          display: "flex",
          flexDirection: "column",
          fontFamily: "inherit"
        }}>
          {/* Header */}
          <div style={{
            padding: "12px 18px",
            background: "var(--surface-soft, var(--surface))",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            borderBottom: "1px solid var(--line)"
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{
                color: "var(--text)",
                fontSize: "13px",
                fontWeight: "800"
              }}>
                过程记录
              </span>
              <span style={{
                color: "var(--muted)",
                fontSize: "12px",
                fontWeight: "650"
              }}>
                {taskStatusLabels[activeTask.status] || activeTask.status}
              </span>
            </div>

            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              <div style={{ display: "flex", gap: "6px" }}>
                {(["all", "thought", "tool"] as const).map(type => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => setTerminalFilter(type)}
                    style={{
                      background: terminalFilter === type ? "var(--accent-bg)" : "transparent",
                      color: terminalFilter === type ? "var(--accent)" : "var(--muted)",
                      border: "1px solid var(--line)",
                      borderRadius: "999px",
                      padding: "4px 10px",
                      fontSize: "11px",
                      cursor: "pointer",
                      fontWeight: "700"
                    }}
                  >
                    {processFilterLabels[type]}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => {
                  if (activeTask.status === "RUNNING") {
                    if (window.confirm("任务仍在处理中，确定关闭过程记录吗？（任务会继续运行）")) {
                      setShowConsole(false);
                    }
                  } else {
                    setShowConsole(false);
                  }
                }}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--muted)",
                  fontSize: "16px",
                  cursor: "pointer",
                  padding: "0 6px"
                }}
              >
                ✕
              </button>
            </div>
          </div>

          {/* Logs */}
          <div style={{
            flexGrow: 1,
            overflowY: "auto",
            padding: "16px",
            display: "flex",
            flexDirection: "column",
            gap: "10px",
            fontSize: "12.5px",
            lineHeight: "1.5"
          }}>
            {activeTask.status === "PENDING" && (
              <div style={{ color: "var(--muted)" }}>任务已创建，正在准备处理环境...</div>
            )}

            {activeTask.logs && activeTask.logs.filter((log: any) => {
              if (terminalFilter === "thought") return log.type === "thought";
              if (terminalFilter === "tool") return log.type === "tool_call" || log.type === "tool_response";
              return true;
            }).map((log: any, index: number) => {
              let color = "var(--muted)";
              let prefix = "记录";

              if (log.type === "info") color = "var(--text)";
              else if (log.type === "thought") {
                color = "var(--success)";
                prefix = "核对";
              } else if (log.type === "tool_call") {
                color = "var(--accent)";
                prefix = "调用";
              } else if (log.type === "tool_response") {
                color = "var(--muted)";
                prefix = "返回";
              } else if (log.type === "warning") color = "var(--warning)";
              else if (log.type === "error") {
                color = "var(--danger)";
                prefix = "错误";
              }

              return (
                <div key={index} style={{ color: color, wordBreak: "break-all" }}>
                  <span style={{ color: "var(--subtle)", marginRight: "6px" }}>
                    [{new Date(log.timestamp).toLocaleTimeString()}]
                  </span>
                  <strong style={{ marginRight: "6px" }}>{prefix}</strong>
                  {log.message}
                  {log.detail && (
                    <pre style={{
                      margin: "4px 0 0 0",
                      background: "var(--surface-muted)",
                      padding: "8px",
                      borderRadius: "6px",
                      color: "var(--text)",
                      fontSize: "11.5px",
                      overflowX: "auto",
                      whiteSpace: "pre-wrap"
                    }}>
                      {typeof log.detail === "string" ? log.detail : JSON.stringify(log.detail, null, 2)}
                    </pre>
                  )}
                </div>
              );
            })}

            {activeTask.status === "RUNNING" && (
              <div style={{ color: "var(--muted)" }}>
                正在后台处理，请稍等...
              </div>
            )}
            <div ref={terminalEndRef} />
          </div>
        </div>
      )}

      {activeEvidenceChunk && (
        <>
          {/* Overlay background blur */}
          <div
            onClick={() => setActiveEvidenceChunk(null)}
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              width: "100vw",
              height: "100vh",
              background: "rgba(0, 0, 0, 0.4)",
              backdropFilter: "blur(4px)",
              zIndex: 999
            }}
          />
          {/* Slide-out Drawer */}
          <div style={{
            position: "fixed",
            top: 0,
            right: 0,
            width: "460px",
            height: "100vh",
            background: "var(--bg-card, #1c1c1e)",
            borderLeft: "1px solid var(--line, #2c2c2e)",
            boxShadow: "-10px 0 35px rgba(0,0,0,0.3)",
            zIndex: 1000,
            padding: "28px",
            display: "flex",
            flexDirection: "column",
            gap: "20px",
            color: "var(--text, #fff)",
            overflowY: "auto",
            animation: "slideIn 0.2s ease-out"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--line, #2c2c2e)", paddingBottom: "12px" }}>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "700", color: "var(--text)" }}>原文依据</h3>
              <button
                type="button"
                onClick={() => setActiveEvidenceChunk(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--muted, #8e8e93)",
                  fontSize: "20px",
                  cursor: "pointer",
                  padding: "4px"
                }}
              >
                ✕
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ fontSize: "11px", textTransform: "uppercase", color: "var(--muted, #8e8e93)", fontWeight: "600" }}>位置出处</div>
              <strong style={{ fontSize: "14px", color: "var(--accent, #007aff)" }}>
                {activeEvidenceChunk.hierarchy && activeEvidenceChunk.hierarchy.length > 0
                  ? activeEvidenceChunk.hierarchy.join(" > ")
                  : (activeEvidenceChunk.sectionTitle || activeEvidenceChunk.section || "简历部分")}
              </strong>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ fontSize: "11px", textTransform: "uppercase", color: "var(--muted, #8e8e93)", fontWeight: "600" }}>原始文件名 / 索引</div>
              <span style={{ fontSize: "13px", color: "var(--text-light, #eaeaea)" }}>
                {activeEvidenceChunk.metadata?.source || "上传简历"} (段落 #{activeEvidenceChunk.index + 1})
              </span>
            </div>

            {activeEvidenceChunk.score !== undefined && (
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <div style={{ fontSize: "11px", textTransform: "uppercase", color: "var(--muted, #8e8e93)", fontWeight: "600" }}>相关度得分</div>
                <span style={{ fontSize: "13px", fontWeight: "600", color: "#10b981" }}>
                  {(activeEvidenceChunk.score > 1 ? activeEvidenceChunk.score / 100 : activeEvidenceChunk.score).toFixed(2)}{" "}
                  ({Math.round(activeEvidenceChunk.score > 1 ? activeEvidenceChunk.score : activeEvidenceChunk.score * 100)}%)
                </span>
              </div>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: "8px", flex: 1 }}>
              <div style={{ fontSize: "11px", textTransform: "uppercase", color: "var(--muted, #8e8e93)", fontWeight: "600" }}>凭证原文内容</div>
              <div style={{
                background: "rgba(0, 0, 0, 0.15)",
                padding: "16px",
                borderRadius: "8px",
                fontSize: "13px",
                lineHeight: "1.6",
                color: "var(--text-light, #eaeaea)",
                border: "1px solid var(--line, #2c2c2e)",
                whiteSpace: "pre-wrap",
                overflowY: "auto",
                flex: 1
              }}>
                {activeEvidenceChunk.content || activeEvidenceChunk.text}
              </div>
            </div>

            <div style={{ display: "flex", gap: "10px", marginTop: "auto", paddingTop: "12px", borderTop: "1px solid var(--line, #2c2c2e)" }}>
              <button
                type="button"
                onClick={() => setActiveEvidenceChunk(null)}
                style={{
                  flex: 1,
                  background: "var(--accent, #007aff)",
                  color: "#fff",
                  border: "none",
                  borderRadius: "6px",
                  padding: "10px",
                  fontWeight: "600",
                  cursor: "pointer"
                }}
              >
                关闭
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
