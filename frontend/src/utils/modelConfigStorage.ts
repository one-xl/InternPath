import type { ChatModelConfig, EmbeddingModelConfig, ModelConfigState } from "../types/modelConfig";

export const MODEL_CONFIG_STORAGE_KEY = "job-desk:model-configs";

const emptyState: ModelConfigState = {
  embeddingConfigs: [],
  chatConfigs: [],
  active: {},
};

function readState(): ModelConfigState {
  try {
    const raw = localStorage.getItem(MODEL_CONFIG_STORAGE_KEY);
    if (!raw) return emptyState;
    const parsed = JSON.parse(raw) as ModelConfigState;
    
    const embeddingConfigs = (Array.isArray(parsed.embeddingConfigs) ? parsed.embeddingConfigs : []).map(config => {
      let provider = config.provider;
      let endpoint = config.endpoint;
      let modelId = config.modelId;
      let dimensions = config.dimensions;
      let encodingFormat = config.encodingFormat;
      let inputType = config.inputType;

      const isDoubao =
        (provider as string) === "doubao" ||
        provider === "doubao-text" ||
        provider === "doubao-multimodal" ||
        (provider as string) === "doubao-text-embedding" ||
        (provider as string) === "doubao-multimodal-embedding";

      if (isDoubao) {
        provider = "doubao-multimodal";
        if (!modelId) {
          modelId = "doubao-embedding-vision-250615";
        }
        if (dimensions !== 1024 && dimensions !== 2048) {
          dimensions = 1024;
        }
        if (!encodingFormat) {
          encodingFormat = "float";
        }
      }

      let _suggestedEndpoint: string | undefined = undefined;
      const needsFix =
        isDoubao &&
        (endpoint === "/embeddings" ||
          inputType === "text" ||
          (modelId?.includes("embedding-vision") && endpoint !== "/embeddings/multimodal"));

      if (needsFix) {
        _suggestedEndpoint = "/embeddings/multimodal";
      }

      return {
        ...config,
        provider,
        endpoint,
        modelId,
        dimensions,
        encodingFormat,
        inputType: isDoubao ? "multimodal" : inputType,
        _suggestedEndpoint,
      };
    });

    return {
      embeddingConfigs,
      chatConfigs: Array.isArray(parsed.chatConfigs) ? parsed.chatConfigs : [],
      active: parsed.active ?? {},
    };
  } catch {
    return emptyState;
  }
}

function writeState(state: ModelConfigState): ModelConfigState {
  localStorage.setItem(MODEL_CONFIG_STORAGE_KEY, JSON.stringify(state));
  return state;
}

export function maskApiKey(apiKey: string): string {
  if (!apiKey) return "未填写";
  if (apiKey.length <= 8) return "****";
  return `${apiKey.slice(0, 3)}-****${apiKey.slice(-4)}`;
}

export function getModelConfigState(): ModelConfigState {
  return readState();
}

export function saveEmbeddingConfig(config: EmbeddingModelConfig): ModelConfigState {
  const state = readState();
  const configs = [config, ...state.embeddingConfigs.filter((item) => item.id !== config.id)];
  const active = state.active.embeddingConfigId ? state.active : { ...state.active, embeddingConfigId: config.id };
  return writeState({ ...state, embeddingConfigs: configs, active });
}

export function saveChatConfig(config: ChatModelConfig): ModelConfigState {
  const state = readState();
  const configs = [config, ...state.chatConfigs.filter((item) => item.id !== config.id)];
  const active = state.active.chatConfigId ? state.active : { ...state.active, chatConfigId: config.id };
  return writeState({ ...state, chatConfigs: configs, active });
}

export function deleteEmbeddingConfig(id: string): ModelConfigState {
  const state = readState();
  return writeState({
    ...state,
    embeddingConfigs: state.embeddingConfigs.filter((item) => item.id !== id),
    active: {
      ...state.active,
      embeddingConfigId: state.active.embeddingConfigId === id ? undefined : state.active.embeddingConfigId,
    },
  });
}

export function deleteChatConfig(id: string): ModelConfigState {
  const state = readState();
  return writeState({
    ...state,
    chatConfigs: state.chatConfigs.filter((item) => item.id !== id),
    active: {
      ...state.active,
      chatConfigId: state.active.chatConfigId === id ? undefined : state.active.chatConfigId,
    },
  });
}

export function setActiveEmbeddingConfig(id: string): ModelConfigState {
  const state = readState();
  return writeState({ ...state, active: { ...state.active, embeddingConfigId: id } });
}

export function setActiveChatConfig(id: string): ModelConfigState {
  const state = readState();
  return writeState({ ...state, active: { ...state.active, chatConfigId: id } });
}

export function getActiveEmbeddingConfig(): EmbeddingModelConfig | undefined {
  const state = readState();
  return state.embeddingConfigs.find((item) => item.id === state.active.embeddingConfigId);
}

export function getActiveChatConfig(): ChatModelConfig | undefined {
  const state = readState();
  return state.chatConfigs.find((item) => item.id === state.active.chatConfigId);
}

export function clearAllModelConfigs(): ModelConfigState {
  return writeState(emptyState);
}
