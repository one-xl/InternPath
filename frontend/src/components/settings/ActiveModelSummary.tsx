import type { ChatModelConfig, EmbeddingModelConfig } from "../../types/modelConfig";
import { isDoubaoMultimodalEmbeddingProvider, isDoubaoTextEmbeddingProvider } from "../../types/modelConfig";
import { formatDateTime } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

export function ActiveModelSummary({
  embeddingConfig,
  chatConfig,
}: {
  embeddingConfig?: EmbeddingModelConfig;
  chatConfig?: ChatModelConfig;
}) {
  const testedAt = [embeddingConfig?.lastTestedAt, chatConfig?.lastTestedAt].filter((value): value is string => Boolean(value)).sort();
  const latestTest = testedAt.length ? testedAt[testedAt.length - 1] : undefined;
  const embeddingReady = embeddingConfig ? (isDoubaoTextEmbeddingProvider(embeddingConfig.provider, embeddingConfig.modelId) || isDoubaoMultimodalEmbeddingProvider(embeddingConfig.provider, embeddingConfig.modelId) || embeddingConfig.provider === "openai-compatible") : false;
  const allTested = embeddingConfig?.testStatus === "success" && chatConfig?.testStatus === "success";

  return (
    <Card title="当前启用模型概览" description="向量模型负责召回相关简历片段，大语言模型负责生成投递建议和简历改造建议。">
      <div className="active-model-grid">
        <div>
          <span>向量模型</span>
          <strong>{embeddingConfig ? `${embeddingConfig.provider} / ${embeddingConfig.modelId}` : "未配置"}</strong>
        </div>
        <div>
          <span>大语言模型</span>
          <strong>{chatConfig ? `${chatConfig.provider} / ${chatConfig.modelId}` : "未配置"}</strong>
        </div>
        <div>
          <span>最近测试状态</span>
          <strong>
            <Badge tone={allTested && embeddingReady ? "success" : "warning"}>
              {embeddingConfig && chatConfig ? (embeddingReady ? "可用于文本 RAG" : "配置未通过测试") : "配置不完整"}
            </Badge>
          </strong>
        </div>
        <div>
          <span>最近测试时间</span>
          <strong>{latestTest ? formatDateTime(latestTest) : "尚未测试"}</strong>
        </div>
      </div>
      {(!embeddingConfig || !chatConfig) && <p className="settings-warning">请先配置向量模型和大语言模型，才能进行真实 RAG 分析。</p>}
    </Card>
  );
}
