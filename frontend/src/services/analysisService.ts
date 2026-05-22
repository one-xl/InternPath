import type { AnalysisResult } from "../types/analysis";
import type { ChatModelConfig, EmbeddingModelConfig } from "../types/modelConfig";
import type { JobDraft } from "../types/job";
import type { ParsedResume, ResumeChunk, UploadedResumeFile } from "../types/resume";
import { analyzeJobWithChatConfig } from "./chatClient";
import { embedChunksWithConfig, embedTextWithConfig, retrieveTopChunksByCosineSimilarity } from "./embeddingClient";
import { safeUUID } from "../utils/uuid";

export interface ResumeRagAnalysisInput {
  jdText: string;
  targetType: string;
  jobDirection: string;
  draft: JobDraft;
  resumeFile: UploadedResumeFile;
  parsedResume: ParsedResume;
  chunks: ResumeChunk[];
  embeddingConfig: EmbeddingModelConfig;
  chatConfig: ChatModelConfig;
  topK?: number;
}

export async function analyzeJobWithResumeRag(input: ResumeRagAnalysisInput): Promise<AnalysisResult> {
  const topK = input.topK ?? 8;
  const embeddedChunks = await embedChunksWithConfig(input.chunks, input.embeddingConfig);
  const jdEmbedding = await embedTextWithConfig(input.jdText, input.embeddingConfig);
  const retrievedChunks = retrieveTopChunksByCosineSimilarity({
    jdEmbedding,
    chunks: embeddedChunks,
    topK,
  });
  if (!retrievedChunks.length) throw new Error("检索失败：没有召回可用于分析的简历片段");

  const chatResult = await analyzeJobWithChatConfig({
    jdText: input.jdText,
    targetType: input.targetType,
    jobDirection: input.jobDirection,
    retrievedChunks,
    config: input.chatConfig,
  });

  const averageScore = Math.round(
    retrievedChunks.reduce((sum, chunk) => sum + (chunk.score ?? 0), 0) / retrievedChunks.length,
  );

  return {
    id: safeUUID(),
    createdAt: new Date().toISOString(),
    draft: input.draft,
    resumeFile: { ...input.resumeFile, status: "indexed" },
    parsedResume: {
      ...input.parsedResume,
      chunks: input.parsedResume.chunks.map((chunk) => ({ ...chunk, embedding: undefined })),
    },
    retrievedResumeChunks: retrievedChunks.map((chunk) => ({ ...chunk, embedding: undefined })),
    retrievalSummary: `使用 ${input.embeddingConfig.provider} / ${input.embeddingConfig.modelId} 召回 ${retrievedChunks.length} 个简历片段。`,
    retrievalScore: averageScore,
    modelUsage: {
      embeddingProvider: input.embeddingConfig.provider,
      embeddingModelId: input.embeddingConfig.modelId,
      chatProvider: input.chatConfig.provider,
      chatModelId: chatResult.chatModelId || input.chatConfig.modelId,
      retrievalTopK: topK,
      createdAt: new Date().toISOString(),
    },
    ...chatResult,
  };
}
