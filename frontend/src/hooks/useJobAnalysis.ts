import { useState } from "react";
import type { AnalysisResult, AnalysisRunStatus, AnalysisStep, AnalysisStepId } from "../types/analysis";
import type { JobDraft } from "../types/job";
import type { ChatModelConfig, EmbeddingModelConfig } from "../types/modelConfig";
import type { ParsedResume, ResumeChunk, UploadedResumeFile } from "../types/resume";
import { embedChunksWithConfig, embedTextWithConfig, retrieveTopChunksByCosineSimilarity } from "../services/embeddingClient";
import { analyzeJobWithChatConfig } from "../services/chatClient";
import { parseJobDescription } from "../services/jobParser";
import { retrieveEvidenceForRequirements } from "../services/evidenceRetriever";
import { checkHardConstraints } from "../services/hardConstraintsChecker";
import { useAnalysisProgress } from "./useAnalysisProgress";
import { safeUUID } from "../utils/uuid";

export const ANALYSIS_STEPS = [
  "检查输入与配置",
  "向量化简历片段",
  "向量化岗位 JD",
  "检索最相关片段",
  "调用 Gemini 分析",
  "保存分析记录"
];

export type AnalysisRunResult =
  | {
      ok: true;
      result: AnalysisResult;
      savedHistoryId?: string;
    }
  | {
      ok: false;
      failedStep: AnalysisStepId;
      errorMessage: string;
      partialResult?: {
        parsedJD?: any;
        retrievedChunks?: ResumeChunk[];
        requirementMatches?: any;
        hardConstraintsResult?: any;
      };
    };

interface RunAnalysisInput {
  draft: JobDraft;
  resumeFile: UploadedResumeFile | null;
  parsedResume: ParsedResume | null;
  chunks: ResumeChunk[];
  embeddingConfig: EmbeddingModelConfig | null | undefined;
  chatConfig: ChatModelConfig | null | undefined;
  activeEmbeddingConfigId?: string;
  activeChatConfigId?: string;
  sourceDraftId?: string;
  onSaveHistory?: (result: AnalysisResult) => void | Promise<void>;
  vectorResultCache?: {
    parsedJD?: any;
    retrievedChunks?: ResumeChunk[];
    requirementMatches?: any;
    hardConstraintsResult?: any;
  };
}

export function toUserFriendlyAnalysisError(
  error: any,
  stepId?: AnalysisStepId,
  embeddingConfig?: EmbeddingModelConfig | null,
  chatConfig?: ChatModelConfig | null
): string {
  if (!error) return "未知分析错误";

  const message = error.message || String(error);
  if (stepId === "validate") {
    return message;
  }

  const lowercaseMsg = message.toLowerCase();
  const status = error.status;
  const responseBody = error.responseBody || "";
  const lowercaseBody = responseBody.toLowerCase();
  const errorType = error.errorType;

  const chatModelName = chatConfig?.name?.trim() || chatConfig?.modelId?.trim() || "Gemini";

  // Gemini / LLM specific errors (from errorType or messages)
  if (errorType === "high_demand" || lowercaseMsg.includes("high demand") || lowercaseMsg.includes("temporary") || lowercaseBody.includes("temporary") || lowercaseMsg.includes("503")) {
    return `${chatModelName} 模型高负载，请稍后重试或切换备用模型`;
  }
  if (errorType === "rate_limit" || status === 429 || lowercaseMsg.includes("rate_limit") || lowercaseMsg.includes("too many requests") || lowercaseMsg.includes("429")) {
    return `${chatModelName} 请求限流，请稍后再试`;
  }
  const isAuthError =
    errorType === "auth" ||
    status === 401 ||
    status === 403 ||
    (lowercaseMsg.includes("api key") && !lowercaseMsg.includes("为空")) ||
    lowercaseMsg.includes("auth") ||
    lowercaseMsg.includes("permission") ||
    lowercaseMsg.includes("401") ||
    lowercaseMsg.includes("403");

  if (isAuthError) {
    const isEmbeddingStep = stepId === "resume_embedding" || stepId === "jd_embedding" || stepId === "retrieve_chunks";
    const isChatStep = stepId === "gemini_analysis";

    if (isEmbeddingStep) {
      const provider = embeddingConfig?.provider || "doubao-multimodal";
      const configName = embeddingConfig?.name || "向量模型";
      if (provider.includes("doubao")) {
        return "Doubao API Key 无效或无权限，请确认您的 API Key 并重试";
      }
      return `${configName} API Key 无效或无权限，请确认您的 API Key 并重试`;
    }

    if (isChatStep) {
      const provider = chatConfig?.provider || "gemini";
      const configName = chatConfig?.name || "大语言模型";
      if (provider === "gemini") {
        return `${chatModelName} API Key 无效或无权限，请检查配置`;
      }
      return `${configName} API Key 无效或无权限，请确认您的 API Key 并重试`;
    }

    if (lowercaseMsg.includes("gemini") || lowercaseMsg.includes("generative")) {
      return `${chatModelName} API Key 无效或无权限，请检查配置`;
    }
    if (lowercaseMsg.includes("doubao") || lowercaseMsg.includes("ark")) {
      return "Doubao API Key 无效或无权限，请确认您的 API Key 并重试";
    }
    return "API Key 无效或无权限，请确认您的 API Key 并重试";
  }
  if (errorType === "output_truncated_by_thinking" || message.includes("MAX_TOKENS") || message.includes("被截断")) {
    return `${chatModelName} 输出被截断，请提高 Max Output Tokens 或降低 thinking level`;
  }
  if (errorType === "invalid_json" || lowercaseMsg.includes("invalid_json") || lowercaseMsg.includes("非 json 内容") || lowercaseMsg.includes("invalid json") || lowercaseMsg.includes("自然语言")) {
    return `${chatModelName} 返回非 JSON 格式数据，请检查 JSON mode 或尝试切换模型`;
  }

  // Doubao specific errors
  if (status === 404 || lowercaseMsg.includes("not_found") || lowercaseBody.includes("notfound") || lowercaseBody.includes("not_found") || lowercaseMsg.includes("404")) {
    return "模型或 Endpoint 不存在，请确保在火山方舟已开通该模型且 Endpoint ID 填写正确";
  }
  if (lowercaseMsg.includes("does not support this api") || lowercaseBody.includes("does not support this api")) {
    return "模型和接口不匹配，请确认已开通多模态向量服务，并使用 /embeddings/multimodal 接口";
  }
  if (lowercaseMsg.includes("未找到 data.embedding") || lowercaseBody.includes("embedding missing") || lowercaseMsg.includes("embedding")) {
    return "Doubao 返回结构异常，未找到 data.embedding";
  }

  // General Network/Abort errors
  if (lowercaseMsg.includes("abort") || lowercaseMsg.includes("timeout") || lowercaseMsg.includes("超时")) {
    return "请求超时，请稍后重试";
  }
  if (lowercaseMsg.includes("network") || lowercaseMsg.includes("fetch") || lowercaseMsg.includes("网络")) {
    return "网络错误，请检查代理或网络环境";
  }

  return message;
}

export function useJobAnalysis() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const progress = useAnalysisProgress();

  async function runAnalysis(input: RunAnalysisInput): Promise<AnalysisRunResult> {
    progress.resetProgress();
    progress.setIsRunning(true);
    progress.setError(null);
    progress.setStatus("validating");
    progress.setRunningStep("validate");

    const recordId = input.sourceDraftId || safeUUID();

    try {
      console.info("[analysis] starting background analysis via API for record:", recordId);

      // 1. JD empty check
      if (!input.draft.jdText || !input.draft.jdText.trim()) {
        throw new Error("请先输入岗位 JD。");
      }
      if (input.draft.jdText.trim().length < 80) {
        throw new Error("JD 内容太短，建议粘贴完整岗位职责 and 任职要求。");
      }

      // 2. Resume missing check
      if (!input.resumeFile) {
        throw new Error("请先上传简历文件。");
      }

      // 3. Resume parsed check (isReady)
      if (!input.parsedResume) {
        throw new Error("简历还在解析中，请稍后再开始分析。");
      }

      // 4. Resume chunks empty check
      if (!input.chunks || !input.chunks.length) {
        throw new Error("简历解析结果为空，请重新上传或检查文件内容。");
      }

      // 5. Dangling embedding config check
      if (input.activeEmbeddingConfigId && !input.embeddingConfig) {
        throw new Error("当前默认模型配置不存在，请重新选择模型配置。");
      }

      // 6. Dangling chat config check
      if (input.activeChatConfigId && !input.chatConfig) {
        throw new Error("当前默认模型配置不存在，请重新选择模型配置。");
      }

      // 7. Missing embedding config
      if (!input.embeddingConfig) {
        throw new Error("请先配置向量模型。");
      }

      // 8. Missing chat config
      if (!input.chatConfig) {
        throw new Error("请先配置大语言模型。");
      }

      // Successfully validated
      progress.completeStep("validate", {
        chunksCount: input.chunks.length,
        embeddingModelId: input.embeddingConfig.modelId,
        chatModelId: input.chatConfig.modelId
      });

      // Start background task in backend
      const response = await fetch("/api/analysis/background-start", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          record_id: recordId,
          draft: input.draft,
          resume_file_id: input.resumeFile.id,
          embedding_config_id: input.embeddingConfig.id,
          chat_config_id: input.chatConfig.id,
        })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`启动后台分析失败: ${errorText || response.statusText}`);
      }

      const startRes = await response.json();
      console.info("[analysis] Background task queued:", startRes);

      // Poll task status until success or failed
      let isCompleted = false;
      let finalResultObj: AnalysisResult | null = null;
      let pollCount = 0;

      while (!isCompleted) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        pollCount++;

        const pollResponse = await fetch(`/api/history/${recordId}`);
        if (!pollResponse.ok) {
          console.warn("[analysis] Polling status failed, retrying...");
          continue;
        }

        const pollData = await pollResponse.json();
        const record = pollData.record;
        if (!record) {
          throw new Error("分析历史记录未创建或被删除。");
        }

        // Sync steps check-list checklist UI
        if (Array.isArray(record.steps)) {
          progress.setSteps(record.steps);
        }

        if (record.status === "watching") {
          isCompleted = true;
          finalResultObj = record;
        } else if (record.status === "failed") {
          isCompleted = true;
          throw new Error(record.errorMessage || "大模型分析执行失败。");
        } else {
          progress.setStatus(record.status === "pending" ? "validating" : record.status as any);
        }

        // Max polling timeout (10 minutes)
        if (pollCount > 300) {
          throw new Error("分析任务响应超时，可在退出浏览器后去历史记录中查看分析结果。");
        }
      }

      if (!finalResultObj) {
        throw new Error("未接收到正确的最终大模型分析报告。");
      }

      // Step 7: render_result
      progress.completeStep("save_history");
      progress.setRunningStep("render_result");
      setResult(finalResultObj);
      progress.completeStep("render_result");

      progress.setStatus("success");
      return { ok: true, result: finalResultObj };
    } catch (caught: any) {
      console.error("[analysis] background analysis failed:", caught);
      const friendlyError = toUserFriendlyAnalysisError(caught, "gemini_analysis", input.embeddingConfig, input.chatConfig);
      
      progress.setError(friendlyError);
      progress.setStatus("failed");
      return {
        ok: false,
        failedStep: "gemini_analysis",
        errorMessage: friendlyError
      };
    } finally {
      progress.setIsRunning(false);
    }
  }

  function setExistingResult(nextResult: AnalysisResult | null) {
    setResult(nextResult);
    progress.resetProgress();
  }

  return {
    result,
    isAnalyzing: progress.isRunning,
    progressStep: progress.steps.findIndex(s => s.status === "running"),
    steps: progress.steps,
    analysisStatus: progress.status,
    error: progress.error || "",
    runAnalysis,
    resetProgress: progress.resetProgress,
    setExistingResult,
  };
}
