import { useState } from "react";
import type { AnalysisRunStatus, AnalysisStep, AnalysisStepId, AnalysisStepStatus } from "../types/analysis";

export const INITIAL_STEPS: { id: AnalysisStepId; title: string; description: string }[] = [
  {
    id: "validate",
    title: "步骤 1：检查输入和模型配置",
    description: "确认 JD、简历解析结果、Doubao 向量模型和 Gemini 模型配置可用。",
  },
  {
    id: "resume_embedding",
    title: "步骤 2：向量化简历片段",
    description: "使用 Doubao Multimodal Embedding 将简历 chunks 转为向量。",
  },
  {
    id: "jd_embedding",
    title: "步骤 3：向量化岗位 JD",
    description: "将岗位 JD 转为向量，用于后续相似度检索。",
  },
  {
    id: "retrieve_chunks",
    title: "步骤 4：检索相关简历片段",
    description: "根据 JD 向量从简历 chunks 中召回最相关的经历片段。",
  },
  {
    id: "gemini_analysis",
    title: "步骤 5：生成岗位匹配分析",
    description: "使用 Gemini 基于 JD 和检索片段生成投递决策、匹配度和简历建议。",
  },
  {
    id: "save_history",
    title: "步骤 6：保存历史记录",
    description: "保存本次分析结果、模型使用信息和引用的简历片段。",
  },
  {
    id: "render_result",
    title: "步骤 7：渲染分析结果",
    description: "展示投递决策、匹配度拆解、简历改造建议和学习路线。",
  }
];

export function getInitialAnalysisSteps(): AnalysisStep[] {
  return INITIAL_STEPS.map(step => ({
    ...step,
    status: "pending" as AnalysisStepStatus
  }));
}

export function useAnalysisProgress() {
  const [status, setStatus] = useState<AnalysisRunStatus>("idle");
  const [steps, setSteps] = useState<AnalysisStep[]>(getInitialAnalysisSteps());
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  function resetProgress() {
    setStatus("idle");
    setSteps(getInitialAnalysisSteps());
    setError(null);
    setIsRunning(false);
  }

  function setRunningStep(stepId: AnalysisStepId) {
    setIsRunning(true);
    setSteps(prev =>
      prev.map(step => {
        if (step.id === stepId) {
          return {
            ...step,
            status: "running" as AnalysisStepStatus,
            startedAt: new Date().toISOString(),
            errorMessage: undefined
          };
        }
        return step;
      })
    );
  }

  function completeStep(stepId: AnalysisStepId, metadata?: any) {
    setSteps(prev =>
      prev.map(step => {
        if (step.id === stepId) {
          const finishedAt = new Date().toISOString();
          const startedAt = step.startedAt || finishedAt;
          const durationMs = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
          return {
            ...step,
            status: "success" as AnalysisStepStatus,
            finishedAt,
            durationMs,
            metadata: {
              ...step.metadata,
              ...metadata
            }
          };
        }
        return step;
      })
    );
  }

  function failStep(stepId: AnalysisStepId, errorMessage: string) {
    setSteps(prev =>
      prev.map(step => {
        if (step.id === stepId) {
          const finishedAt = new Date().toISOString();
          const startedAt = step.startedAt || finishedAt;
          const durationMs = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
          return {
            ...step,
            status: "failed" as AnalysisStepStatus,
            finishedAt,
            durationMs,
            errorMessage
          };
        }
        return step;
      })
    );
  }

  function skipStep(stepId: AnalysisStepId) {
    setSteps(prev =>
      prev.map(step => {
        if (step.id === stepId) {
          return {
            ...step,
            status: "skipped" as AnalysisStepStatus
          };
        }
        return step;
      })
    );
  }

  function updateStepMetadata(stepId: AnalysisStepId, metadata: any) {
    setSteps(prev =>
      prev.map(step => {
        if (step.id === stepId) {
          return {
            ...step,
            metadata: {
              ...step.metadata,
              ...metadata
            }
          };
        }
        return step;
      })
    );
  }

  return {
    status,
    steps,
    error,
    isRunning,
    resetProgress,
    setRunningStep,
    completeStep,
    failStep,
    skipStep,
    updateStepMetadata,
    setStatus,
    setError,
    setIsRunning,
    setSteps
  };
}
