import type { ChatModelConfig, EmbeddingModelConfig, ModelConfigState } from "../types/modelConfig";
import { apiFetch } from "./apiClient";

export async function fetchConfigs(): Promise<ModelConfigState> {
  const data = await apiFetch<{ configs: any[] }>("/api/configs");
  const configs = data.configs || [];
  const embeddingConfigs: EmbeddingModelConfig[] = [];
  const chatConfigs: ChatModelConfig[] = [];
  let activeEmbedding: string | undefined;
  let activeChat: string | undefined;

  for (const c of configs) {
    // Chat/LLM providers: openai-compatible, custom, or any provider that is not embedding-specific
    const isEmbedding = c.provider && (c.provider.includes("doubao") || c.provider.includes("embed"));
    if (!isEmbedding) {
      const chat: ChatModelConfig = {
        id: c.id,
        type: "chat",
        name: c.name || c.display_name || "",
        provider: c.provider,
        apiKey: c.apiKey || "",
        is_server_managed: Boolean(c.is_server_managed),
        baseUrl: c.baseUrl,
        modelId: c.modelId || c.model_id || "",
        enabled: c.enabled !== false,
        createdAt: c.created_at || new Date().toISOString(),
        updatedAt: c.updated_at || new Date().toISOString(),
        testStatus: c.testStatus || "untested",
        testMessage: c.testMessage,
        temperature: c.temperature,
        maxOutputTokens: c.maxOutputTokens,
        timeoutMs: c.timeoutMs,
        responseMimeType: c.responseMimeType,
        streamApiMode: c.streamApiMode || c.stream_api_mode,
        promptCacheEnabled: c.promptCacheEnabled ?? c.prompt_cache_enabled,
        promptCacheKey: c.promptCacheKey || c.prompt_cache_key,
        promptCacheKeyPrefix: c.promptCacheKeyPrefix || c.prompt_cache_key_prefix,
        promptCacheRetention: c.promptCacheRetention || c.prompt_cache_retention,
        fallbackModelId: c.fallbackModelId,
        testModelId: c.testModelId,
      };
      chatConfigs.push(chat);
      if (c.enabled !== false && !activeChat) activeChat = chat.id;
    } else {
      const embed: EmbeddingModelConfig = {
        id: c.id,
        type: "embedding",
        name: c.name || c.display_name || "",
        provider: c.provider,
        apiKey: c.apiKey || "",
        is_server_managed: Boolean(c.is_server_managed),
        modelId: c.modelId || c.model_id || "",
        enabled: c.enabled !== false,
        createdAt: c.created_at || new Date().toISOString(),
        updatedAt: c.updated_at || new Date().toISOString(),
        testStatus: c.testStatus || "untested",
        testMessage: c.testMessage,
        endpoint: c.endpoint,
        dimensions: c.dimensions,
        encodingFormat: c.encodingFormat,
        timeoutMs: c.timeoutMs,
        inputType: c.inputType,
      };
      embeddingConfigs.push(embed);
      if (c.enabled !== false && !activeEmbedding) activeEmbedding = embed.id;
    }
  }

  return {
    embeddingConfigs,
    chatConfigs,
    active: { embeddingConfigId: activeEmbedding, chatConfigId: activeChat },
  };
}

export async function saveConfigToServer(config: {
  id?: string;
  provider: string;
  modelId: string;
  name?: string;
  apiKey?: string;
  enabled?: boolean;
  [key: string]: any;
}): Promise<{ id: string }> {
  return apiFetch<{ id: string }>("/api/configs", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function deleteConfigFromServer(id: string): Promise<void> {
  await apiFetch(`/api/configs/${encodeURIComponent(id)}`, { method: "DELETE" });
}
