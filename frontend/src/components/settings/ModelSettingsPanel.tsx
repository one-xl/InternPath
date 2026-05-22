import { useState } from "react";
import type { ChatModelConfig, EmbeddingModelConfig } from "../../types/modelConfig";
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
  onSaveEmbedding: (config: EmbeddingModelConfig) => void;
  onSaveChat: (config: ChatModelConfig) => void;
  onDeleteEmbedding: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onSetActiveEmbedding: (id: string) => void;
  onSetActiveChat: (id: string) => void;
  onTestEmbedding: (config: EmbeddingModelConfig) => void;
  onTestChat: (config: ChatModelConfig) => void;
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

  function clearAll() {
    if (window.confirm("确定清除所有模型配置吗？API Key 也会从当前浏览器本地存储中删除。")) onClearAll();
  }

  return (
    <div className="settings-grid">
      <ActiveModelSummary embeddingConfig={activeEmbeddingConfig} chatConfig={activeChatConfig} />

      <Card
        title="向量模型配置"
        description="优先推荐 Doubao Text Embedding，用于对 JD 和简历文本 chunks 做向量化召回。多模态向量仅作为高级能力预留。"
        action={
          <Button
            type="button"
            variant="primary"
            onClick={() => {
              setEditingEmbedding(undefined);
              setShowEmbeddingForm(true);
            }}
          >
            新增 Doubao 配置
          </Button>
        }
      >
        {showEmbeddingForm && (
          <EmbeddingModelForm
            editingConfig={editingEmbedding}
            onSave={(config) => {
              onSaveEmbedding(config);
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
              onEdit={(item) => {
                setEditingEmbedding(item);
                setShowEmbeddingForm(true);
              }}
              onDelete={onDeleteEmbedding}
              onSetActive={onSetActiveEmbedding}
              onTest={onTestEmbedding}
            />
          ))}
          {!embeddingConfigs.length && <p className="muted-line">还没有向量模型配置。</p>}
        </div>
      </Card>

      <Card
        title="大语言模型配置"
        description="优先支持 Gemini。用户只需要填写 API Key、Model ID 和生成参数，请求细节由系统自动封装。"
        action={
          <Button
            type="button"
            variant="primary"
            onClick={() => {
              setEditingChat(undefined);
              setShowChatForm(true);
            }}
          >
            新增 Gemini 配置
          </Button>
        }
      >
        {showChatForm && (
          <ChatModelForm
            editingConfig={editingChat}
            onSave={(config) => {
              onSaveChat(config);
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
              onEdit={(item) => {
                setEditingChat(item);
                setShowChatForm(true);
              }}
              onDelete={onDeleteChat}
              onSetActive={onSetActiveChat}
              onTest={onTestChat}
            />
          ))}
          {!chatConfigs.length && <p className="muted-line">还没有大语言模型配置。</p>}
        </div>
      </Card>

      <Card title="隐私与安全提示">
        <p className="privacy-note">
          API Key 将保存在当前浏览器本地存储中，仅建议在个人本地环境使用。请不要在公共电脑或不可信环境保存密钥。
          配置不会写入历史分析记录，也不要提交到代码仓库。
        </p>
        <Button type="button" variant="danger" onClick={clearAll}>
          清除所有模型配置
        </Button>
      </Card>
    </div>
  );
}
