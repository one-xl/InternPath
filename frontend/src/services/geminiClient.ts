import type { ChatModelConfig, ModelTestResult } from "../types/modelConfig";
import { safeParseModelJson } from "../utils/safeParseModelJson";

const DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta";

function validateGeminiConfig(config: ChatModelConfig) {
  if (!config.modelId.trim()) throw new Error("Model ID 不能为空");
  if ((config.temperature ?? 0.2) < 0 || (config.temperature ?? 0.2) > 2) throw new Error("Temperature 不合法");
  if ((config.maxOutputTokens ?? 4096) <= 0) throw new Error("Max Output Tokens 不合法");
  if ((config.timeoutMs ?? 60000) <= 0) throw new Error("Timeout 不合法");
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("Gemini 请求超时");
    throw new Error("网络错误，请检查代理或网络环境");
  } finally {
    window.clearTimeout(timer);
  }
}

function parseErrorStatus(status: number): string {
  if (status === 401 || status === 403) return "Gemini API Key 无效或无权限";
  if (status === 404) return "Gemini 模型不存在或不可用";
  if (status === 429) return "Gemini 请求被限流，请稍后再试";
  if (status >= 500) return "Gemini 服务异常，请稍后再试";
  return "Gemini 请求失败";
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    throw new Error(`Gemini REST 响应不是合法 JSON：${error instanceof Error ? error.message : "解析失败"}`);
  }
}

function readGeminiText(payload: unknown): string {
  const root = payload as { candidates?: unknown };
  const candidates = Array.isArray(root.candidates) ? root.candidates : [];
  const first = candidates[0] as { content?: { parts?: unknown } } | undefined;
  const parts = Array.isArray(first?.content?.parts) ? first.content.parts : [];
  const text = parts
    .map((part) => (part as { text?: unknown }).text)
    .filter((value): value is string => typeof value === "string")
    .join("\n")
    .trim();
  if (!text) throw new Error("Gemini 返回内容为空");
  return text;
}

export async function callGeminiWithConfig(input: {
  config: ChatModelConfig;
  prompt: string;
  forceJson?: boolean;
  responseSchema?: unknown;
  overrideGenerationConfig?: {
    temperature?: number;
    maxOutputTokens?: number;
    responseMimeType?: "application/json" | "text/plain";
    thinkingConfig?: {
      thinkingLevel: string;
    };
  };
  debugCapture?: {
    rawRequestBody?: string;
    rawResponseText?: string;
    modelText?: string;
    parseError?: string;
    finishReason?: string;
    promptTokenCount?: number;
    candidatesTokenCount?: number;
    thoughtsTokenCount?: number;
    totalTokenCount?: number;
    thinkingLevel?: string;
    isTruncatedByMaxTokens?: boolean;
  };
}): Promise<string> {
  const { config, prompt, forceJson = true, responseSchema, overrideGenerationConfig, debugCapture } = input;

  if (!config.modelId?.trim()) {
    throw new Error("Gemini Model ID 不能为空");
  }

  const baseUrl = config.baseUrl?.trim() || "https://generativelanguage.googleapis.com/v1beta";
  const url = `${baseUrl.replace(/\/$/, "")}/models/${encodeURIComponent(config.modelId.trim())}:generateContent`;

  const generationConfig: Record<string, unknown> = {
    temperature: overrideGenerationConfig?.temperature ?? config.temperature ?? 0.2,
    maxOutputTokens: overrideGenerationConfig?.maxOutputTokens ?? config.maxOutputTokens ?? 4096,
  };

  if (forceJson) {
    generationConfig.responseMimeType = overrideGenerationConfig?.responseMimeType ?? config.responseMimeType ?? "application/json";
  }

  if (responseSchema) {
    generationConfig.responseSchema = responseSchema;
  }

  const modelId = config.modelId.trim();
  if (modelId.startsWith("gemini-3")) {
    generationConfig.thinkingConfig = overrideGenerationConfig?.thinkingConfig ?? {
      thinkingLevel: "minimal"
    };
  }

  const requestBodyObj = {
    contents: [
      {
        parts: [{ text: prompt }],
      },
    ],
    generationConfig,
  };

  if (debugCapture) {
    debugCapture.rawRequestBody = JSON.stringify(requestBodyObj, null, 2);
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), config.timeoutMs ?? 60000);

  try {
    console.info("[chat] LLM analysis request started", {
      url,
      model: config.modelId.trim(),
      provider: config.provider,
      generationConfig,
    });

    let response = await fetch("/api/models/chat-completions", {
      method: "POST",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: config.provider,
        modelId: config.modelId.trim(),
        requestBody: requestBodyObj,
      }),
    });

    let raw = await response.text();
    if (debugCapture) {
      debugCapture.rawResponseText = raw;
    }

    // Auto-downgrade retry if status is 400 and we sent thinkingConfig
    if (!response.ok && response.status === 400 && generationConfig.thinkingConfig) {
      const lowerRaw = raw.toLowerCase();
      if (lowerRaw.includes("thinking") || lowerRaw.includes("config") || lowerRaw.includes("parameter") || lowerRaw.includes("invalid") || lowerRaw.includes("bad request")) {
        delete generationConfig.thinkingConfig;
        const fallbackRequestBodyObj = {
          ...requestBodyObj,
          generationConfig,
        };
        if (debugCapture) {
          debugCapture.rawRequestBody = JSON.stringify(fallbackRequestBodyObj, null, 2);
        }

        console.info("[chat] LLM analysis request retrying without thinkingConfig", {
          url,
          model: config.modelId.trim(),
          provider: config.provider,
          generationConfig,
        });

        response = await fetch("/api/models/chat-completions", {
          method: "POST",
          signal: controller.signal,
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            provider: config.provider,
            modelId: config.modelId.trim(),
            requestBody: fallbackRequestBodyObj,
          }),
        });
        raw = await response.text();
        if (debugCapture) {
          debugCapture.rawResponseText = raw;
        }
      }
    }

    if (!response.ok) {
      const error = new Error(`Gemini 请求失败：${response.status} ${raw.slice(0, 500)}`);
      (error as any).status = response.status;
      (error as any).responseBody = raw;
      throw error;
    }

    console.info("[chat] Gemini analysis request success");

    let json: any;
    try {
      json = JSON.parse(raw);
    } catch (error: any) {
      if (debugCapture) {
        debugCapture.parseError = `JSON 解析 HTTP 响应失败: ${error.message}`;
      }
      throw new Error(`Gemini REST 响应不是合法 JSON：${error instanceof Error ? error.message : "解析失败"}`);
    }

    const text =
      json?.candidates?.[0]?.content?.parts
        ?.map((part: { text?: string }) => part.text ?? "")
        .join("") ?? "";

    const finishReason = json?.candidates?.[0]?.finishReason;
    const usageMetadata = json?.usageMetadata;
    const promptTokenCount = usageMetadata?.promptTokenCount;
    const candidatesTokenCount = usageMetadata?.candidatesTokenCount;
    const thoughtsTokenCount = usageMetadata?.thoughtsTokenCount;
    const totalTokenCount = usageMetadata?.totalTokenCount;

    if (debugCapture) {
      debugCapture.modelText = text;
      debugCapture.finishReason = finishReason;
      debugCapture.promptTokenCount = promptTokenCount;
      debugCapture.candidatesTokenCount = candidatesTokenCount;
      debugCapture.thoughtsTokenCount = thoughtsTokenCount;
      debugCapture.totalTokenCount = totalTokenCount;
      if (generationConfig.thinkingConfig) {
        debugCapture.thinkingLevel = (generationConfig.thinkingConfig as any).thinkingLevel;
      }
      debugCapture.isTruncatedByMaxTokens = finishReason === "MAX_TOKENS";
    }

    if (finishReason === "MAX_TOKENS") {
      const maxTokensErr = new Error(`Gemini 输出被截断：模型输出已被 MAX_TOKENS 截断。`);
      (maxTokensErr as any).status = response.status;
      (maxTokensErr as any).responseBody = raw;
      (maxTokensErr as any).finishReason = "MAX_TOKENS";
      (maxTokensErr as any).usageMetadata = usageMetadata;
      (maxTokensErr as any).modelText = text;
      throw maxTokensErr;
    }

    if (!text.trim()) {
      throw new Error("Gemini 返回内容为空");
    }

    return text;
  } catch (error: any) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Gemini 请求超时");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export interface GeminiErrorDetails {
  errorType: ModelTestResult["errorType"];
  message: string;
  retryable: boolean;
  status?: number;
  responseBody?: string;
}

export function classifyGeminiError(error: any, defaultMsg = "Gemini 连接失败"): GeminiErrorDetails {
  let status: number | undefined = error.status;
  let responseBody: string | undefined = error.responseBody;
  let rawMessage = error.message || String(error);
  let finishReason: string | undefined = error.finishReason;
  let usageMetadata = error.usageMetadata;

  // If not explicitly set, try to parse status/body from message
  if (!status && rawMessage.includes("Gemini 请求失败：")) {
    const match = rawMessage.match(/Gemini 请求失败：(\d+)\s*(.*)/);
    if (match) {
      status = parseInt(match[1], 10);
      if (!responseBody) {
        responseBody = match[2];
      }
    }
  }

  const lowercaseMsg = rawMessage.toLowerCase();
  const lowercaseBody = (responseBody || "").toLowerCase();

  let errorType: ModelTestResult["errorType"] = "unknown";
  let userMessage = defaultMsg;
  let retryable = false;

  const thoughtsTokenCount = usageMetadata?.thoughtsTokenCount ?? 0;
  const candidatesTokenCount = usageMetadata?.candidatesTokenCount ?? 0;

  // 0. Check for MAX_TOKENS / output truncated
  if (finishReason === "MAX_TOKENS") {
    if (thoughtsTokenCount > candidatesTokenCount || thoughtsTokenCount > 50) {
      errorType = "output_truncated_by_thinking";
      userMessage = "Gemini 输出被截断：当前模型使用了 thinking token，maxOutputTokens 过低，导致可见 JSON 没有生成完整。请提高 maxOutputTokens 或将 thinking level 设置为 minimal。";
      retryable = false;
    } else {
      errorType = "invalid_json";
      userMessage = "Gemini 输出被截断：已达到最大 tokens 限制 (MAX_TOKENS)，导致可见 JSON 没有生成完整。请提高 maxOutputTokens。";
      retryable = false;
    }
  }
  // 1. Check for 503 / high demand
  else if (
    status === 503 ||
    lowercaseMsg.includes("unavailable") ||
    lowercaseMsg.includes("high demand") ||
    lowercaseMsg.includes("try again later") ||
    lowercaseBody.includes("unavailable") ||
    lowercaseBody.includes("high demand") ||
    lowercaseBody.includes("try again later")
  ) {
    errorType = "high_demand";
    userMessage = "Gemini 当前模型负载较高，服务暂时不可用。请稍后重试，或切换备用模型。";
    retryable = true;
  }
  // 2. Check for 429 / rate limit
  else if (status === 429 || lowercaseMsg.includes("rate_limit") || lowercaseMsg.includes("resource_exhausted") || lowercaseBody.includes("resource_exhausted")) {
    errorType = "rate_limit";
    userMessage = "Gemini 请求被限流，请稍后再试或降低请求频率。";
    retryable = true;
  }
  // 3. Check for auth / 401 / 403
  else if (status === 401 || status === 403 || lowercaseMsg.includes("api key") || lowercaseMsg.includes("auth") || lowercaseMsg.includes("permission")) {
    errorType = "auth";
    userMessage = "Gemini API Key 无效或无权限，请检查配置。";
    retryable = false;
  }
  // 4. Check for 404 / not found
  else if (status === 404 || lowercaseMsg.includes("model not found") || lowercaseMsg.includes("not found")) {
    errorType = "not_found";
    userMessage = "Gemini 模型不存在或不可用，请检查 Model ID。";
    retryable = false;
  }
  // 5. Check for timeout
  else if (lowercaseMsg.includes("timeout") || lowercaseMsg.includes("超时")) {
    errorType = "timeout";
    userMessage = "Gemini 请求超时，请检查 network 或稍后重试。";
    retryable = true;
  }
  // 6. Check for 400 invalid request
  else if (status === 400) {
    errorType = "invalid_request";
    userMessage = `请求参数错误：${rawMessage}`;
    retryable = false;
  }
  // 7. Check for JSON parse / format failure
  else if (lowercaseMsg.includes("非 json 内容") || lowercaseMsg.includes("json")) {
    errorType = "invalid_json";
    userMessage = rawMessage;
    retryable = false;
  }
  // 8. Check for network temporary failure
  else if (lowercaseMsg.includes("network") || lowercaseMsg.includes("failed to fetch") || lowercaseMsg.includes("网络")) {
    errorType = "network";
    userMessage = "网络连接失败，请检查代理或网络环境。";
    retryable = true;
  }
  else {
    userMessage = rawMessage;
  }

  return {
    errorType,
    message: userMessage,
    retryable,
    status,
    responseBody
  };
}

export async function testGeminiConfig(
  config: ChatModelConfig,
  onProgress?: (msg: string) => void
): Promise<ModelTestResult> {
  const startedAt = performance.now();

  const promptSchemaCombinations = [
    { prompt: 'Return exactly:\n{"ok":true}', useSchema: true },
    { prompt: 'Return exactly:\n{"ok":true}', useSchema: false },
    { prompt: '{"ok":true}', useSchema: true },
    { prompt: '{"ok":true}', useSchema: false },
  ];

  const responseSchema = {
    type: "OBJECT",
    properties: {
      ok: {
        type: "BOOLEAN",
      },
    },
    required: ["ok"],
  };

  const debugCapture: {
    rawRequestBody?: string;
    rawResponseText?: string;
    modelText?: string;
    parseError?: string;
    finishReason?: string;
    promptTokenCount?: number;
    candidatesTokenCount?: number;
    thoughtsTokenCount?: number;
    totalTokenCount?: number;
    thinkingLevel?: string;
    isTruncatedByMaxTokens?: boolean;
  } = {};

  async function executeTest(modelId: string, useSchema: boolean, promptText: string, maxTokens: number): Promise<string> {
    return await callGeminiWithConfig({
      config: {
        ...config,
        modelId,
        temperature: 0,
        maxOutputTokens: maxTokens,
        responseMimeType: "application/json",
      },
      prompt: promptText,
      forceJson: true,
      responseSchema: useSchema ? responseSchema : undefined,
      overrideGenerationConfig: {
        temperature: 0,
        maxOutputTokens: maxTokens,
        responseMimeType: "application/json",
      },
      debugCapture,
    });
  }

  let initialModelId = config.testModelId?.trim() || config.modelId;
  let finalModelId = initialModelId;
  let fallbackUsed = false;
  let usedSchema = true;
  let text = "";
  let finalPromptStr = "";

  async function runTestForModel(modelId: string, isFallback: boolean): Promise<{ text: string; usedSchema: boolean; finalPrompt: string }> {
    const retryDelays = [2000, 5000, 10000];
    let comboIndex = 0;
    let attempt = 0;

    while (comboIndex < promptSchemaCombinations.length) {
      const { prompt: promptText, useSchema } = promptSchemaCombinations[comboIndex];
      usedSchema = useSchema;
      finalPromptStr = promptText;

      try {
        let resText = "";
        try {
          resText = await executeTest(modelId, useSchema, promptText, 512);
        } catch (err: any) {
          if (err.finishReason === "MAX_TOKENS") {
            if (onProgress) {
              onProgress(`由于 MAX_TOKENS 截断，正在尝试自动重试并将 maxOutputTokens 提高至 1024...`);
            }
            resText = await executeTest(modelId, useSchema, promptText, 1024);
          } else {
            throw err;
          }
        }
        return { text: resText, usedSchema: useSchema, finalPrompt: promptText };
      } catch (error: any) {
        const classification = classifyGeminiError(error);
        
        if (classification.errorType === "high_demand" && config.fallbackModelId?.trim() && !isFallback) {
          throw error;
        }

        if (classification.retryable && attempt < retryDelays.length) {
          const delay = retryDelays[attempt];
          attempt++;
          if (onProgress) {
            onProgress(`正在重试，第 ${attempt} 次`);
          }
          await new Promise(resolve => setTimeout(resolve, delay));
          continue; // Retry the same combination
        }

        // Try next combination
        comboIndex++;
        attempt = 0;
        if (comboIndex >= promptSchemaCombinations.length) {
          throw error;
        }
      }
    }
    throw new Error("所有测试组合已尝试，未能成功连接");
  }

  try {
    try {
      const resultObj = await runTestForModel(initialModelId, false);
      text = resultObj.text;
    } catch (primaryError: any) {
      const primaryClassification = classifyGeminiError(primaryError);
      
      if (primaryClassification.errorType === "high_demand" && config.fallbackModelId?.trim()) {
        fallbackUsed = true;
        finalModelId = config.fallbackModelId.trim();
        if (onProgress) {
          onProgress(`主模型繁忙，正在尝试备用模型 ${finalModelId}...`);
        }
        const resultObj = await runTestForModel(finalModelId, true);
        text = resultObj.text;
      } else {
        throw primaryError;
      }
    }

    const cleanText = text.trim();
    const parsed = safeParseModelJson<{ ok: boolean }>(cleanText);

    if (parsed.ok !== true) {
      throw new Error("Gemini 返回 JSON 不符合预期");
    }

    const hasIntroText = cleanText.startsWith("Here is") || !cleanText.startsWith("{");
    const successMessage = hasIntroText
      ? "Gemini 连接成功，但模型返回了额外说明文字，系统已自动提取 JSON。建议继续保留 responseMimeType 或切换更稳定模型。"
      : (fallbackUsed ? "主模型当前繁忙，已使用备用模型连接成功。" : "Gemini 连接成功");

    const baseUrl = config.baseUrl?.trim() || "https://generativelanguage.googleapis.com/v1beta";
    const url = `${baseUrl.replace(/\/$/, "")}/models/${encodeURIComponent(finalModelId.trim())}:generateContent`;

    const diagnostics = {
      provider: "gemini",
      url,
      modelId: finalModelId,
      temperature: 0,
      maxOutputTokens: debugCapture.isTruncatedByMaxTokens ? 1024 : 512,
      responseMimeType: "application/json",
      hasResponseSchema: usedSchema,
      status: 200,
      message: "success",
      rawRequestBody: debugCapture.rawRequestBody,
      rawResponseText: debugCapture.rawResponseText,
      modelText: debugCapture.modelText,
      parseError: undefined,
      errorType: undefined,
      retryable: false,
      fallbackUsed,
      fallbackModelId: config.fallbackModelId,
      
      finishReason: debugCapture.finishReason,
      promptTokenCount: debugCapture.promptTokenCount,
      candidatesTokenCount: debugCapture.candidatesTokenCount,
      thoughtsTokenCount: debugCapture.thoughtsTokenCount,
      totalTokenCount: debugCapture.totalTokenCount,
      thinkingLevel: debugCapture.thinkingLevel,
      isTruncatedByMaxTokens: debugCapture.isTruncatedByMaxTokens,
    };

    return {
      ok: true,
      message: successMessage,
      latencyMs: Math.round(performance.now() - startedAt),
      provider: "gemini",
      modelId: finalModelId,
      fallbackUsed,
      fallbackModelId: fallbackUsed ? config.fallbackModelId : undefined,
      diagnostics,
    };

  } catch (error: any) {
    if (debugCapture.finishReason === "MAX_TOKENS") {
      error.finishReason = "MAX_TOKENS";
      error.usageMetadata = {
        promptTokenCount: debugCapture.promptTokenCount,
        candidatesTokenCount: debugCapture.candidatesTokenCount,
        thoughtsTokenCount: debugCapture.thoughtsTokenCount,
        totalTokenCount: debugCapture.totalTokenCount,
      };
    }
    const classification = classifyGeminiError(error);

    const baseUrl = config.baseUrl?.trim() || "https://generativelanguage.googleapis.com/v1beta";
    const url = `${baseUrl.replace(/\/$/, "")}/models/${encodeURIComponent(finalModelId.trim())}:generateContent`;

    const diagnostics = {
      provider: "gemini",
      url,
      modelId: finalModelId,
      temperature: 0,
      maxOutputTokens: debugCapture.isTruncatedByMaxTokens ? 1024 : 512,
      responseMimeType: "application/json",
      hasResponseSchema: usedSchema,
      status: classification.status,
      message: classification.message,
      responsePreview: debugCapture.rawResponseText ? debugCapture.rawResponseText.slice(0, 500) : (error.message || "").slice(0, 500),
      rawRequestBody: debugCapture.rawRequestBody,
      rawResponseText: debugCapture.rawResponseText,
      modelText: debugCapture.modelText || error.modelText,
      parseError: debugCapture.parseError || error.message,
      errorType: classification.errorType,
      retryable: classification.retryable,
      fallbackUsed,
      fallbackModelId: config.fallbackModelId,
      
      finishReason: debugCapture.finishReason || error.finishReason,
      promptTokenCount: debugCapture.promptTokenCount || error.usageMetadata?.promptTokenCount,
      candidatesTokenCount: debugCapture.candidatesTokenCount || error.usageMetadata?.candidatesTokenCount,
      thoughtsTokenCount: debugCapture.thoughtsTokenCount || error.usageMetadata?.thoughtsTokenCount,
      totalTokenCount: debugCapture.totalTokenCount || error.usageMetadata?.totalTokenCount,
      thinkingLevel: debugCapture.thinkingLevel,
      isTruncatedByMaxTokens: debugCapture.isTruncatedByMaxTokens || error.finishReason === "MAX_TOKENS",
    };

    return {
      ok: false,
      message: classification.message,
      latencyMs: Math.round(performance.now() - startedAt),
      provider: "gemini",
      modelId: finalModelId,
      errorType: classification.errorType,
      retryable: classification.retryable,
      fallbackUsed,
      fallbackModelId: fallbackUsed ? config.fallbackModelId : undefined,
      diagnostics,
    } as any;
  }
}
