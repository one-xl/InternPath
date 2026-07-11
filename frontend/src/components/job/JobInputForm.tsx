import type { FormEvent } from "react";
import type { ReactNode } from "react";
import type { JobDraft, JobLevel, WorkMode } from "../../types/job";
import type { ChatModelConfig, EmbeddingModelConfig } from "../../types/modelConfig";
import { isDoubaoMultimodalEmbeddingProvider } from "../../types/modelConfig";
import type { ParsedResume, ResumeFileStatus, UploadedResumeFile } from "../../types/resume";
import type { AnalysisRunStatus } from "../../types/analysis";
import { levelLabels, workModeLabels } from "../../utils/format";
import { ResumeUpload } from "../resume/ResumeUpload";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { ErrorState } from "../ui/ErrorState";
import { JDTextArea } from "./JDTextArea";

interface JobInputFormProps {
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
  analysisStatus?: AnalysisRunStatus;
  error: string;
  onChange: (patch: Partial<JobDraft>) => void;
  onSelectResume: (file: File) => void;
  onSelectSavedResume: (parsed: ParsedResume) => void;
  onRetryResume: () => void;
  onRemoveResume: () => void;
  onGoSettings: () => void;
  onSubmit: () => void;
  onSaveDraft: () => void;
  onViewDrafts: () => void;
  onClearForm: () => void;
  sidePanel?: ReactNode;
}

const workModes: WorkMode[] = ["unknown", "remote", "onsite", "hybrid"];
const levels: JobLevel[] = ["intern", "campus", "junior", "middle", "unknown"];

function ModelConfigHint({
  embeddingConfig,
  chatConfig,
  onGoSettings,
}: {
  embeddingConfig?: EmbeddingModelConfig;
  chatConfig?: ChatModelConfig;
  onGoSettings: () => void;
}) {
  return (
    <Card title="当前服务配置" description="本次分析会使用当前启用的检索服务和生成服务。">
      <div className="model-hint-grid">
        <div>
          <span>检索服务</span>
          <strong>{embeddingConfig ? `${embeddingConfig.provider} / ${embeddingConfig.modelId}` : "未配置"}</strong>
          {embeddingConfig && <Badge tone={embeddingConfig.testStatus === "success" ? "success" : "warning"}>{embeddingConfig.testStatus === "success" ? "已测试" : "尚未测试"}</Badge>}
        </div>
        <div>
          <span>生成服务</span>
          <strong>{chatConfig ? `${chatConfig.provider} / ${chatConfig.modelId}` : "未配置"}</strong>
          {chatConfig && <Badge tone={chatConfig.testStatus === "success" ? "success" : "warning"}>{chatConfig.testStatus === "success" ? "已测试" : "尚未测试"}</Badge>}
        </div>
      </div>
      {(!embeddingConfig || !chatConfig) && <p className="settings-warning">{!embeddingConfig ? "请先配置检索服务。" : "请先配置生成服务。"}</p>}
      {embeddingConfig && chatConfig && (embeddingConfig.testStatus !== "success" || chatConfig.testStatus !== "success") && (
        <p className="settings-warning">当前服务尚未全部测试，允许继续，但建议先测试连通性。</p>
      )}
      <Button type="button" variant="secondary" onClick={onGoSettings}>
        去配置
      </Button>
    </Card>
  );
}

export function JobInputForm({
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
  analysisStatus = "idle",
  error,
  onChange,
  onSelectResume,
  onSelectSavedResume,
  onRetryResume,
  onRemoveResume,
  onGoSettings,
  onSubmit,
  onSaveDraft,
  onViewDrafts,
  onClearForm,
  sidePanel,
}: JobInputFormProps) {
  const missingModel = !activeEmbeddingConfig || !activeChatConfig;
  const isButtonDisabled = isAnalyzing || isRetrieving || !draft.jdText.trim() || !resumeFile || missingModel;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!isButtonDisabled) {
      onSubmit();
    }
  }

  const getButtonText = () => {
    if (!isAnalyzing) {
      if (analysisStatus === "success") return "重新分析";
      if (analysisStatus === "failed") return "重试分析";
      return "开始分析";
    }
    switch (analysisStatus) {
      case "validating":
        return "检查中...";
      case "embedding_resume":
        return "向量化简历中...";
      case "embedding_jd":
        return "向量化 JD 中...";
      case "retrieving":
        return "检索片段中...";
      case "analyzing":
        return "生成分析中...";
      case "saving":
        return "保存中...";
      default:
        return "分析中...";
    }
  };

  return (
    <form className="analysis-form" onSubmit={submit}>
      <div className="form-main-content">
        <div className="form-left-col">
          <Card title="岗位信息" description="用于历史检索、匹配度参考和投递复盘。">
            <div className="form-grid">
              <label className="field">
                <span>公司名</span>
                <input value={draft.company} onChange={(event) => onChange({ company: event.target.value })} placeholder="例如：Vercel" />
              </label>
              <label className="field">
                <span>岗位名</span>
                <input value={draft.title} onChange={(event) => onChange({ title: event.target.value })} placeholder="例如：前端实习生" />
              </label>
              <label className="field">
                <span>岗位链接</span>
                <input value={draft.link} onChange={(event) => onChange({ link: event.target.value })} placeholder="可选，用于回溯来源" />
              </label>
              <label className="field">
                <span>地点</span>
                <input value={draft.location} onChange={(event) => onChange({ location: event.target.value })} placeholder="例如：北京 / 远程" />
              </label>
              <label className="field">
                <span>工作模式</span>
                <select value={draft.workMode} onChange={(event) => onChange({ workMode: event.target.value as WorkMode })}>
                  {workModes.map((mode) => (
                    <option key={mode} value={mode}>
                      {workModeLabels[mode]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>岗位级别</span>
                <select value={draft.level} onChange={(event) => onChange({ level: event.target.value as JobLevel, targetType: levelLabels[event.target.value as JobLevel] })}>
                  {levels.map((level) => (
                    <option key={level} value={level}>
                      {levelLabels[level]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>岗位方向</span>
                <input value={draft.jobDirection} onChange={(event) => onChange({ jobDirection: event.target.value })} placeholder="前端 / 全栈 / 数据产品" />
              </label>
              <label className="field">
                <span>求职目标</span>
                <input value={draft.targetType} onChange={(event) => onChange({ targetType: event.target.value })} placeholder="实习 / 校招 / 初级" />
              </label>
            </div>
          </Card>

          <ResumeUpload
            resumeFile={resumeFile}
            parsedResume={parsedResume}
            status={resumeStatus}
            error={resumeError}
            disabled={isAnalyzing || isRetrieving}
            onSelectFile={onSelectResume}
            onSelectSavedResume={onSelectSavedResume}
            onRetry={onRetryResume}
            onRemove={onRemoveResume}
          />

          <Card title="JD 岗位要求描述" description="粘贴完整职责和任职要求，系统会先召回简历片段，再生成结构化判断。">
            <JDTextArea value={draft.jdText} onChange={(jdText) => onChange({ jdText })} />
          </Card>
        </div>

        <div className="form-right-col">
          <ModelConfigHint embeddingConfig={activeEmbeddingConfig} chatConfig={activeChatConfig} onGoSettings={onGoSettings} />
          {sidePanel}
        </div>
      </div>

      <ErrorState message={error || (!resumeReady && resumeFile ? resumeError : "")} />
      <div className="sticky-action">
        <Button variant="primary" disabled={isButtonDisabled}>
          {getButtonText()}
        </Button>
        <Button type="button" variant="secondary" onClick={onSaveDraft} disabled={isAnalyzing || isRetrieving}>
          保存草稿
        </Button>
        <Button type="button" variant="secondary" onClick={onViewDrafts}>
          查看草稿
        </Button>
        <Button type="button" variant="danger" onClick={onClearForm} disabled={isAnalyzing || isRetrieving}>
          清空当前输入
        </Button>
        <span className="save-note">
          {missingModel
            ? "请配置分析与生成服务"
            : !resumeFile
              ? "请上传简历文件"
              : !resumeReady
                ? "请等待简历解析完成"
                : draft.jdText.trim().length < 80
                  ? "请粘贴完整 JD (至少 80 字)"
                  : "已准备好进行分析，点击左侧按钮开始"}
        </span>
      </div>
    </form>
  );
}
