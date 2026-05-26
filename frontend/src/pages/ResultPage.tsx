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
