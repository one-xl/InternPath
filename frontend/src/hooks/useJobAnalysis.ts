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

    let currentStepId: AnalysisStepId = "validate";
    let parsedJD: any = undefined;
    let requirementMatchesResult: any = undefined;
    let retrievedChunks: ResumeChunk[] = [];
    let hardConstraintsResult: any = undefined;

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
        throw new Error("请先配置向量模型。");
      }

      // 8. Missing chat config
      if (!input.chatConfig) {
        throw new Error("请先配置大语言模型。");
      }

      const chatConfigWithHighTimeout = {
        ...input.chatConfig,
        timeoutMs: Math.max(input.chatConfig.timeoutMs ?? 300000, 300000)
      };

      // 10. Check if the embedding provider is supported
      if (
        input.embeddingConfig.provider !== "doubao" &&
        input.embeddingConfig.provider !== "doubao-multimodal" &&
        input.embeddingConfig.provider !== "doubao-text" &&
        input.embeddingConfig.provider !== "openai-compatible" &&
        input.embeddingConfig.provider !== "custom"
      ) {
        throw new Error("不支持的向量模型 Provider 配置。");
      }

      // 11. Check if the chat provider is supported
      if (
        input.chatConfig.provider !== "gemini" &&
        input.chatConfig.provider !== "openai-compatible" &&
        input.chatConfig.provider !== "custom"
      ) {
        throw new Error("不支持的大语言模型 Provider 配置。");
      }

      // Successfully validated
      progress.completeStep("validate", {
        chunksCount: input.chunks.length,
        embeddingModelId: input.embeddingConfig.modelId,
        chatModelId: input.chatConfig.modelId
      });

      // Determine if we can reuse vector cache
      const cache = input.vectorResultCache;
      const canReuseCache = 
        cache &&
        cache.parsedJD &&
        cache.retrievedChunks &&
        cache.retrievedChunks.length > 0;

      if (canReuseCache) {
        console.info("[analysis] Reusing cached vector results from previous attempt.");
        
        // Populate the variables directly from cache
        parsedJD = cache.parsedJD;
        retrievedChunks = cache.retrievedChunks || [];
        requirementMatchesResult = cache.requirementMatches;
        hardConstraintsResult = cache.hardConstraintsResult;

        // Instantly complete Step 2, Step 3, Step 4 in progress UI
        progress.completeStep("resume_embedding", {
          embeddedChunksCount: retrievedChunks.length,
          cacheReused: true
        });
        progress.completeStep("jd_embedding", { cacheReused: true });
        progress.completeStep("retrieve_chunks", {
          retrievedChunksCount: retrievedChunks.length,
          cacheReused: true
        });
        // Step 2: embedding_resume
        currentStepId = "resume_embedding";
        progress.setStatus("embedding_resume");
        progress.setRunningStep("resume_embedding");
        
        const alreadyVectorized = 
          input.chunks && 
          input.chunks.length > 0 && 
          input.chunks.every((c) => Array.isArray(c.embedding) && c.embedding.length > 0);

        let embeddedChunks: ResumeChunk[] = [];

        if (alreadyVectorized) {
          console.info("[analysis] Chunks are already vectorized. Skipping resume embedding step.");
          embeddedChunks = input.chunks;
          progress.completeStep("resume_embedding", {
            embeddedChunksCount: embeddedChunks.length,
            skipped: true
          });
        } else {
          progress.updateStepMetadata("resume_embedding", {
            embeddedChunksCount: 0,
            chunksCount: input.chunks.length
          });

          embeddedChunks = await embedChunksWithConfig(
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
        }

        // Step 3: embedding_jd
        currentStepId = "jd_embedding";
        progress.setStatus("embedding_jd");
        progress.setRunningStep("jd_embedding");
        
        // Stage A: Decompose JD into structural requirements and constraints
        parsedJD = await parseJobDescription(input.draft.jdText, chatConfigWithHighTimeout);
        
        // Stage B: Vectorize entire JD text for legacy/fallback search compatibility
        const jdEmbedding = await embedTextWithConfig(input.draft.jdText, input.embeddingConfig);
        progress.completeStep("jd_embedding");

        // Step 4: retrieving
        currentStepId = "retrieve_chunks";
        progress.setStatus("retrieving");
        progress.setRunningStep("retrieve_chunks");
        
        // Stage A: Core multi-requirement vector retrieval
        requirementMatchesResult = await retrieveEvidenceForRequirements(
          parsedJD,
          embeddedChunks,
          input.embeddingConfig,
          { topK: 3, threshold: 0.3 }
        );
        
        // Stage B: Deduplicate evidence chunks to build flat array for compatible rendering
        const seenChunkIds = new Set<string>();
        
        requirementMatchesResult.requirement_matches.forEach((rm: any) => {
          rm.matched_evidence.forEach((ev: any) => {
            if (!seenChunkIds.has(ev.evidence_id)) {
              seenChunkIds.add(ev.evidence_id);
              const originalChunk = embeddedChunks.find((c) => c.id === ev.evidence_id);
              if (originalChunk) {
                retrievedChunks.push({
                  ...originalChunk,
                  score: ev.similarity // Store highest retrieved similarity
                });
              }
            }
          });
        });
        
        // Sort flat list by similarity score descending
        retrievedChunks.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
        
        // Fallback: if no requirement matches returned any chunks, use whole-JD similarity
        if (retrievedChunks.length === 0) {
          const legacyChunks = retrieveTopChunksByCosineSimilarity({
            jdEmbedding,
            chunks: embeddedChunks,
            topK: 8,
          });
          retrievedChunks.push(...legacyChunks);
        }
        
        progress.completeStep("retrieve_chunks", {
          retrievedChunksCount: retrievedChunks.length
        });
      }

      if (!retrievedChunks.length) {
        throw new Error("没有检索到相关简历片段，请检查简历解析结果或 JD 内容。");
      }

      // Step 5: analyzing
      currentStepId = "gemini_analysis";
      progress.setStatus("analyzing");
      progress.setRunningStep("gemini_analysis");
      
      // Stage A: Hard constraints audit checking
      progress.updateStepMetadata("gemini_analysis", {
        subState: "checking_constraints",
        subProgress: 15
      });
      if (!hardConstraintsResult) {
        hardConstraintsResult = await checkHardConstraints(
          parsedJD,
          input.parsedResume,
          chatConfigWithHighTimeout
        );
      }
      
      // Stage B: Structured evidence-constrained Gemini analysis
      progress.updateStepMetadata("gemini_analysis", {
        subState: "deep_analyzing",
        subProgress: 35
      });

      // Smoothly emulated sub-progress bar updates for long reasoning/response time
      let currentSubProgress = 35;
      const progressTimer = window.setInterval(() => {
        if (currentSubProgress < 95) {
          if (currentSubProgress < 60) {
            currentSubProgress += 4;
          } else if (currentSubProgress < 80) {
            progress.updateStepMetadata("gemini_analysis", {
              subState: "generating_advice",
              subProgress: Math.round(currentSubProgress)
            });
            currentSubProgress += 2.5;
          } else {
            progress.updateStepMetadata("gemini_analysis", {
              subState: "building_roadmap",
              subProgress: Math.round(currentSubProgress)
            });
            currentSubProgress += 1.2;
          }
          progress.updateStepMetadata("gemini_analysis", {
            subProgress: Math.min(Math.round(currentSubProgress), 95)
          });
        }
      }, 2000);
      
      let chatResult;
      try {
        chatResult = await analyzeJobWithChatConfig({
          jdText: input.draft.jdText,
          targetType: input.draft.targetType || input.draft.level,
          jobDirection: input.draft.jobDirection || input.draft.title,
          retrievedChunks,
          config: chatConfigWithHighTimeout,
          
          // Pass structural context
          parsedJD,
          requirementMatches: requirementMatchesResult,
          hardConstraintsResult,
          userExtraContext: input.draft.candidateMaterial
        });
      } finally {
        window.clearInterval(progressTimer);
      }

      progress.updateStepMetadata("gemini_analysis", {
        subState: "completed",
        subProgress: 100
      });

      progress.completeStep("gemini_analysis", {
        retryCount: (chatResult as any)?.retryCount || 0
      });

      // Step 6: saving
      currentStepId = "save_history";
      progress.setStatus("saving");
      progress.setRunningStep("save_history");
      await new Promise((resolve) => window.setTimeout(resolve, 500));

      const averageScore = Math.round(
        retrievedChunks.reduce((sum, chunk) => sum + (chunk.score ?? 0), 0) / retrievedChunks.length,
      );

      const nextResult: AnalysisResult = {
        id: input.sourceDraftId || safeUUID(),
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

      // Auto-save history if callback is provided
      if (input.onSaveHistory) {
        try {
          await input.onSaveHistory(nextResult);
        } catch (saveError: any) {
          throw new Error("保存历史记录失败: " + (saveError.message || String(saveError)));
        }
      }

      progress.completeStep("save_history");

      // Step 7: render_result
      currentStepId = "render_result";
      progress.setRunningStep("render_result");
      setResult(nextResult);
      progress.completeStep("render_result");

      progress.setStatus("success");
      return { ok: true, result: nextResult };
    } catch (caught: any) {
      console.error("[analysis] failed", caught);
      const friendlyError = toUserFriendlyAnalysisError(caught, currentStepId, input.embeddingConfig, input.chatConfig);
      
      progress.failStep(currentStepId, friendlyError);
      progress.setError(friendlyError);
      progress.setStatus("failed");
      return {
        ok: false,
        failedStep: currentStepId,
        errorMessage: friendlyError,
        partialResult: {
          parsedJD,
          retrievedChunks,
          requirementMatches: requirementMatchesResult,
          hardConstraintsResult
        }
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
