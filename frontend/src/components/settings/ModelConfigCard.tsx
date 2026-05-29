import { memo } from "react";
import type { ChatModelConfig, EmbeddingModelConfig } from "../../types/modelConfig";
import { formatDateTime } from "../../utils/format";
import { maskApiKey } from "../../utils/modelConfigStorage";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { ModelTestButton } from "./ModelTestButton";

type AnyModelConfig = EmbeddingModelConfig | ChatModelConfig;

interface ModelConfigCardProps {
  config: AnyModelConfig;
  active: boolean;
  onEdit: (config: AnyModelConfig) => void;
  onDelete: (id: string) => void;
  onSetActive: (id: string) => void;
  onTest: (config: AnyModelConfig) => void;
}

export const ModelConfigCard = memo(function ModelConfigCardInner({
  config,
  active,
  onEdit,
  onDelete,
  onSetActive,
  onTest,
}: ModelConfigCardProps) {
  function confirmDelete() {
    if (window.confirm(`确定删除配置「${config.name}」吗？`)) onDelete(config.id);
  }

  return (
    <article className="model-card">
      <div className="model-card-main">
        <div>
          <h3>{config.name}</h3>
          <p>
            {config.provider} · {config.modelId}
          </p>
          <div className="badge-row">
            {active && <Badge tone="success">默认</Badge>}
            <Badge tone={config.testStatus === "success" ? "success" : config.testStatus === "failed" ? "danger" : "neutral"}>
              {config.testStatus === "success" ? "测试成功" : config.testStatus === "failed" ? "测试失败" : "未测试"}
            </Badge>
            <Badge tone="info">{maskApiKey(config.apiKey)}</Badge>
          </div>
          {config.lastTestedAt && <small>最近测试：{formatDateTime(config.lastTestedAt)}</small>}
        </div>
        <div className="model-card-actions">
          <Button type="button" variant="secondary" onClick={() => onSetActive(config.id)} disabled={active}>
            设为默认
          </Button>
          <Button type="button" variant="ghost" onClick={() => onEdit(config)}>
            编辑
          </Button>
          <Button type="button" variant="danger" onClick={confirmDelete}>
            删除
          </Button>
        </div>
      </div>
      <ModelTestButton status={config.testStatus} message={config.testMessage} diagnostics={config.testDiagnostics} onTest={() => onTest(config)} />
    </article>
  );
});
