import { ModelSettingsPanel } from "../components/settings/ModelSettingsPanel";
import type { ChatModelConfig, EmbeddingModelConfig, ModelConfigState } from "../types/modelConfig";

interface SettingsPageProps {
  state: ModelConfigState;
  activeEmbeddingConfig?: EmbeddingModelConfig;
  activeChatConfig?: ChatModelConfig;
  onSaveEmbedding: (config: EmbeddingModelConfig) => void;
  onSaveChat: (config: ChatModelConfig) => void;
  onDeleteEmbedding: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onSetActiveEmbedding: (id: string) => void;
  onSetActiveChat: (id: string) => void;
  onTestEmbedding: (config: EmbeddingModelConfig) => void | Promise<any>;
  onTestChat: (config: ChatModelConfig) => void | Promise<any>;
  onClearAll: () => void;
}

export function SettingsPage({
  state,
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
}: SettingsPageProps) {
  return (
    <div className="page-stack">
      <div className="page-title">
        <span className="section-kicker">模型配置</span>
        <h2>配置简历检索和岗位分析模型</h2>
        <p>
          向量模型负责召回相关简历片段，大语言模型负责生成匹配度、投递建议和简历改造建议。
          当前简历文本 RAG 默认推荐 Doubao Text Embedding。
        </p>
      </div>
      <ModelSettingsPanel
        embeddingConfigs={state.embeddingConfigs}
        chatConfigs={state.chatConfigs}
        activeEmbeddingConfig={activeEmbeddingConfig}
        activeChatConfig={activeChatConfig}
        onSaveEmbedding={onSaveEmbedding}
        onSaveChat={onSaveChat}
        onDeleteEmbedding={onDeleteEmbedding}
        onDeleteChat={onDeleteChat}
        onSetActiveEmbedding={onSetActiveEmbedding}
        onSetActiveChat={onSetActiveChat}
        onTestEmbedding={onTestEmbedding}
        onTestChat={onTestChat}
        onClearAll={onClearAll}
      />
    </div>
  );
}
