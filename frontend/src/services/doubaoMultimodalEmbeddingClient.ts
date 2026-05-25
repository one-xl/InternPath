import type { EmbeddingModelConfig } from "../types/modelConfig";

const DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3";
export const DOUBAO_MULTIMODAL_EMBEDDING_ENDPOINT = "/embeddings/multimodal";

export class HttpRequestError extends Error {
  status: number;
  statusText: string;
  responseBody?: string;
  constructor(message: string, status: number, statusText: string, responseBody?: string) {
    super(message);
    this.name = "HttpRequestError";
    this.status = status;
    this.statusText = statusText;
    this.responseBody = responseBody;
  }
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时，请检查网络或适当增大 Timeout");
    }
    throw new Error("网络错误，请检查代理、网络环境或火山方舟域名访问");
  } finally {
    window.clearTimeout(timer);
  }
}

export function extractDoubaoMultimodalEmbedding(responseJson: unknown): number[] {
  const embedding = (responseJson as any)?.data?.embedding;

  if (!Array.isArray(embedding)) {
    throw new Error("Doubao 返回结构异常：未找到 data.embedding");
  }

  if (!embedding.every((value) => typeof value === "number")) {
    throw new Error("Doubao 返回结构异常：embedding 不是 number[]");
  }

  return embedding;
}

export function extractEmbeddingByProvider(responseJson: any, provider: string): number[] {
  if (provider === "doubao-multimodal" || provider === "doubao") {
    return extractDoubaoMultimodalEmbedding(responseJson);
  }

  if (provider === "openai-compatible" || provider === "custom" || provider === "doubao-text") {
    const data = responseJson?.data;
    const first = Array.isArray(data) ? data[0] : undefined;
    if (!first || !Array.isArray(first?.embedding) || !first.embedding.every((v: any) => typeof v === "number")) {
      throw new Error("返回结构异常：未找到 data[0].embedding");
    }
    return first.embedding;
  }

  throw new Error(`不支持的 Provider 向量解析方式: ${provider}`);
}

async function postEmbedding(url: string, config: EmbeddingModelConfig, body: unknown): Promise<unknown> {
  const response = await fetchWithTimeout(
    "/api/models/embeddings",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: config.provider,
        modelId: config.modelId,
        requestBody: body,
        endpoint: config.endpoint || DOUBAO_MULTIMODAL_EMBEDDING_ENDPOINT,
        configId: config.id,
      }),
    },
    config.timeoutMs ?? 60000,
  );

  if (!response.ok) {
    let bodyText = "";
    try {
      bodyText = await response.text();
    } catch {}
    throw new HttpRequestError(
      `请求失败，状态码 ${response.status}`,
      response.status,
      response.statusText,
      bodyText
    );
  }
  console.info("[embedding] Doubao embedding request success");
  return response.json();
}

export async function embedTextWithDoubaoMultimodal(text: string, config: EmbeddingModelConfig): Promise<number[]> {
  if (!config.modelId.trim()) throw new Error("Model ID 不能为空");
  if (!text.trim()) throw new Error("Embedding 文本不能为空");

  const baseUrl = config.baseUrl || DEFAULT_BASE_URL;
  const endpoint = config.endpoint || DOUBAO_MULTIMODAL_EMBEDDING_ENDPOINT;
  const url = `${baseUrl.replace(/\/$/, "")}${endpoint}`;

  const body: any = {
    model: config.modelId,
    encoding_format: config.encodingFormat ?? "float",
    input: [
      {
        type: "text",
        text: text,
      },
    ],
  };

  if (config.dimensions === 1024 || config.dimensions === 2048) {
    body.dimensions = config.dimensions;
  } else {
    body.dimensions = 1024; // Default to 1024 as specified
  }

  console.info("[embedding] Doubao embedding request started", {
    url,
    model: config.modelId,
    dimensions: body.dimensions,
    encoding_format: body.encoding_format
  });

  const payload = await postEmbedding(url, config, body);
  return extractDoubaoMultimodalEmbedding(payload);
}
