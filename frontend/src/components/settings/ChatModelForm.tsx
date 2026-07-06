import { useEffect, useState } from "react";
import type { ChatModelConfig, ChatProvider, StreamApiMode } from "../../types/modelConfig";
import { Button } from "../ui/Button";
import { safeUUID } from "../../utils/uuid";
import { ApiKeyInput } from "./ApiKeyInput";

const GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta";
const GEMINI_DEFAULT_MODEL = "gemini-flash-latest";

function providerLabel(provider: ChatProvider): string {
  if (provider === "gemini") return "Gemini";
  if (provider === "openai-compatible") return "OpenAI Compatible";
  return "Custom";
}

function nameFromProviderModel(provider: ChatProvider, modelId: string): string {
  const label = providerLabel(provider);
  return modelId.trim() ? `${label} ${modelId.trim()}` : label;
}

function providerDefaults(provider: ChatProvider): Pick<ChatModelConfig, "baseUrl" | "modelId" | "responseMimeType"> {
  if (provider === "gemini") {
    return {
      baseUrl: GEMINI_BASE_URL,
      modelId: GEMINI_DEFAULT_MODEL,
      responseMimeType: "application/json",
    };
  }

  return {
    baseUrl: "",
    modelId: "",
    responseMimeType: "application/json",
  };
}

function createDefault(): ChatModelConfig {
  const now = new Date().toISOString();
  const defaults = providerDefaults("gemini");
  return {
    id: safeUUID(),
    type: "chat",
    name: nameFromProviderModel("gemini", defaults.modelId),
    provider: "gemini",
    apiKey: "",
    baseUrl: defaults.baseUrl,
    modelId: defaults.modelId,
    enabled: true,
    createdAt: now,
    updatedAt: now,
    testStatus: "untested",
    temperature: 0.2,
    maxOutputTokens: 4096,
    responseMimeType: defaults.responseMimeType,
    streamApiMode: "chat_completions",
    timeoutMs: 60000,
  };
}

export function ChatModelForm({
  editingConfig,
  onSave,
  onCancel,
}: {
  editingConfig?: ChatModelConfig;
  onSave: (config: ChatModelConfig) => Promise<void> | void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<ChatModelConfig>(() => {
    const base = editingConfig ?? createDefault();
    return { ...base, apiKey: "", streamApiMode: base.streamApiMode ?? "chat_completions" };
  });
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const base = editingConfig ?? createDefault();
    setDraft({ ...base, apiKey: "", streamApiMode: base.streamApiMode ?? "chat_completions" });
    setError(null);
  }, [editingConfig]);

  function changeProvider(provider: ChatProvider) {
    const defaults = providerDefaults(provider);
    const currentIsGeminiDefault =
      draft.provider === "gemini" &&
      (!draft.modelId.trim() || draft.modelId === GEMINI_DEFAULT_MODEL) &&
      (!draft.baseUrl?.trim() || draft.baseUrl === GEMINI_BASE_URL);

    setDraft({
      ...draft,
      provider,
      modelId: currentIsGeminiDefault || !editingConfig ? defaults.modelId : draft.modelId,
      baseUrl: currentIsGeminiDefault || !editingConfig ? defaults.baseUrl : draft.baseUrl,
      responseMimeType: draft.responseMimeType ?? defaults.responseMimeType,
    });
  }

  async function submit() {
    const modelId = draft.modelId.trim();
    if (!modelId) return;

    setIsSaving(true);
    setError(null);
    try {
      await onSave({
        ...draft,
        provider: draft.provider,
        modelId,
        baseUrl: draft.baseUrl?.trim(),
        fallbackModelId: draft.fallbackModelId?.trim(),
        testModelId: draft.testModelId?.trim(),
        streamApiMode: draft.streamApiMode ?? "chat_completions",
        name: nameFromProviderModel(draft.provider, modelId),
        updatedAt: new Date().toISOString(),
      });
    } catch (err: any) {
      console.error("[ChatModelForm] Save failed:", err);
      setError(err.message || "保存配置失败，请检查配置参数及网络状态");
      setIsSaving(false);
    }
  }

  const isGemini = draft.provider === "gemini";

  return (
    <div className="settings-editor">
      <div className="settings-editor-head">
        <h3>{editingConfig ? "编辑大语言模型配置" : "新增大语言模型配置"}</h3>
      </div>
      <div className="settings-form">
        <label className="field">
          <span>Provider</span>
          <select value={draft.provider} onChange={(event) => changeProvider(event.target.value as ChatProvider)} disabled={isSaving}>
            <option value="gemini">Gemini</option>
            <option value="openai-compatible">OpenAI Compatible</option>
            <option value="custom">Custom</option>
          </select>
        </label>

        <label className="field">
          <span>API Key</span>
          <ApiKeyInput
            value={draft.apiKey}
            onChange={(apiKey) => setDraft({ ...draft, apiKey })}
            placeholder={editingConfig ? "留空表示继续使用已保存的 API Key" : "输入 API Key"}
          />
        </label>

        <label className="field">
          <span>Model ID</span>
          <input
            value={draft.modelId}
            onChange={(event) => setDraft({ ...draft, modelId: event.target.value })}
            placeholder={isGemini ? GEMINI_DEFAULT_MODEL : "输入模型 ID"}
            disabled={isSaving}
          />
        </label>

        <label className="field">
          <span>备用 Model ID</span>
          <input
            value={draft.fallbackModelId ?? ""}
            onChange={(event) => setDraft({ ...draft, fallbackModelId: event.target.value })}
            placeholder={isGemini ? "例如 gemini-2.5-flash" : "可选"}
            disabled={isSaving}
          />
        </label>

        <label className="field">
          <span>测试 Model ID</span>
          <input
            value={draft.testModelId ?? ""}
            onChange={(event) => setDraft({ ...draft, testModelId: event.target.value })}
            placeholder={isGemini ? "例如 gemini-2.5-flash" : "可选"}
            disabled={isSaving}
          />
        </label>

        <div className="form-grid">
          <label className="field">
            <span>Temperature</span>
            <input
              type="number"
              min="0"
              max="2"
              step="0.1"
              value={draft.temperature ?? 0.2}
              onChange={(event) => setDraft({ ...draft, temperature: Number(event.target.value) })}
              disabled={isSaving}
            />
          </label>
          <label className="field">
            <span>Max Output Tokens</span>
            <input
              type="number"
              min="1"
              value={draft.maxOutputTokens ?? 4096}
              onChange={(event) => setDraft({ ...draft, maxOutputTokens: Number(event.target.value) })}
              disabled={isSaving}
            />
          </label>
        </div>

        <div className="form-grid">
          <label className="field">
            <span>Response MIME Type</span>
            <select
              value={draft.responseMimeType ?? "application/json"}
              onChange={(event) => setDraft({ ...draft, responseMimeType: event.target.value as ChatModelConfig["responseMimeType"] })}
              disabled={isSaving}
            >
              <option value="application/json">application/json</option>
              <option value="text/plain">text/plain</option>
            </select>
          </label>
          <label className="field">
            <span>Timeout</span>
            <input
              type="number"
              value={draft.timeoutMs ?? 60000}
              onChange={(event) => setDraft({ ...draft, timeoutMs: Number(event.target.value) })}
              disabled={isSaving}
            />
          </label>
        </div>

        <details className="settings-details" open={!isGemini}>
          <summary>高级设置</summary>
          <div className="settings-form">
            <label className="field">
              <span>Base URL</span>
              <input
                value={draft.baseUrl ?? ""}
                onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })}
                placeholder={isGemini ? GEMINI_BASE_URL : "https://api.example.com/v1"}
                disabled={isSaving}
              />
            </label>
            <label className="field">
              <span>Stream API</span>
              <select
                value={draft.streamApiMode ?? "chat_completions"}
                onChange={(event) => setDraft({ ...draft, streamApiMode: event.target.value as StreamApiMode })}
                disabled={isSaving}
              >
                <option value="chat_completions">Chat Completions (/v1/chat/completions)</option>
                <option value="responses">Responses (/v1/responses)</option>
              </select>
            </label>
          </div>
        </details>
      </div>

      {error && (
        <div style={{
          marginTop: "16px",
          padding: "10px 14px",
          background: "#fef2f2",
          border: "1px solid #fca5a5",
          borderRadius: "6px",
          color: "#b91c1c",
          fontSize: "13px",
          fontWeight: "600"
        }}>
          ❌ {error}
        </div>
      )}

      <div className="settings-actions">
        <Button type="button" variant="primary" onClick={submit} disabled={!draft.modelId.trim() || isSaving}>
          {isSaving ? "正在保存..." : "保存配置"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={isSaving}>
          取消
        </Button>
      </div>
    </div>
  );
}
