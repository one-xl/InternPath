import type { EmbeddingModelConfig } from "../types/modelConfig";
import { isDoubaoMultimodalEmbeddingProvider, isDoubaoTextEmbeddingProvider } from "../types/modelConfig";
import type { ResumeChunk } from "../types/resume";
import { embedTextWithDoubaoMultimodal, HttpRequestError } from "./doubaoMultimodalEmbeddingClient";

async function embedTextWithOpenAICompatible(text: string, config: EmbeddingModelConfig): Promise<number[]> {
  const response = await fetch("/api/models/embeddings", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      provider: config.provider,
      modelId: config.modelId,
      requestBody: {
        model: config.modelId,
        input: [text],
        ...(config.dimensions ? { dimensions: config.dimensions } : {}),
      },
      endpoint: config.endpoint || "/embeddings",
    }),
  });

  if (!response.ok) {
    let bodyText = "";
    try {
      bodyText = await response.text();
    } catch {}
    throw new HttpRequestError(`OpenAI-compatible Embedding 请求失败，HTTP ${response.status}`, response.status, response.statusText, bodyText);
  }

  const payload = await response.json();
  const embedding = payload?.data?.[0]?.embedding;
  if (!Array.isArray(embedding)) {
    throw new Error("OpenAI-compatible 返回结构异常：未找到 data[0].embedding");
  }
  return embedding;
}

export async function embedTextWithConfig(text: string, config: EmbeddingModelConfig): Promise<number[]> {
  if (isDoubaoMultimodalEmbeddingProvider(config.provider, config.modelId)) {
    return embedTextWithDoubaoMultimodal(text, config);
  }
  if (
    config.provider === "openai-compatible" ||
    config.provider === "custom" ||
    config.provider === "doubao-text" ||
    isDoubaoTextEmbeddingProvider(config.provider, config.modelId)
  ) {
    return embedTextWithOpenAICompatible(text, config);
  }
  throw new Error(`当前文本 RAG 不支持 Provider: ${config.provider}`);
}

export async function embedChunksWithConfig(
  chunks: ResumeChunk[],
  config: EmbeddingModelConfig,
  options?: {
    onProgress?: (progress: {
      completed: number;
      total: number;
      currentChunkId?: string;
    }) => void;
  }
): Promise<ResumeChunk[]> {
  const embedded: ResumeChunk[] = [];
  for (let index = 0; index < chunks.length; index += 1) {
    const chunk = chunks[index];
    const embedding = await embedTextWithConfig(chunk.content, config);
    embedded.push({
      ...chunk,
      embedding,
    });
    options?.onProgress?.({
      completed: index + 1,
      total: chunks.length,
      currentChunkId: chunk.id,
    });
  }
  return embedded;
}

export function cosineSimilarity(a: number[], b: number[]): number {
  if (!a.length || !b.length || a.length !== b.length) return 0;
  let dot = 0;
  let normA = 0;
  let normB = 0;
  for (let index = 0; index < a.length; index += 1) {
    dot += a[index] * b[index];
    normA += a[index] * a[index];
    normB += b[index] * b[index];
  }
  if (!normA || !normB) return 0;
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

export function retrieveTopChunksByCosineSimilarity(input: {
  jdEmbedding: number[];
  chunks: ResumeChunk[];
  topK: number;
}): ResumeChunk[] {
  return input.chunks
    .map((chunk) => ({
      ...chunk,
      score: Math.round(Math.max(0, cosineSimilarity(input.jdEmbedding, chunk.embedding ?? [])) * 100),
      embedding: undefined,
    }))
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    .slice(0, input.topK);
}
