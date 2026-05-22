import { useCallback, useEffect, useMemo, useState } from "react";
import { testChatModelConfig, testEmbeddingModelConfig } from "../services/modelConfigService";
import { fetchConfigs, saveConfigToServer, deleteConfigFromServer } from "../services/configService";
import type { ChatModelConfig, EmbeddingModelConfig, ModelConfigState } from "../types/modelConfig";
import { safeUUID } from "../utils/uuid";
import { loadFromStorage, saveToStorage } from "../utils/storage";

const ACTIVE_KEY = "job-desk:active-configs";

function loadActive(): { embeddingConfigId?: string; chatConfigId?: string } {
  return loadFromStorage(ACTIVE_KEY, {});
}

function saveActive(active: { embeddingConfigId?: string; chatConfigId?: string }) {
  saveToStorage(ACTIVE_KEY, active);
}

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

export function useModelConfigs(enabled = true) {
  const [state, setState] = useState<ModelConfigState>({
    embeddingConfigs: [],
    chatConfigs: [],
    active: loadActive(),
  });

  const reload = useCallback(async () => {
    if (!enabled) {
      setState({ embeddingConfigs: [], chatConfigs: [], active: loadActive() });
      return;
    }

    try {
      const serverState = await fetchConfigs();
      const savedActive = loadActive();
      setState({
        ...serverState,
        active: {
          embeddingConfigId: savedActive.embeddingConfigId || serverState.active.embeddingConfigId,
          chatConfigId: savedActive.chatConfigId || serverState.active.chatConfigId,
        },
      });
    } catch (err) {
      console.error("[model-configs] Failed to load from server:", err);
    }
  }, [enabled]);

  useEffect(() => {
    reload();
  }, [reload]);

  const activeEmbeddingConfig = useMemo(
    () => state.embeddingConfigs.find((item) => item.id === state.active.embeddingConfigId),
    [state.active.embeddingConfigId, state.embeddingConfigs],
  );
  const activeChatConfig = useMemo(
    () => state.chatConfigs.find((item) => item.id === state.active.chatConfigId),
    [state.active.chatConfigId, state.chatConfigs],
  );

  function persistState(next: ModelConfigState) {
    setState(next);
    saveActive(next.active);
  }

  async function saveEmbeddingConfig(config: EmbeddingModelConfig) {
    const stamped = stamp(config);
    try {
      await saveConfigToServer({
        id: stamped.id,
        provider: stamped.provider,
        modelId: stamped.modelId,
        name: stamped.name,
        apiKey: stamped.apiKey,
        enabled: stamped.enabled,
        endpoint: stamped.endpoint,
        dimensions: stamped.dimensions,
        encodingFormat: stamped.encodingFormat,
        timeoutMs: stamped.timeoutMs,
        inputType: stamped.inputType,
      });
    } catch (err) {
      console.error("[model-configs] Save embedding config failed:", err);
    }
    await reload();
  }

  async function saveChatConfig(config: ChatModelConfig) {
    const stamped = stamp(config);
    try {
      await saveConfigToServer({
        id: stamped.id,
        provider: stamped.provider,
        modelId: stamped.modelId,
        name: stamped.name,
        apiKey: stamped.apiKey,
        enabled: stamped.enabled,
        temperature: stamped.temperature,
        maxOutputTokens: stamped.maxOutputTokens,
        timeoutMs: stamped.timeoutMs,
        responseMimeType: stamped.responseMimeType,
        fallbackModelId: stamped.fallbackModelId,
        testModelId: stamped.testModelId,
      });
    } catch (err) {
      console.error("[model-configs] Save chat config failed:", err);
    }
    await reload();
  }

  async function deleteEmbeddingConfig(id: string) {
    try {
      await deleteConfigFromServer(id);
    } catch (err) {
      console.error("[model-configs] Delete embedding config failed:", err);
    }
    const next = {
      ...state,
      embeddingConfigs: state.embeddingConfigs.filter((item) => item.id !== id),
      active: {
        ...state.active,
        embeddingConfigId: state.active.embeddingConfigId === id ? undefined : state.active.embeddingConfigId,
      },
    };
    persistState(next);
    await reload();
  }

  async function deleteChatConfig(id: string) {
    try {
      await deleteConfigFromServer(id);
    } catch (err) {
      console.error("[model-configs] Delete chat config failed:", err);
    }
    const next = {
      ...state,
      chatConfigs: state.chatConfigs.filter((item) => item.id !== id),
      active: {
        ...state.active,
        chatConfigId: state.active.chatConfigId === id ? undefined : state.active.chatConfigId,
      },
    };
    persistState(next);
    await reload();
  }

  function setActiveEmbeddingConfig(id: string) {
    persistState({ ...state, active: { ...state.active, embeddingConfigId: id } });
  }

  function setActiveChatConfig(id: string) {
    persistState({ ...state, active: { ...state.active, chatConfigId: id } });
  }

  async function testEmbeddingConfig(config: EmbeddingModelConfig) {
    const testing = { ...config, testStatus: "testing" as const, testMessage: "正在测试连接..." };
    setState((prev) => ({
      ...prev,
      embeddingConfigs: prev.embeddingConfigs.map((c) => (c.id === testing.id ? testing : c)),
    }));
    const result = await testEmbeddingModelConfig(config);
    const updated = {
      ...testing,
      testStatus: result.ok ? "success" as const : "failed" as const,
      testMessage: withLatency(result.message, result.latencyMs),
      lastTestedAt: new Date().toISOString(),
      testDiagnostics: (result as any).diagnostics,
    };
    setState((prev) => ({
      ...prev,
      embeddingConfigs: prev.embeddingConfigs.map((c) => (c.id === updated.id ? updated : c)),
    }));
    return result;
  }

  async function testChatConfig(config: ChatModelConfig) {
    const testing = { ...config, testStatus: "testing" as const, testMessage: "正在测试连接..." };
    setState((prev) => ({
      ...prev,
      chatConfigs: prev.chatConfigs.map((c) => (c.id === testing.id ? testing : c)),
    }));
    const result = await testChatModelConfig(config, (msg) => {
      setState((prev) => ({
        ...prev,
        chatConfigs: prev.chatConfigs.map((c) => (c.id === testing.id ? { ...c, testMessage: msg } : c)),
      }));
    });
    const updated = {
      ...testing,
      testStatus: result.ok ? "success" as const : "failed" as const,
      testMessage: withLatency(result.message, result.latencyMs),
      lastTestedAt: new Date().toISOString(),
      testDiagnostics: (result as any).diagnostics,
    };
    setState((prev) => ({
      ...prev,
      chatConfigs: prev.chatConfigs.map((c) => (c.id === updated.id ? updated : c)),
    }));
    return result;
  }

  async function clearAllConfigs() {
    for (const c of state.embeddingConfigs) {
      try { await deleteConfigFromServer(c.id); } catch {}
    }
    for (const c of state.chatConfigs) {
      try { await deleteConfigFromServer(c.id); } catch {}
    }
    persistState({ embeddingConfigs: [], chatConfigs: [], active: {} });
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
    reload,
  };
}
