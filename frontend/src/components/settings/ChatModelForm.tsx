import { useEffect, useState } from "react";
import type { ChatModelConfig } from "../../types/modelConfig";
import { Button } from "../ui/Button";
import { ApiKeyInput } from "./ApiKeyInput";
import { safeUUID } from "../../utils/uuid";

function nameFromModelId(modelId: string): string {
  return modelId.trim() ? `Gemini ${modelId.trim()}` : "Gemini";
}

function createDefault(): ChatModelConfig {
  const now = new Date().toISOString();
  const modelId = "gemini-flash-latest";
  return {
    id: safeUUID(),
    type: "chat",
    name: nameFromModelId(modelId),
    provider: "gemini",
    apiKey: "",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    modelId,
    enabled: true,
    createdAt: now,
    updatedAt: now,
    testStatus: "untested",
    temperature: 0.2,
    maxOutputTokens: 4096,
    responseMimeType: "application/json",
    timeoutMs: 60000,
  };
}

export function ChatModelForm({
  editingConfig,
  onSave,
  onCancel,
}: {
  editingConfig?: ChatModelConfig;
  onSave: (config: ChatModelConfig) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<ChatModelConfig>(() => {
    const base = editingConfig ?? createDefault();
    return { ...base, apiKey: "" };
  });

  useEffect(() => {
    const base = editingConfig ?? createDefault();
    setDraft({ ...base, apiKey: "" });
  }, [editingConfig]);

  function submit() {
    if (!draft.modelId.trim()) return;
    onSave({
      ...draft,
      name: nameFromModelId(draft.modelId),
      updatedAt: new Date().toISOString(),
    });
  }

  return (
    <div className="settings-editor">
      <div className="settings-editor-head">
        <h3>{editingConfig ? "编辑 Gemini 配置" : "新增 Gemini 配置"}</h3>
        <p>用户只需要填写 API Key 和模型参数；URL、headers、body、generateContent endpoint 都由代码自动生成。</p>
      </div>
      <div className="settings-form">
        <label className="field">
          <span>API Key</span>
          <ApiKeyInput
            value={draft.apiKey}
            onChange={(apiKey) => setDraft({ ...draft, apiKey })}
            placeholder={editingConfig ? "留空表示继续使用已保存的 Gemini API Key" : "输入 Gemini API Key"}
          />
        </label>
        <label className="field">
          <span>Model ID</span>
          <input value={draft.modelId} onChange={(event) => setDraft({ ...draft, modelId: event.target.value })} placeholder="gemini-flash-latest" />
        </label>
        <label className="field">
          <span>备用 Model ID (可选 fallbackModelId)</span>
          <input value={draft.fallbackModelId ?? ""} onChange={(event) => setDraft({ ...draft, fallbackModelId: event.target.value })} placeholder="例如 gemini-2.5-flash 或 gemini-flash-latest" />
        </label>
        <label className="field">
          <span>测试 Model ID (可选 testModelId)</span>
          <input value={draft.testModelId ?? ""} onChange={(event) => setDraft({ ...draft, testModelId: event.target.value })} placeholder="例如 gemini-2.5-flash，专门在连接测试中替代 Preview 模型" />
        </label>
        <div className="form-grid">
          <label className="field">
            <span>Temperature</span>
            <input type="number" min="0" max="2" step="0.1" value={draft.temperature ?? 0.2} onChange={(event) => setDraft({ ...draft, temperature: Number(event.target.value) })} />
          </label>
          <label className="field">
            <span>Max Output Tokens</span>
            <input type="number" min="1" value={draft.maxOutputTokens ?? 4096} onChange={(event) => setDraft({ ...draft, maxOutputTokens: Number(event.target.value) })} />
          </label>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>Response MIME Type</span>
            <select value={draft.responseMimeType ?? "application/json"} onChange={(event) => setDraft({ ...draft, responseMimeType: event.target.value as ChatModelConfig["responseMimeType"] })}>
              <option value="application/json">application/json</option>
              <option value="text/plain">text/plain</option>
            </select>
          </label>
          <label className="field">
            <span>Timeout</span>
            <input type="number" value={draft.timeoutMs ?? 60000} onChange={(event) => setDraft({ ...draft, timeoutMs: Number(event.target.value) })} />
          </label>
        </div>
        <details className="settings-details">
          <summary>高级设置</summary>
          <div className="settings-form">
            <label className="field">
              <span>Base URL</span>
              <input value={draft.baseUrl ?? ""} onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })} />
            </label>
          </div>
        </details>
      </div>
      <div className="settings-actions">
        <Button type="button" variant="primary" onClick={submit} disabled={!draft.modelId.trim()}>
          保存配置
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}
