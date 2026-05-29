import { useState } from "react";
import { AnalysisProgressPanel } from "../components/analysis/AnalysisProgressPanel";
import { JobInputForm } from "../components/job/JobInputForm";
import { AnalysisDebugPanel } from "../components/job/AnalysisDebugPanel";
import type { JobDraft } from "../types/job";
import type { ChatModelConfig, EmbeddingModelConfig } from "../types/modelConfig";
import type { ParsedResume, ResumeFileStatus, UploadedResumeFile } from "../types/resume";
import type { AnalysisRunStatus, AnalysisStep } from "../types/analysis";
import type { AnalysisDraft } from "../types/analysisDraft";

interface NewAnalysisPageProps {
  draft: JobDraft;
  resumeFile: UploadedResumeFile | null;
  parsedResume: ParsedResume | null;
  resumeStatus: ResumeFileStatus;
  resumeError: string;
  resumeReady: boolean;
  isAnalyzing: boolean;
  isRetrieving: boolean;
  activeEmbeddingConfig?: EmbeddingModelConfig;
  activeChatConfig?: ChatModelConfig;
  progressStep: number;
  steps: AnalysisStep[];
  analysisStatus: AnalysisRunStatus;
  error: string;
  onChangeDraft: (patch: Partial<JobDraft>) => void;
  onSelectResume: (file: File) => void;
  onSelectSavedResume: (parsed: ParsedResume) => void;
  onRetryResume: () => void;
  onRemoveResume: () => void;
  onGoSettings: () => void;
  onAnalyze: () => void;
  
  // Draft props
  latestDraft: AnalysisDraft | null;
  draftSaveMessage: string | null;
  onRestoreDraft: (draft: AnalysisDraft) => void;
  onDeleteDraft: (id: string) => void;
  onSaveDraft: () => void;
  onViewDrafts: () => void;
  onClearForm: () => void;
}

export function NewAnalysisPage({
  draft,
  resumeFile,
  parsedResume,
  resumeStatus,
  resumeError,
  resumeReady,
  isAnalyzing,
  isRetrieving,
  activeEmbeddingConfig,
  activeChatConfig,
  progressStep,
  steps,
  analysisStatus,
  error,
  onChangeDraft,
  onSelectResume,
  onSelectSavedResume,
  onRetryResume,
  onRemoveResume,
  onGoSettings,
  onAnalyze,
  
  latestDraft,
  draftSaveMessage,
  onRestoreDraft,
  onDeleteDraft,
  onSaveDraft,
  onViewDrafts,
  onClearForm,
}: NewAnalysisPageProps) {
  const [isAlertIgnored, setIsAlertIgnored] = useState(false);
  const embeddingStatus = activeEmbeddingConfig ? `${activeEmbeddingConfig.provider} / ${activeEmbeddingConfig.modelId}` : "向量模型未配置";
  const chatStatus = activeChatConfig ? `${activeChatConfig.provider} / ${activeChatConfig.modelId}` : "分析模型未配置";

  return (
    <div className="page-stack new-analysis-page">
      <section className="analysis-hero">
        <div>
          <span className="section-kicker">Spotify x Apple Job Desk</span>
          <h2>求职决策台</h2>
          <p>上传简历，粘贴 JD，快速判断这个岗位是否值得投。</p>
        </div>
        <div className="analysis-hero-meta" aria-label="当前分析环境">
          <span>{embeddingStatus}</span>
          <span>{chatStatus}</span>
          <span>{latestDraft ? "检测到未完成草稿" : "当前没有待恢复草稿"}</span>
        </div>
      </section>

      {latestDraft && !isAlertIgnored && (
        <div className="draft-alert-banner">
          <div className="banner-content">
            <span className="banner-icon" aria-hidden="true" />
            <div className="banner-text">
              <strong>检测到未完成的分析草稿</strong>
              <span>
                公司：{latestDraft.companyName || "未填写"} | 岗位：{latestDraft.jobTitle || "未填写"} | 更新时间：
                {new Date(latestDraft.updatedAt).toLocaleString()}
              </span>
            </div>
          </div>
          <div className="banner-actions">
            <button
              type="button"
              className="btn-restore"
              onClick={() => onRestoreDraft(latestDraft)}
            >
              恢复草稿
            </button>
            <button
              type="button"
              className="btn-ignore"
              onClick={() => setIsAlertIgnored(true)}
            >
              忽略
            </button>
            <button
              type="button"
              className="btn-delete"
              onClick={() => {
                if (window.confirm("确定要删除这篇草稿吗？此操作无法撤销。")) {
                  onDeleteDraft(latestDraft.id);
                }
              }}
            >
              删除草稿
            </button>
          </div>
        </div>
      )}
      <JobInputForm
        draft={draft}
        resumeFile={resumeFile}
        parsedResume={parsedResume}
        resumeStatus={resumeStatus}
        resumeError={resumeError}
        resumeReady={resumeReady}
        isAnalyzing={isAnalyzing}
        isRetrieving={isRetrieving}
        activeEmbeddingConfig={activeEmbeddingConfig}
        activeChatConfig={activeChatConfig}
        analysisStatus={analysisStatus}
        error={error}
        onChange={onChangeDraft}
        onSelectResume={onSelectResume}
        onSelectSavedResume={onSelectSavedResume}
        onRetryResume={onRetryResume}
        onRemoveResume={onRemoveResume}
        onGoSettings={onGoSettings}
        onSubmit={onAnalyze}
        onSaveDraft={onSaveDraft}
        onViewDrafts={onViewDrafts}
        onClearForm={onClearForm}
        sidePanel={
          <>
            <AnalysisProgressPanel
              status={analysisStatus}
              steps={steps}
              error={error || null}
              onRetry={onAnalyze}
              draftSaveMessage={draftSaveMessage}
              activeChatConfig={activeChatConfig}
            />
            <AnalysisDebugPanel
              jdText={draft.jdText}
              hasParsedResume={Boolean(parsedResume)}
              chunksCount={parsedResume?.chunks?.length ?? 0}
              activeEmbeddingConfig={activeEmbeddingConfig}
              activeChatConfig={activeChatConfig}
              analysisStatus={analysisStatus}
              isAnalyzing={isAnalyzing}
              lastError={error}
            />
          </>
        }
      />
    </div>
  );
}
