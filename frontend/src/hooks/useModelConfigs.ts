import { useMemo, useState } from "react";
import { testChatModelConfig, testEmbeddingModelConfig } from "../services/modelConfigService";
import type { ChatModelConfig, EmbeddingModelConfig, ModelConfigState } from "../types/modelConfig";
import { safeUUID } from "../utils/uuid";
import {
  clearAllModelConfigs,
  deleteChatConfig as deleteChatConfigFromStorage,
  deleteEmbeddingConfig as deleteEmbeddingConfigFromStorage,
  getModelConfigState,
  saveChatConfig as saveChatConfigToStorage,
  saveEmbeddingConfig as saveEmbeddingConfigToStorage,
  setActiveChatConfig as setActiveChatConfigInStorage,
  setActiveEmbeddingConfig as setActiveEmbeddingConfigInStorage,
} from "../utils/modelConfigStorage";

function stamp<T extends { id?: string; createdAt?: string; updatedAt?: string; testStatus?: string }>(config: T): T {
  const now = new Date().toISOString();
  return {
    ...config,
    id: config.id || safeUUID(),
    createdAt: config.createdAt || now,
    updatedAt: now,
    testStatus: config.testStatus || "untested",
  };
}

function withLatency(message: string, latencyMs?: number): string {
  return latencyMs ? `${message}，${latencyMs}ms` : message;
}

export function useModelConfigs() {
  const [state, setState] = useState<ModelConfigState>(() => getModelConfigState());

  const activeEmbeddingConfig = useMemo(
    () => state.embeddingConfigs.find((item) => item.id === state.active.embeddingConfigId),
    [state.active.embeddingConfigId, state.embeddingConfigs],
  );
  const activeChatConfig = useMemo(
    () => state.chatConfigs.find((item) => item.id === state.active.chatConfigId),
    [state.active.chatConfigId, state.chatConfigs],
  );

  function saveEmbeddingConfig(config: EmbeddingModelConfig) {
    setState(saveEmbeddingConfigToStorage(stamp(config) as EmbeddingModelConfig));
  }

  function saveChatConfig(config: ChatModelConfig) {
    setState(saveChatConfigToStorage(stamp(config) as ChatModelConfig));
  }

  function deleteEmbeddingConfig(id: string) {
    setState(deleteEmbeddingConfigFromStorage(id));
  }

  function deleteChatConfig(id: string) {
    setState(deleteChatConfigFromStorage(id));
  }

  function setActiveEmbeddingConfig(id: string) {
    setState(setActiveEmbeddingConfigInStorage(id));
  }

  function setActiveChatConfig(id: string) {
    setState(setActiveChatConfigInStorage(id));
  }

  async function testEmbeddingConfig(config: EmbeddingModelConfig) {
    const testing = { ...config, testStatus: "testing" as const, testMessage: "正在测试连接..." };
    saveEmbeddingConfig(testing);
    const result = await testEmbeddingModelConfig(config);
    saveEmbeddingConfig({
      ...testing,
      testStatus: result.ok ? "success" : "failed",
      testMessage: withLatency(result.message, result.latencyMs),
      lastTestedAt: new Date().toISOString(),
      testDiagnostics: (result as any).diagnostics,
    });
    return result;
  }

  async function testChatConfig(config: ChatModelConfig) {
    const testing = { ...config, testStatus: "testing" as const, testMessage: "正在测试连接..." };
    saveChatConfig(testing);
    const result = await testChatModelConfig(config, (msg) => {
      saveChatConfig({
        ...testing,
        testStatus: "testing",
        testMessage: msg,
      });
    });
    saveChatConfig({
      ...testing,
      testStatus: result.ok ? "success" : "failed",
      testMessage: withLatency(result.message, result.latencyMs),
      lastTestedAt: new Date().toISOString(),
      testDiagnostics: (result as any).diagnostics,
    });
    return result;
  }

  function clearAllConfigs() {
    setState(clearAllModelConfigs());
  }

  return {
    state,
    activeEmbeddingConfig,
    activeChatConfig,
    saveEmbeddingConfig,
    saveChatConfig,
    deleteEmbeddingConfig,
    deleteChatConfig,
    setActiveEmbeddingConfig,
    setActiveChatConfig,
    testEmbeddingConfig,
    testChatConfig,
    clearAllConfigs,
  };
}
