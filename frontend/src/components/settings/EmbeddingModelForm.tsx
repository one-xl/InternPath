import { useEffect, useState } from "react";
import type { EmbeddingModelConfig, EmbeddingProvider } from "../../types/modelConfig";
import { Button } from "../ui/Button";
import { ApiKeyInput } from "./ApiKeyInput";
import { safeUUID } from "../../utils/uuid";

const DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3";
const DEFAULT_MULTIMODAL_MODEL = "doubao-embedding-vision-250615";
const DOUBAO_MULTIMODAL_EMBEDDING_ENDPOINT = "/embeddings/multimodal";

function providerLabel(provider: EmbeddingProvider): string {
  return "Doubao Multimodal Embedding";
}

function createDefault(provider: EmbeddingProvider = "doubao-multimodal"): EmbeddingModelConfig {
  const now = new Date().toISOString();
  return {
    id: safeUUID(),
    type: "embedding",
    name: providerLabel(provider),
    provider,
    apiKey: "",
    baseUrl: DEFAULT_BASE_URL,
    endpoint: DOUBAO_MULTIMODAL_EMBEDDING_ENDPOINT,
    modelId: DEFAULT_MULTIMODAL_MODEL,
    enabled: true,
    createdAt: now,
    updatedAt: now,
    testStatus: "untested",
    timeoutMs: 60000,
    dimensions: 1024,
    encodingFormat: "float",
    inputType: "multimodal",
  };
}

export function EmbeddingModelForm({
  editingConfig,
  onSave,
  onCancel,
}: {
  editingConfig?: EmbeddingModelConfig;
  onSave: (config: EmbeddingModelConfig) => Promise<void> | void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<EmbeddingModelConfig>(() => {
    const base = editingConfig ?? createDefault();
    return { ...base, apiKey: "" };
  });
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const base = editingConfig ?? createDefault();
    setDraft({ ...base, apiKey: "" });
    setError(null);
  }, [editingConfig]);

  async function submit() {
    if (!draft.baseUrl?.trim() || !draft.modelId.trim()) return;
    setIsSaving(true);
    setError(null);
    try {
      await onSave({
        ...draft,
        provider: "doubao-multimodal",
        name: providerLabel(draft.provider),
        endpoint: draft.endpoint || DOUBAO_MULTIMODAL_EMBEDDING_ENDPOINT,
        inputType: "multimodal",
        updatedAt: new Date().toISOString(),
      });
    } catch (err: any) {
      console.error("[EmbeddingModelForm] Save failed:", err);
      setError(err.message || "保存配置失败，请检查配置参数及网络状态");
      setIsSaving(false);
    }
  }

  const isDoubao = draft.provider === "doubao-multimodal";
  const needsFix =
    isDoubao &&
    (draft.endpoint === "/embeddings" ||
      draft.inputType === "text" ||
      (draft.modelId?.includes("embedding-vision") && draft.endpoint !== "/embeddings/multimodal"));

  return (
    <div className="settings-editor">
      <div className="settings-editor-head">
        <h3>{editingConfig ? "编辑 Doubao 向量模型" : "新增 Doubao 向量模型"}</h3>
        <p>
          当前项目使用 Doubao Multimodal Embedding 作为统一向量模型。即使输入是普通文本，也会按多模态接口要求包装为：
          <code>[{"{"} type: "text", text: "..." {"}"}]</code>。该接口也可扩展支持图片、扫描件、作品集截图 and 视频材料。
        </p>
      </div>

      {needsFix && (
        <div style={{
          margin: "12px 0",
          padding: "12px 14px",
          background: "#fffbeb",
          border: "1px solid #fef3c7",
          color: "#b45309",
          borderRadius: "6px",
          fontSize: "13px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "12px"
        }}>
          <span>检测到当前配置与多模态向量规范不符，请更新以确保连通性。</span>
          <Button
            type="button"
            variant="secondary"
            onClick={() => setDraft({
              ...draft,
              provider: "doubao-multimodal",
              endpoint: DOUBAO_MULTIMODAL_EMBEDDING_ENDPOINT,
              inputType: "multimodal",
              encodingFormat: "float",
              dimensions: 1024,
              modelId: DEFAULT_MULTIMODAL_MODEL,
              _suggestedEndpoint: undefined
            })}
            disabled={isSaving}
          >
            一键切换为 Doubao 多模态向量接口
          </Button>
        </div>
      )}

      <div className="settings-form">
        <label className="field">
          <span>API Key</span>
          <ApiKeyInput
            value={draft.apiKey}
            onChange={(apiKey) => setDraft({ ...draft, apiKey })}
            placeholder={editingConfig ? "留空表示继续使用已保存的 Doubao API Key" : "输入 Doubao API Key"}
          />
        </label>
        <label className="field">
          <span>Model ID</span>
          <input
            value={draft.modelId}
            onChange={(event) => setDraft({ ...draft, modelId: event.target.value })}
            placeholder={DEFAULT_MULTIMODAL_MODEL}
            disabled={isSaving}
          />
          <small>
            可填 {DEFAULT_MULTIMODAL_MODEL}，或火山方舟控制台你实际开通的接入点 Endpoint ID。
          </small>
        </label>
        <label className="field">
          <span>Base URL</span>
          <input value={draft.baseUrl ?? ""} onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })} disabled={isSaving} />
        </label>

        <label className="field">
          <span>Endpoint</span>
          <input value={draft.endpoint ?? ""} onChange={(event) => setDraft({ ...draft, endpoint: event.target.value })} disabled={isSaving} />
          <small>
            多模态接口固定建议为 /embeddings/multimodal，请求体包含 encoding_format 与 dimensions。
          </small>
        </label>

        <div className="form-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px" }}>
          <label className="field">
            <span>Dimensions（尺寸）</span>
            <select
              value={draft.dimensions ?? 1024}
              onChange={(event) => setDraft({ ...draft, dimensions: Number(event.target.value) as 1024 | 2048 })}
              disabled={isSaving}
            >
              <option value="1024">1024 (默认)</option>
              <option value="2048">2048</option>
            </select>
          </label>
          <label className="field">
            <span>Encoding Format</span>
            <select
              value={draft.encodingFormat ?? "float"}
              onChange={(event) => setDraft({ ...draft, encodingFormat: event.target.value as any })}
              disabled={isSaving}
            >
              <option value="float">float</option>
              <option value="base64">base64</option>
            </select>
          </label>
          <label className="field">
            <span>Timeout (ms)</span>
            <input
              type="number"
              value={draft.timeoutMs ?? 60000}
              onChange={(event) => setDraft({ ...draft, timeoutMs: Number(event.target.value) })}
              disabled={isSaving}
            />
          </label>
        </div>
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
        <Button type="button" variant="primary" onClick={submit} disabled={!draft.baseUrl?.trim() || !draft.modelId.trim() || isSaving}>
          {isSaving ? "正在保存..." : "保存配置"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={isSaving}>
          取消
        </Button>
      </div>
    </div>
  );
}
