import type { ApplicationStatus, HistoryRecord } from "../../types/analysis";
import { EmptyState } from "../ui/EmptyState";
import { HistoryItemCard } from "./HistoryItemCard";

interface HistoryListProps {
  records: HistoryRecord[];
  onOpen: (record: HistoryRecord) => void;
  onDelete: (id: string) => void;
  onStatusChange: (id: string, status: ApplicationStatus) => void;
  onNewAnalysis: () => void;
}

export function HistoryList({ records, onOpen, onDelete, onStatusChange, onNewAnalysis }: HistoryListProps) {
  if (!records.length) {
    return (
      <EmptyState
        title="暂无匹配的历史记录"
        description="调整搜索和筛选条件，或者创建一次新的岗位分析。"
        actionLabel="新建分析"
        onAction={onNewAnalysis}
      />
    );
  }

  return (
    <div className="history-list">
      {records.map((record) => (
        <HistoryItemCard
          key={record.id}
          record={record}
          onOpen={onOpen}
          onDelete={onDelete}
          onStatusChange={onStatusChange}
        />
      ))}
    </div>
  );
}
