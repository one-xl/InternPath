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
  return (
    <article className="history-card">
      <div className="history-main">
        <div>
          <h3>
            {record.draft.company || "未知公司"} · {record.draft.title || "未命名岗位"}
          </h3>
          <p>{record.oneLineReason}</p>
        </div>
        <strong>{record.matchScore}</strong>
      </div>
      <div className="badge-row">
        <Badge tone={record.decision === "no" ? "danger" : record.decision === "maybe" ? "warning" : "success"}>
          {decisionLabels[record.decision]}
        </Badge>
        <Badge tone="neutral">{statusLabels[record.status]}</Badge>
        <Badge tone={record.resumeFile ? "info" : "neutral"}>{record.resumeFile?.name ?? "旧版文本输入记录"}</Badge>
        <span className="history-time">{formatDateTime(record.createdAt)}</span>
      </div>
      <div className="tag-row">
        {record.detectedKeywords.slice(0, 6).map((keyword) => (
          <span key={keyword}>{keyword}</span>
        ))}
      </div>
      <div className="history-actions">
        <Button variant="secondary" onClick={() => onOpen(record)}>
          查看详情
        </Button>
        <select value={record.status} onChange={(event) => onStatusChange(record.id, event.target.value as ApplicationStatus)}>
          <option value="watching">观察中</option>
          <option value="applied">已投递</option>
          <option value="interviewing">面试中</option>
          <option value="rejected">已拒绝</option>
          <option value="abandoned">已放弃</option>
        </select>
        <Button variant="danger" onClick={() => onDelete(record.id)}>
          删除
        </Button>
      </div>
    </article>
  );
}
