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
        modelId: config.modelId,
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
