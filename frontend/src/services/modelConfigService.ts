import type { ChatModelConfig, EmbeddingModelConfig, ModelTestResult } from "../types/modelConfig";

function nowMs(): number {
  return performance.now();
}

export async function testEmbeddingModelConfig(config: EmbeddingModelConfig): Promise<ModelTestResult> {
  const started = nowMs();
  try {
    const response = await fetch("/api/models/test-connection", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: config.provider,
        modelId: config.modelId,
        endpoint: config.endpoint || undefined,
      }),
    });
    const data = await response.json();
    if (response.ok && data.ok) {
      return {
        ok: true,
        message: data.message || "连接成功",
        latencyMs: Math.round(nowMs() - started),
        provider: config.provider,
        modelId: config.modelId,
      };
    } else {
      throw new Error(data.message || "连接失败，请检查服务器端模型配置。");
    }
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : "连接失败，请检查服务器端模型配置。",
      latencyMs: Math.round(nowMs() - started),
      provider: config.provider,
      modelId: config.modelId,
      diagnostics: {
        provider: config.provider,
        modelId: config.modelId,
        message: error instanceof Error ? error.message : "未知错误",
      }
    } as any;
  }
}

export async function testChatModelConfig(
  config: ChatModelConfig,
  onProgress?: (msg: string) => void
): Promise<ModelTestResult> {
  const started = nowMs();
  const modelId = config.testModelId?.trim() || config.modelId;
  const baseUrl = config.baseUrl?.trim() || "https://generativelanguage.googleapis.com/v1beta";
  const url = config.provider === "gemini"
    ? `${baseUrl.replace(/\/$/, "")}/models/${encodeURIComponent(modelId)}:generateContent`
    : `${baseUrl.replace(/\/$/, "")}/chat/completions`;

  if (onProgress) {
    onProgress("正在向服务器发起测试连接请求...");
  }
  try {
    const response = await fetch("/api/models/test-connection", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: config.provider,
        type: "chat",
        modelId,
      }),
    });
    const rawResponseText = await response.text();
    let data: any = {};
    try {
      data = rawResponseText ? JSON.parse(rawResponseText) : {};
    } catch {
      data = {};
    }

    const diagnostics = {
      provider: config.provider,
      url: data.url || url,
      modelId,
      temperature: 0,
      maxOutputTokens: 256,
      responseMimeType: "application/json",
      hasResponseSchema: false,
      status: data.upstreamStatus ?? response.status,
      proxyStatus: response.status,
      message: data.message || rawResponseText || "连接失败，请检查服务器端模型配置。",
      rawResponseText: data.rawResponseText || rawResponseText,
      responsePreview: (data.rawResponseText || rawResponseText).slice(0, 500),
      retryable: false,
    };

    if (response.ok && data.ok) {
      return {
        ok: true,
        message: data.message || "连接成功",
        latencyMs: Math.round(nowMs() - started),
        provider: config.provider,
        modelId,
        diagnostics,
      };
    } else {
      const err: any = new Error(data.message || "连接失败，请检查服务器端模型配置。");
      err.diagnostics = diagnostics;
      throw err;
    }
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : "连接失败，请检查服务器端模型配置。",
      latencyMs: Math.round(nowMs() - started),
      provider: config.provider,
      modelId,
      diagnostics: (error as any)?.diagnostics || {
        provider: config.provider,
        url,
        modelId,
        temperature: 0,
        maxOutputTokens: 256,
        responseMimeType: "application/json",
        hasResponseSchema: false,
        message: error instanceof Error ? error.message : "未知错误",
      }
    } as any;
  }
}
