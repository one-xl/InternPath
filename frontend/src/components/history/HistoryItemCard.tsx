import type { ApplicationStatus, HistoryRecord } from "../../types/analysis";
import { decisionLabels, formatDateTime, statusLabels } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";

interface HistoryItemCardProps {
  record: HistoryRecord;
  onOpen: (record: HistoryRecord) => void;
  onDelete: (id: string) => void;
  onStatusChange: (id: string, status: ApplicationStatus) => void;
}

export function HistoryItemCard({ record, onOpen, onDelete, onStatusChange }: HistoryItemCardProps) {
  const isBackgroundActive = record.status === "pending" || record.status === "processing";
  const isFailed = record.status === "failed";

  return (
    <article className="history-card">
      <div className="history-main">
        <div>
          <h3>
            {record.draft?.company || "未知公司"} · {record.draft?.title || "未命名岗位"}
          </h3>
          <p>{record.oneLineReason || (isFailed ? `分析失败: ${record.errorMessage || "未知错误"}` : isBackgroundActive ? "正在后台分析简历，请稍候..." : "无摘要说明")}</p>
        </div>
        <strong>{isBackgroundActive ? "..." : isFailed ? "-" : (record.matchScore ?? 0)}</strong>
      </div>
      <div className="badge-row">
        {record.decision ? (
          <Badge tone={record.decision === "no" ? "danger" : record.decision === "maybe" ? "warning" : "success"}>
            {decisionLabels[record.decision]}
          </Badge>
        ) : (
          <Badge tone={isFailed ? "danger" : "neutral"}>
            {isFailed ? "分析失败" : "分析中"}
          </Badge>
        )}
        <Badge tone={isFailed ? "danger" : isBackgroundActive ? "warning" : "neutral"}>
          {statusLabels[record.status]}
        </Badge>
        <Badge tone={record.resumeFile ? "info" : "neutral"}>{record.resumeFile?.name ?? "旧版文本输入记录"}</Badge>
        <span className="history-time">{formatDateTime(record.createdAt)}</span>
      </div>
      <div className="tag-row">
        {(record.detectedKeywords ?? []).slice(0, 6).map((keyword) => (
          <span key={keyword}>{keyword}</span>
        ))}
      </div>
      <div className="history-actions">
        {isBackgroundActive ? (
          <Button variant="secondary" disabled>
            正在分析...
          </Button>
        ) : isFailed ? (
          <Button variant="secondary" disabled>
            分析失败
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => onOpen(record)}>
            查看详情
          </Button>
        )}
        <select
          value={record.status}
          disabled={isBackgroundActive || isFailed}
          onChange={(event) => onStatusChange(record.id, event.target.value as ApplicationStatus)}
        >
          <option value="watching">观察中</option>
          <option value="applied">已投递</option>
          <option value="interviewing">面试中</option>
          <option value="rejected">已拒绝</option>
          <option value="abandoned">已放弃</option>
          {(isBackgroundActive || isFailed) && (
            <option value={record.status}>{statusLabels[record.status]}</option>
          )}
        </select>
        <Button variant="danger" onClick={() => onDelete(record.id)}>
          删除
        </Button>
      </div>
    </article>
  );
}
