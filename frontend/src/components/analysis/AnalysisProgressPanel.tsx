import React, { useState } from "react";
import type { AnalysisRunStatus, AnalysisStep } from "../../types/analysis";
import type { ChatModelConfig } from "../../types/modelConfig";
import { AnalysisStepItem } from "./AnalysisStepItem";

interface AnalysisProgressPanelProps {
  status: AnalysisRunStatus;
  steps: AnalysisStep[];
  error: string | null;
  onRetry?: () => void;
  draftSaveMessage?: string | null;
  activeChatConfig?: ChatModelConfig;
}

export function getModelName(chatModelId?: string, activeChatConfig?: ChatModelConfig | null): string {
  const modelId = chatModelId || activeChatConfig?.modelId || "";
  const provider = activeChatConfig?.provider || "";
  if (!modelId) return "大语言模型";
  
  if (modelId.toLowerCase().includes("gemini")) return "Gemini";
  if (modelId.toLowerCase().includes("deepseek")) return "DeepSeek";
  if (modelId.toLowerCase().includes("doubao") || modelId.toLowerCase().includes("ark")) return "豆包 Ark";
  if (provider === "gemini") return "Gemini";
  
  return modelId;
}

export function AnalysisProgressPanel({
  status,
  steps,
  error,
  onRetry,
  draftSaveMessage,
  activeChatConfig,
}: AnalysisProgressPanelProps) {
  const [showDebug, setShowDebug] = useState(false);

  if (status === "idle") return null;

  // Title maps
  const getTitle = () => {
    switch (status) {
      case "validating":
        return "正在检查输入和模型配置";
      case "embedding_resume":
        return "正在向量化简历片段";
      case "embedding_jd":
        return "正在向量化岗位 JD";
      case "retrieving":
        return "正在检索相关简历片段";
      case "analyzing":
        const name = getModelName(undefined, activeChatConfig);
        return `正在调用 ${name} 生成分析结果`;
      case "saving":
        return "正在保存分析记录";
      case "success":
        return "分析完成";
      case "failed":
        return "分析失败";
      default:
        return "处理中";
    }
  };

  const currentStep = steps.find(s => s.status === "running");
  const currentStepId = currentStep?.id || "none";

  // Gather metadata values from steps
  const validateStep = steps.find(s => s.id === "validate");
  const resumeStep = steps.find(s => s.id === "resume_embedding");
  const retrieveStep = steps.find(s => s.id === "retrieve_chunks");

  const chunksCount = validateStep?.metadata?.chunksCount ?? resumeStep?.metadata?.chunksCount ?? 0;
  const embeddedChunksCount = resumeStep?.metadata?.embeddedChunksCount ?? 0;
  const retrievedChunksCount = retrieveStep?.metadata?.retrievedChunksCount ?? 0;
  const embeddingModelId = validateStep?.metadata?.embeddingModelId || "未配置";
  const chatModelId = validateStep?.metadata?.chatModelId || "未配置";

  return (
    <div className="analysis-progress-card">
      <div className="progress-card-header">
        <div className="header-status-indicator">
          {status !== "success" && status !== "failed" && (
            <div className="pulse-spinner"></div>
          )}
          {status === "success" && (
            <span className="badge-dot-success"></span>
          )}
          {status === "failed" && (
            <span className="badge-dot-failed"></span>
          )}
          <h3 className="progress-title">{getTitle()}</h3>
        </div>
        <span className="status-label">{status.toUpperCase()}</span>
      </div>

      <div className="steps-container">
        {steps.map((step, index) => (
          <AnalysisStepItem key={step.id} step={step} index={index} activeChatConfig={activeChatConfig} />
        ))}
      </div>

      {status === "failed" && onRetry && (
        <div className="retry-action-area">
          {draftSaveMessage && (
            <div className={`draft-notice-bar ${draftSaveMessage.includes("失败") ? "notice-error" : "notice-success"}`}>
              <span>{draftSaveMessage}</span>
            </div>
          )}
          <button type="button" className="btn-retry" onClick={onRetry}>
            <svg className="btn-icon" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 110 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
            </svg>
            重新尝试分析
          </button>
        </div>
      )}

      {/* Foldable Debug Panel */}
      <div className="debug-foldable-area">
        <button
          type="button"
          className="debug-toggle-btn"
          onClick={() => setShowDebug(!showDebug)}
        >
          <span>{showDebug ? "收起调试信息" : "展开调试信息"}</span>
          <svg
            className={`chevron-icon ${showDebug ? "rotated" : ""}`}
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </button>

        {showDebug && (
          <div className="debug-content-grid">
            <div className="debug-item">
              <span className="debug-label">analysisStatus</span>
              <span className="debug-value font-mono">{status}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">currentStepId</span>
              <span className="debug-value font-mono">{currentStepId}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">chunksCount</span>
              <span className="debug-value font-mono">{chunksCount}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">embeddedChunksCount</span>
              <span className="debug-value font-mono">{embeddedChunksCount}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">retrievedChunksCount</span>
              <span className="debug-value font-mono">{retrievedChunksCount}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">embeddingModelId</span>
              <span className="debug-value font-mono">{embeddingModelId}</span>
            </div>
            <div className="debug-item">
              <span className="debug-label">chatModelId</span>
              <span className="debug-value font-mono">{chatModelId}</span>
            </div>
            {error && (
              <div className="debug-item debug-item-full">
                <span className="debug-label">lastError</span>
                <span className="debug-value font-mono text-danger">{error}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
