import type { AnalysisStep } from "../../types/analysis";
import type { ChatModelConfig } from "../../types/modelConfig";

interface AnalysisStepItemProps {
  step: AnalysisStep;
  index: number;
  activeChatConfig?: ChatModelConfig;
  isLast?: boolean;
}

export function AnalysisStepItem({ step, index, isLast }: AnalysisStepItemProps) {
  const { status, title, description, durationMs, errorMessage, metadata } = step;

  // Keep generated progress copy user-facing while preserving underlying step ids.
  const cleanTitle = title.replace(/^步骤\s*\d+[:：]\s*/, "");
  const displayTitle = step.id === "gemini_analysis"
    ? `步骤 ${index + 1}：生成岗位匹配分析`
    : step.id === "agent_resume"
    ? `步骤 ${index + 1}：简历定向优化`
    : `步骤 ${index + 1}：${cleanTitle}`;
  const displayDescription = step.id === "gemini_analysis"
    ? `根据 JD 和匹配到的经历生成投递判断、匹配度和简历建议。`
    : step.id === "agent_resume"
    ? `正在逐段调整简历，并核对表述是否有真实经历支撑。`
    : description;

  // Icon based on status
  const getIcon = () => {
    switch (status) {
      case "pending":
        return (
          <div className="step-icon step-icon-pending">
            <span className="step-dot"></span>
          </div>
        );
      case "running":
        return (
          <div className="step-icon step-icon-running">
            <svg className="animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          </div>
        );
      case "success":
        return (
          <div className="step-icon step-icon-success">
            <svg className="icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
          </div>
        );
      case "failed":
        return (
          <div className="step-icon step-icon-failed">
            <svg className="icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          </div>
        );
      case "skipped":
      default:
        return (
          <div className="step-icon step-icon-skipped">
            <span className="step-dash"></span>
          </div>
        );
    }
  };

  // Build metadata tags
  const renderMetadata = () => {
    if (!metadata) return null;
    const items: React.ReactNode[] = [];

    if (metadata.chunksCount !== undefined) {
      if (step.id === "resume_embedding") {
        items.push(
          <span key="chunks">
            简历片段数: <strong>{metadata.embeddedChunksCount ?? 0} / {metadata.chunksCount}</strong>
          </span>
        );
      } else {
        items.push(
          <span key="chunks">
            简历片段数: <strong>{metadata.chunksCount}</strong>
          </span>
        );
      }
    } else if (metadata.embeddedChunksCount !== undefined) {
      items.push(
        <span key="embedded">
          整理数量: <strong>{metadata.embeddedChunksCount}</strong>
        </span>
      );
    }

    if (metadata.retrievedChunksCount !== undefined) {
      items.push(
        <span key="retrieved">
          匹配经历召回: <strong>{metadata.retrievedChunksCount} 个片段</strong>
        </span>
      );
    }

    if (metadata.embeddingModelId) {
      items.push(
        <span key="embeddingModel">
          检索服务: <code>{metadata.embeddingModelId}</code>
        </span>
      );
    }

    if (metadata.chatModelId) {
      items.push(
        <span key="chatModel">
          生成服务: <code>{metadata.chatModelId}</code>
        </span>
      );
    }

    if (metadata.retryCount !== undefined && metadata.retryCount > 0) {
      items.push(
        <span key="retries" className="metadata-highlight-danger">
          由于 503 异常，正在第 <strong>{metadata.retryCount}</strong> 次重试
        </span>
      );
    }

    if (items.length === 0) return null;

    return (
      <div className="step-metadata-tags">
        {items.map((item, idx) => (
          <span key={idx} className="metadata-tag">
            {item}
          </span>
        ))}
      </div>
    );
  };

  // Extra prompt descriptions based on state/id
  const renderExtraHelperInfo = () => {
    if (status === "running") {
      if (step.id === "gemini_analysis") {
        const subState = metadata?.subState;
        const subProgress = metadata?.subProgress ?? 0;

        let subStateText = "正在准备岗位匹配分析...";
        let subStateColor = "var(--muted)";
        if (subState === "checking_constraints") {
          subStateText = "正在核对学历、年限、地点等硬性要求...";
          subStateColor = "var(--info)";
        } else if (subState === "deep_analyzing") {
          subStateText = "正在结合相关经历片段判断技能匹配度...";
          subStateColor = "var(--accent)";
        } else if (subState === "generating_advice") {
          subStateText = "正在整理简历问题和修改建议...";
          subStateColor = "var(--warning)";
        } else if (subState === "building_roadmap") {
          subStateText = "正在整理技能差距、面试准备和学习路径...";
          subStateColor = "var(--success)";
        } else if (subState === "completed") {
          subStateText = "分析完成，即将展示结果...";
          subStateColor = "var(--success)";
        }

        return (
          <div className="analysis-substate-wrapper" style={{ marginTop: "8px" }}>
            <p className="step-helper-text accent-text" style={{ color: subStateColor, fontWeight: 500, fontSize: "13px", margin: "4px 0", display: "flex", alignItems: "center", gap: "6px" }}>
              {subStateText}
            </p>
            <div className="step-progress-bar-container" style={{ height: "6px", background: "rgba(0,0,0,0.06)", borderRadius: "3px", overflow: "hidden", marginTop: "6px" }}>
              <div
                className="step-progress-bar"
                style={{
                  width: `${subProgress}%`,
                  background: subStateColor,
                  boxShadow: `0 0 4px ${subStateColor}`,
                  transition: "width 0.4s ease-out, background-color 0.4s ease",
                  height: "100%"
                }}
              />
            </div>
          </div>
        );
      }
      if (step.id === "resume_embedding" && metadata?.chunksCount) {
        const pct = Math.round(((metadata.embeddedChunksCount ?? 0) / metadata.chunksCount) * 100);
        return (
          <div className="step-progress-bar-container">
            <div className="step-progress-bar" style={{ width: `${pct}%` }}></div>
          </div>
        );
      }
    }
    return null;
  };

  return (
    <div className={`analysis-step-item step-status-${status}`}>
      <div className="step-left">
        {getIcon()}
        {!isLast && <div className="step-timeline-connector"></div>}
      </div>
      <div className="step-body">
        <div className="step-header">
          <h4 className="step-title">{displayTitle}</h4>
          {durationMs !== undefined && durationMs > 0 && (
            <span className="step-duration">{(durationMs / 1000).toFixed(2)}s</span>
          )}
        </div>
        <p className="step-description">{displayDescription}</p>
        {renderExtraHelperInfo()}
        {renderMetadata()}
        {errorMessage && (
          <div className="step-error-card">
            <svg className="error-icon" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <div className="error-body">
              <strong>分析出错：</strong>
              <span>{errorMessage}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
