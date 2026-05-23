export type EmbeddingProvider =
  | "doubao-multimodal"
  | "doubao-text"
  | "openai-compatible"
  | "custom";
export type ChatProvider = "gemini" | "openai-compatible" | "custom";
export type ModelTestStatus = "untested" | "testing" | "success" | "failed";

export function isDoubaoTextEmbeddingProvider(provider: EmbeddingProvider): boolean {
  return provider === "doubao-text";
}

export function isDoubaoMultimodalEmbeddingProvider(provider: EmbeddingProvider): boolean {
  return provider === "doubao-multimodal" || provider === "doubao" as any;
}

export interface BaseModelConfig {
  id: string;
  name: string;
  provider: string;
  apiKey: string;
  is_server_managed?: boolean;
  baseUrl?: string;
  modelId: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
  lastTestedAt?: string;
  testStatus: ModelTestStatus;
  testMessage?: string;
  testDiagnostics?: {
    provider: string;
    baseUrl?: string;
    endpoint?: string;
    modelId: string;
    dimensions?: number;
    encodingFormat?: string;
    inputShape?: string;
    status?: number;
    message?: string;
    responsePreview?: string;
    url?: string;
    responseMimeType?: string;
    hasResponseSchema?: boolean;
    temperature?: number;
    maxOutputTokens?: number;
    errorCode?: string;
    requestId?: string;
    errorType?: string;
    retryable?: boolean;
    fallbackUsed?: boolean;
    fallbackModelId?: string;
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
}

export interface EmbeddingModelConfig extends BaseModelConfig {
  type: "embedding";
  provider: EmbeddingProvider;
  endpoint?: string;
  dimensions?: 1024 | 2048;
  encodingFormat?: "float" | "base64" | "null";
  timeoutMs?: number;
  inputType?: "text" | "multimodal";
  _suggestedEndpoint?: string;
}

export interface ChatModelConfig extends BaseModelConfig {
  type: "chat";
  provider: ChatProvider;
  temperature?: number;
  maxOutputTokens?: number;
  timeoutMs?: number;
  responseMimeType?: "application/json" | "text/plain";
  fallbackModelId?: string;
  testModelId?: string;
}

export interface ActiveModelConfig {
  embeddingConfigId?: string;
  chatConfigId?: string;
}

export interface ModelConfigState {
  embeddingConfigs: EmbeddingModelConfig[];
  chatConfigs: ChatModelConfig[];
  active: ActiveModelConfig;
}

export interface ModelTestResult {
  ok: boolean;
  message: string;
  latencyMs?: number;
  provider?: string;
  modelId?: string;
  errorType?: 
    | "auth"
    | "not_found"
    | "rate_limit"
    | "high_demand"
    | "timeout"
    | "invalid_request"
    | "invalid_json"
    | "output_truncated_by_thinking"
    | "network"
    | "unknown";
  retryable?: boolean;
  fallbackUsed?: boolean;
  fallbackModelId?: string;
  diagnostics?: BaseModelConfig["testDiagnostics"];
}

export interface ModelUsage {
  embeddingProvider: string;
  embeddingModelId: string;
  chatProvider: string;
  chatModelId: string;
  retrievalTopK: number;
  createdAt: string;
}
