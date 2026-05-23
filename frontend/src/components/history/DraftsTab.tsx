import type { AnalysisDraft } from "../../types/analysisDraft";
import { EmptyState } from "../ui/EmptyState";

interface DraftsTabProps {
  drafts: AnalysisDraft[];
  onRestore: (draft: AnalysisDraft) => void;
  onClone: (draft: AnalysisDraft) => void;
  onDelete: (id: string) => void;
  onNewAnalysis: () => void;
}

export function DraftsTab({
  drafts,
  onRestore,
  onClone,
  onDelete,
  onNewAnalysis,
}: DraftsTabProps) {
  // Filter out successfully converted drafts from this view
  const safeDrafts = drafts ?? [];
  const activeDrafts = safeDrafts.filter((d) => d && d.status !== "converted_to_history");

  if (!activeDrafts.length) {
    return (
      <EmptyState
        title="暂无未完成的草稿"
        description="填写分析表单或当分析意外中断时，数据将以草稿形式保存在这里。"
        actionLabel="新建分析"
        onAction={onNewAnalysis}
      />
    );
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "analysis_failed":
        return <span className="draft-badge badge-failed">分析失败</span>;
      case "ready_to_analyze":
        return <span className="draft-badge badge-ready">可继续分析</span>;
      case "draft":
      default:
        return <span className="draft-badge badge-neutral">普通草稿</span>;
    }
  };

  const getStepChineseName = (stepId?: string) => {
    if (!stepId) return "未知步骤";
    const steps: Record<string, string> = {
      validate: "检查输入与配置",
      resume_embedding: "向量化简历片段",
      jd_embedding: "向量化岗位 JD",
      retrieve_chunks: "检索最相关片段",
      gemini_analysis: "调用 Gemini 分析",
      save_history: "保存分析记录",
      render_result: "渲染分析结果",
    };
    return steps[stepId] || stepId;
  };

  return (
    <div className="drafts-tab-container">
      <div className="drafts-list-header">
        <h3>未完成的分析草稿 ({activeDrafts.length})</h3>
        <p className="sub-label">分析意外中断或手动保存的表单数据，支持一键载入恢复。</p>
      </div>

      <div className="drafts-grid">
        {activeDrafts.map((draft) => {
          const hasResume = Boolean(draft.resumeFile);
          const hasParsed = Boolean(draft.parsedResume);
          const jdWordCount = draft.jdText?.trim().length || 0;

          return (
            <div key={draft.id} className="draft-item-card">
              <div className="draft-card-main">
                <div className="draft-card-header">
                  <div className="draft-title-area">
                    <h4>
                      {draft.companyName || "未名公司"}
                      <span className="title-separator">/</span>
                      <span className="job-title">{draft.jobTitle || "未填岗位"}</span>
                    </h4>
                    <span className="updated-time">
                      更新于: {new Date(draft.updatedAt).toLocaleString()}
                    </span>
                  </div>
                  {getStatusBadge(draft.status)}
                </div>

                <div className="draft-card-body">
                  <div className="draft-meta-info">
                    <span className="meta-pill">
                      JD 长度: <strong>{jdWordCount} 字</strong>
                    </span>
                    <span className="meta-pill">
                      简历:{" "}
                      <strong>
                        {hasResume ? (
                          hasParsed ? (
                            <span className="text-success">已解析 ({draft.parsedResume?.chunks?.length || 0} chunks)</span>
                          ) : (
                            <span className="text-warning">已选择未解析</span>
                          )
                        ) : (
                          <span className="text-muted">未上传</span>
                        )}
                      </strong>
                    </span>
                    {draft.notes && (
                      <p className="draft-notes-preview">
                        <strong>备注:</strong> {draft.notes}
                      </p>
                    )}
                  </div>

                  {draft.status === "analysis_failed" && draft.lastAnalysisAttempt && (
                    <div className="draft-error-block">
                      <div className="error-header">
                        <span className="error-step">
                          失败于: <strong>{getStepChineseName(draft.lastAnalysisAttempt.failedStep)}</strong>
                        </span>
                      </div>
                      <p className="error-message-text">
                        原因: {draft.lastAnalysisAttempt.errorMessage || "网络调用超时或模型未配置"}
                      </p>
                    </div>
                  )}
                </div>
              </div>

              <div className="draft-card-actions">
                <button
                  type="button"
                  className="btn-action-restore"
                  onClick={() => onRestore(draft)}
                >
                  继续分析
                </button>
                <button
                  type="button"
                  className="btn-action-clone"
                  onClick={() => onClone(draft)}
                >
                  复制新分析
                </button>
                <button
                  type="button"
                  className="btn-action-delete"
                  onClick={() => {
                    if (window.confirm("确定要删除这篇草稿吗？此操作无法撤销。")) {
                      onDelete(draft.id);
                    }
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
