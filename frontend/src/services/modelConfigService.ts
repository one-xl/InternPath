import type { ChatModelConfig, EmbeddingModelConfig, ModelTestResult } from "../types/modelConfig";
import { isDoubaoMultimodalEmbeddingProvider } from "../types/modelConfig";
import { embedTextWithDoubaoMultimodal, HttpRequestError } from "./doubaoMultimodalEmbeddingClient";
import { embedTextWithConfig } from "./embeddingClient";
import { testGeminiConfig } from "./geminiClient";

function nowMs(): number {
  return performance.now();
}

export async function testEmbeddingModelConfig(config: EmbeddingModelConfig): Promise<ModelTestResult> {
  const started = nowMs();
  try {
    const sample = "React TypeScript frontend engineer";

    // Validate configuration constraints
    if (!config.apiKey?.trim()) throw new Error("API Key 不能为空");
    if (!config.modelId?.trim()) throw new Error("Model ID 不能为空");
    if (!config.baseUrl?.trim()) throw new Error("Base URL 不能为空");
    if (!config.endpoint?.trim()) throw new Error("Endpoint 不能为空");

    if (isDoubaoMultimodalEmbeddingProvider(config.provider)) {
      if (config.dimensions !== undefined && config.dimensions !== null && config.dimensions !== 1024 && config.dimensions !== 2048) {
        throw new Error("dimensions 只能是 1024 或 2048");
      }
    }

    const embedding = isDoubaoMultimodalEmbeddingProvider(config.provider)
      ? await embedTextWithDoubaoMultimodal(sample, config)
      : await embedTextWithConfig(sample, config);

    if (!embedding || !embedding.length) {
      throw new Error("Doubao 返回结构异常，未找到 data.embedding");
    }

    if (config.dimensions && embedding.length !== config.dimensions) {
      throw new Error(`返回向量维度 ${embedding.length} 与配置的 dimensions ${config.dimensions} 不符`);
    }

    return {
      ok: true,
      message: isDoubaoMultimodalEmbeddingProvider(config.provider)
        ? `Doubao 多模态向量模型连接成功，返回向量维度：${embedding.length}`
        : `连接成功，向量维度 ${embedding.length}`,
      latencyMs: Math.round(nowMs() - started),
      provider: config.provider,
      modelId: config.modelId,
    };
  } catch (error) {
    let userFriendlyMessage = error instanceof Error ? error.message : "Embedding 测试失败";
    const lowercaseMsg = userFriendlyMessage.toLowerCase();

    let errorCode: string | undefined = undefined;
    let requestId: string | undefined = undefined;

    if (lowercaseMsg.includes("timeout") || lowercaseMsg.includes("超时")) {
      userFriendlyMessage = "请求超时";
    } else if (lowercaseMsg.includes("network") || lowercaseMsg.includes("failed to fetch") || lowercaseMsg.includes("网络")) {
      userFriendlyMessage = "网络错误";
    } else if (error instanceof HttpRequestError) {
      const responseBody = error.responseBody || "";
      
      // Attempt to parse Volcano Engine error JSON
      try {
        const parsed = JSON.parse(responseBody);
        errorCode = parsed?.error?.code || parsed?.code;
        requestId = parsed?.request_id || parsed?.error?.request_id;
      } catch {}

      if (!errorCode && responseBody.includes("does not support this api")) {
        errorCode = "does not support this api";
      }
      if (!errorCode && responseBody.includes("InvalidEndpointOrModel.NotFound")) {
        errorCode = "InvalidEndpointOrModel.NotFound";
      }

      // Check explicit mapping criteria
      if (errorCode === "does not support this api" || responseBody.includes("does not support this api")) {
        userFriendlyMessage = "当前模型不支持所选接口。Doubao 多模态向量模型必须使用 /embeddings/multimodal，且 input 必须是 object[]。";
      } else if (errorCode === "InvalidEndpointOrModel.NotFound" || responseBody.includes("InvalidEndpointOrModel.NotFound")) {
        userFriendlyMessage = "模型或 Endpoint 不存在、未开通，或当前 API Key 无权访问。请确认火山方舟控制台已开通 doubao-embedding-vision-250615 或复制实际可用的 Endpoint ID。";
      } else if (error.status === 401 || error.status === 403) {
        userFriendlyMessage = "API Key 无效或无权限，请检查 ARK_API_KEY。";
      } else if (error.status === 400 && (responseBody.includes("input") || responseBody.includes("param"))) {
        userFriendlyMessage = "请求体 input 格式错误。多模态向量接口要求 input 为 object[]，例如 [{ type: \"text\", text: \"...\" }]。";
      } else if (responseBody.includes("embedding") === false) {
        userFriendlyMessage = "Doubao 返回结构异常，未找到 data.embedding。请确认当前接口是 /embeddings/multimodal。";
      }
    }

    const diagnostics = {
      provider: config.provider,
      baseUrl: config.baseUrl,
      endpoint: config.endpoint,
      modelId: config.modelId,
      dimensions: config.dimensions ?? 1024,
      encodingFormat: config.encodingFormat || "float",
      inputShape: isDoubaoMultimodalEmbeddingProvider(config.provider) ? "object[]" : "string[]",
      status: error instanceof HttpRequestError ? error.status : undefined,
      message: error instanceof Error ? error.message : "未知错误",
      responsePreview: error instanceof HttpRequestError && error.responseBody
        ? error.responseBody.slice(0, 500)
        : undefined,
      errorCode,
      requestId,
    };

    return {
      ok: false,
      message: userFriendlyMessage,
      latencyMs: Math.round(nowMs() - started),
      provider: config.provider,
      modelId: config.modelId,
      diagnostics,
    } as any;
  }
}

export async function testChatModelConfig(
  config: ChatModelConfig,
  onProgress?: (msg: string) => void
): Promise<ModelTestResult> {
  if (config.provider !== "gemini") {
    return {
      ok: false,
      message: "当前仅支持 Gemini 大语言模型配置",
      provider: config.provider,
      modelId: config.modelId,
    };
  }
  return testGeminiConfig(config, onProgress);
}
