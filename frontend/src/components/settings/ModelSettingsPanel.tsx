import { useState, useCallback } from "react";
import type { ChatModelConfig, EmbeddingModelConfig } from "../../types/modelConfig";
type AnyModelConfig = EmbeddingModelConfig | ChatModelConfig;
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { ActiveModelSummary } from "./ActiveModelSummary";
import { ChatModelForm } from "./ChatModelForm";
import { EmbeddingModelForm } from "./EmbeddingModelForm";
import { ModelConfigCard } from "./ModelConfigCard";

interface ModelSettingsPanelProps {
  embeddingConfigs: EmbeddingModelConfig[];
  chatConfigs: ChatModelConfig[];
  activeEmbeddingConfig?: EmbeddingModelConfig;
  activeChatConfig?: ChatModelConfig;
  onSaveEmbedding: (config: EmbeddingModelConfig) => Promise<void> | void;
  onSaveChat: (config: ChatModelConfig) => Promise<void> | void;
  onDeleteEmbedding: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onSetActiveEmbedding: (id: string) => void;
  onSetActiveChat: (id: string) => void;
  onTestEmbedding: (config: EmbeddingModelConfig) => void | Promise<any>;
  onTestChat: (config: ChatModelConfig) => void | Promise<any>;
  onClearAll: () => void;
}

export function ModelSettingsPanel({
  embeddingConfigs,
  chatConfigs,
  activeEmbeddingConfig,
  activeChatConfig,
  onSaveEmbedding,
  onSaveChat,
  onDeleteEmbedding,
  onDeleteChat,
  onSetActiveEmbedding,
  onSetActiveChat,
  onTestEmbedding,
  onTestChat,
  onClearAll,
}: ModelSettingsPanelProps) {
  const [editingEmbedding, setEditingEmbedding] = useState<EmbeddingModelConfig | undefined>();
  const [editingChat, setEditingChat] = useState<ChatModelConfig | undefined>();
  const [showEmbeddingForm, setShowEmbeddingForm] = useState(false);
  const [showChatForm, setShowChatForm] = useState(false);

  const handleEditEmbedding = useCallback((item: AnyModelConfig) => {
    setEditingEmbedding(item as EmbeddingModelConfig);
    setShowEmbeddingForm(true);
  }, []);

  const handleEditChat = useCallback((item: AnyModelConfig) => {
    setEditingChat(item as ChatModelConfig);
    setShowChatForm(true);
  }, []);

  function clearAll() {
    if (window.confirm("确定清除所有模型配置吗？API Key 也会从当前浏览器本地存储中删除。")) onClearAll();
  }

  return (
    <div className="settings-grid">
      <ActiveModelSummary embeddingConfig={activeEmbeddingConfig} chatConfig={activeChatConfig} />

      <Card
        title="向量模型配置"
        description="用于对 JD 和简历文本 chunks 做向量化召回。"
        action={
          <Button
            type="button"
            variant="primary"
            onClick={() => {
              setEditingEmbedding(undefined);
              setShowEmbeddingForm(true);
            }}
          >
            新增向量模型配置
          </Button>
        }
      >
        {showEmbeddingForm && (
          <EmbeddingModelForm
            editingConfig={editingEmbedding}
            onSave={async (config) => {
              await onSaveEmbedding(config);
              setShowEmbeddingForm(false);
            }}
            onCancel={() => setShowEmbeddingForm(false)}
          />
        )}
        <div className="model-list">
          {embeddingConfigs.map((config) => (
            <ModelConfigCard
              key={config.id}
              config={config}
              active={config.id === activeEmbeddingConfig?.id}
              onEdit={handleEditEmbedding}
              onDelete={onDeleteEmbedding}
              onSetActive={onSetActiveEmbedding}
              onTest={onTestEmbedding as (config: AnyModelConfig) => void}
            />
          ))}
          {!embeddingConfigs.length && <p className="muted-line">还没有向量模型配置。</p>}
        </div>
      </Card>

      <Card
        title="大语言模型配置"
        description="支持 OpenAI 兼容的大语言模型。填写 API Key、Base URL 和 Model ID 即可使用。"
        action={
          <Button
            type="button"
            variant="primary"
            onClick={() => {
              setEditingChat(undefined);
              setShowChatForm(true);
            }}
          >
            新增大语言模型配置
          </Button>
        }
      >
        {showChatForm && (
          <ChatModelForm
            editingConfig={editingChat}
            onSave={async (config) => {
              await onSaveChat(config);
              setShowChatForm(false);
            }}
            onCancel={() => setShowChatForm(false)}
          />
        )}
        <div className="model-list">
          {chatConfigs.map((config) => (
            <ModelConfigCard
              key={config.id}
              config={config}
              active={config.id === activeChatConfig?.id}
              onEdit={handleEditChat}
              onDelete={onDeleteChat}
              onSetActive={onSetActiveChat}
              onTest={onTestChat as (config: AnyModelConfig) => void}
            />
          ))}
          {!chatConfigs.length && <p className="muted-line">还没有大语言模型配置。</p>}
        </div>
      </Card>

      <Card title="安全设置">
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div>
            <h4 style={{ color: "var(--accent-hover)", fontSize: "14px", fontWeight: "700", marginBottom: "6px" }}>🔒 登录保护</h4>
            <ul style={{ margin: "0", paddingLeft: "20px", fontSize: "13px", color: "var(--muted)", lineHeight: "1.6" }}>
              <li>当前账号已启用登录保护。</li>
              <li>建议定期更换密码以保障账户安全。</li>
            </ul>
          </div>
          <div>
            <h4 style={{ color: "var(--accent-hover)", fontSize: "14px", fontWeight: "700", marginBottom: "6px" }}>🔑 API 密钥安全</h4>
            <ul style={{ margin: "0", paddingLeft: "20px", fontSize: "13px", color: "var(--muted)", lineHeight: "1.6" }}>
              <li>生产环境下，API 密钥由服务器安全托管。</li>
              <li>前端从不显示、保存或传输任何真实生产环境的 API 密钥。</li>
              <li>如果你怀疑密钥在其他渠道泄露，请立即前往服务商模型平台重置。</li>
            </ul>
          </div>
          <div>
            <h4 style={{ color: "var(--accent-hover)", fontSize: "14px", fontWeight: "700", marginBottom: "6px" }}>🛡️ 数据隐私</h4>
            <ul style={{ margin: "0", paddingLeft: "20px", fontSize: "13px", color: "var(--muted)", lineHeight: "1.6" }}>
              <li>简历、岗位 JD 和历史分析属于高度个人隐私。</li>
              <li>系统不会在服务端日志中记录完整简历、完整 JD 文本、提示词或 API 返回体。</li>
              <li>你可以在历史记录管理页面中随时彻底删除历史分析。</li>
            </ul>
          </div>
          <div>
            <h4 style={{ color: "var(--accent-hover)", fontSize: "14px", fontWeight: "700", marginBottom: "6px" }}>🚀 部署建议</h4>
            <ul style={{ margin: "0", paddingLeft: "20px", fontSize: "13px", color: "var(--muted)", lineHeight: "1.6" }}>
              <li>请确保云服务器上线运行已启用 HTTPS 加密证书。</li>
              <li>请检查 <code>.gitignore</code>，严防把包含真实密钥的 <code>.env</code> 文件推送到公开 Git。</li>
              <li>限制服务器数据库的公网监听端口，只允许内网安全访问。</li>
            </ul>
          </div>
        </div>
      </Card>
    </div>
  );
}
