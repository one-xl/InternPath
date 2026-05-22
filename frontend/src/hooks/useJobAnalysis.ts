import { useState } from "react";
import type { AnalysisResult, AnalysisRunStatus, AnalysisStep } from "../types/analysis";
import type { JobDraft } from "../types/job";
import type { ChatModelConfig, EmbeddingModelConfig } from "../types/modelConfig";
import type { ParsedResume, ResumeChunk, UploadedResumeFile } from "../types/resume";
import { embedChunksWithConfig, embedTextWithConfig, retrieveTopChunksByCosineSimilarity } from "../services/embeddingClient";
import { analyzeJobWithChatConfig } from "../services/chatClient";
import { useAnalysisProgress } from "./useAnalysisProgress";

export const ANALYSIS_STEPS = [
  "检查输入与配置",
  "向量化简历片段",
  "向量化岗位 JD",
  "检索最相关片段",
  "调用 Gemini 分析",
  "保存分析记录"
];

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
}

export function toUserFriendlyAnalysisError(error: any): string {
  if (!error) return "未知分析错误";

  const message = error.message || String(error);
  const lowercaseMsg = message.toLowerCase();
  const status = error.status;
  const responseBody = error.responseBody || "";
  const lowercaseBody = responseBody.toLowerCase();
  const errorType = error.errorType;

  // Gemini specific errors (from errorType or messages)
  if (errorType === "high_demand" || lowercaseMsg.includes("high demand") || lowercaseMsg.includes("temporary") || lowercaseBody.includes("temporary") || lowercaseMsg.includes("503")) {
    return "Gemini 模型高负载，请稍后重试或切换备用模型";
  }
  if (errorType === "rate_limit" || status === 429 || lowercaseMsg.includes("rate_limit") || lowercaseMsg.includes("too many requests") || lowercaseMsg.includes("429")) {
    return "Gemini 请求限流，请稍后再试";
  }
  if (errorType === "auth" || status === 401 || status === 403 || lowercaseMsg.includes("api key") || lowercaseMsg.includes("auth") || lowercaseMsg.includes("permission") || lowercaseMsg.includes("401") || lowercaseMsg.includes("403")) {
    if (lowercaseMsg.includes("gemini") || lowercaseMsg.includes("generative")) {
      return "Gemini API Key 无效或无权限，请检查配置";
    }
    return "Doubao API Key 无效或无权限，请确认您的 API Key 并重试";
  }
  if (errorType === "output_truncated_by_thinking" || errorType === "invalid_json" || message.includes("MAX_TOKENS") || message.includes("被截断")) {
    return "Gemini 输出被截断，请提高 Max Output Tokens 或降低 thinking level";
  }
  if (errorType === "invalid_json" || lowercaseMsg.includes("invalid_json") || lowercaseMsg.includes("非 json 内容") || lowercaseMsg.includes("invalid json")) {
    return "Gemini 返回非 JSON 格式数据，请检查 JSON mode 或切换模型";
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

  async function runAnalysis(input: RunAnalysisInput): Promise<AnalysisResult | null> {
    progress.resetProgress();
    progress.setIsRunning(true);
    progress.setError(null);
    progress.setStatus("validating");
    progress.setRunningStep("validate");

    try {
      console.info("[analysis] start clicked");
      console.info("[analysis] validation", {
        hasJdText: Boolean(input.draft.jdText?.trim()),
        hasParsedResume: Boolean(input.parsedResume),
        chunksCount: input.chunks?.length ?? 0,
        hasEmbeddingConfig: Boolean(input.embeddingConfig),
        hasChatConfig: Boolean(input.chatConfig),
        embeddingProvider: input.embeddingConfig?.provider,
        embeddingModelId: input.embeddingConfig?.modelId,
        chatProvider: input.chatConfig?.provider,
        chatModelId: input.chatConfig?.modelId
      });

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
        throw new Error("请先配置 Doubao 多模态向量模型。");
      }

      // 8. Missing chat config
      if (!input.chatConfig) {
        throw new Error("请先配置 Gemini 模型。");
      }

      // 9. API Key empty check
      if (!input.embeddingConfig.apiKey.trim() || !input.chatConfig.apiKey.trim()) {
        throw new Error("模型 API Key 为空，请先完成模型配置。");
      }

      // 10. Check if the embedding provider is doubao-multimodal
      if (input.embeddingConfig.provider !== "doubao-multimodal") {
        throw new Error("请先配置 Doubao 多模态向量模型。");
      }

      // Successfully validated
      progress.completeStep("validate", {
        chunksCount: input.chunks.length,
        embeddingModelId: input.embeddingConfig.modelId,
        chatModelId: input.chatConfig.modelId
      });

      // Step 2: embedding_resume
      progress.setStatus("embedding_resume");
      progress.setRunningStep("resume_embedding");
      
      progress.updateStepMetadata("resume_embedding", {
        embeddedChunksCount: 0,
        chunksCount: input.chunks.length
      });

      const embeddedChunks = await embedChunksWithConfig(
        input.chunks,
        input.embeddingConfig,
        {
          onProgress: ({ completed, total }) => {
            progress.updateStepMetadata("resume_embedding", {
              embeddedChunksCount: completed,
              chunksCount: total
            });
          }
        }
      );
      progress.completeStep("resume_embedding", {
        embeddedChunksCount: embeddedChunks.length
      });

      // Step 3: embedding_jd
      progress.setStatus("embedding_jd");
      progress.setRunningStep("jd_embedding");
      const jdEmbedding = await embedTextWithConfig(input.draft.jdText, input.embeddingConfig);
      progress.completeStep("jd_embedding");

      // Step 4: retrieving
      progress.setStatus("retrieving");
      progress.setRunningStep("retrieve_chunks");
      const retrievedChunks = retrieveTopChunksByCosineSimilarity({
        jdEmbedding,
        chunks: embeddedChunks,
        topK: 8,
      });
      progress.completeStep("retrieve_chunks", {
        retrievedChunksCount: retrievedChunks.length
      });

      if (!retrievedChunks.length) {
        throw new Error("没有检索到相关简历片段，请检查简历解析结果或 JD 内容。");
      }

      // Step 5: analyzing
      progress.setStatus("analyzing");
      progress.setRunningStep("gemini_analysis");
      const chatResult = await analyzeJobWithChatConfig({
        jdText: input.draft.jdText,
        targetType: input.draft.targetType || input.draft.level,
        jobDirection: input.draft.jobDirection || input.draft.title,
        retrievedChunks,
        config: input.chatConfig,
      });
      progress.completeStep("gemini_analysis", {
        retryCount: (chatResult as any).retryCount || 0
      });

      // Step 6: saving
      progress.setStatus("saving");
      progress.setRunningStep("save_history");
      await new Promise((resolve) => window.setTimeout(resolve, 500));

      const averageScore = Math.round(
        retrievedChunks.reduce((sum, chunk) => sum + (chunk.score ?? 0), 0) / retrievedChunks.length,
      );

      const nextResult: AnalysisResult = {
        id: crypto.randomUUID(),
        createdAt: new Date().toISOString(),
        draft: input.draft,
        sourceDraftId: input.sourceDraftId,
        resumeFile: { ...input.resumeFile, status: "indexed" } as any,
        parsedResume: {
          ...input.parsedResume,
          chunks: input.parsedResume.chunks.map((chunk) => ({ ...chunk, embedding: undefined })),
        } as any,
        retrievedResumeChunks: retrievedChunks.map((chunk) => ({ ...chunk, embedding: undefined })),
        retrievalSummary: `使用 ${input.embeddingConfig.provider} / ${input.embeddingConfig.modelId} 召回 ${retrievedChunks.length} 个简历片段。`,
        retrievalScore: averageScore,
        modelUsage: {
          embeddingProvider: input.embeddingConfig.provider,
          embeddingModelId: input.embeddingConfig.modelId,
          chatProvider: input.chatConfig.provider,
          chatModelId: chatResult.chatModelId || input.chatConfig.modelId,
          retrievalTopK: 8,
          createdAt: new Date().toISOString(),
        },
        ...chatResult,
      };
      progress.completeStep("save_history");

      // Step 7: render_result
      progress.setRunningStep("render_result");
      setResult(nextResult);
      progress.completeStep("render_result");

      progress.setStatus("success");
      return nextResult;
    } catch (caught: any) {
      console.error("[analysis] failed", caught);
      const friendlyError = toUserFriendlyAnalysisError(caught);
      
      const runningStep = progress.steps.find(s => s.status === "running");
      if (runningStep) {
        progress.failStep(runningStep.id, friendlyError);
      } else {
        progress.failStep("validate", friendlyError);
      }

      progress.setError(friendlyError);
      progress.setStatus("failed");
      return null;
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
