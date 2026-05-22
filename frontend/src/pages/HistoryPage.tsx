import { useState } from "react";
import type { ApplicationStatus, HistoryFilter, HistoryRecord, HistorySort } from "../types/analysis";
import type { AnalysisDraft } from "../types/analysisDraft";
import { HistoryFilterBar } from "../components/history/HistoryFilterBar";
import { HistoryList } from "../components/history/HistoryList";
import { DraftsTab } from "../components/history/DraftsTab";
import { Card } from "../components/ui/Card";

interface HistoryPageProps {
  records: HistoryRecord[];
  query: string;
  filter: HistoryFilter;
  sort: HistorySort;
  onQueryChange: (query: string) => void;
  onFilterChange: (filter: HistoryFilter) => void;
  onSortChange: (sort: HistorySort) => void;
  onOpen: (record: HistoryRecord) => void;
  onDelete: (id: string) => void;
  onStatusChange: (id: string, status: ApplicationStatus) => void;
  onNewAnalysis: () => void;

  // Draft related props
  drafts: AnalysisDraft[];
  onRestoreDraft: (draft: AnalysisDraft) => void;
  onCloneDraft: (draft: AnalysisDraft) => void;
  onDeleteDraft: (id: string) => void;
}

export function HistoryPage({
  records,
  query,
  filter,
  sort,
  onQueryChange,
  onFilterChange,
  onSortChange,
  onOpen,
  onDelete,
  onStatusChange,
  onNewAnalysis,
  
  drafts,
  onRestoreDraft,
  onCloneDraft,
  onDeleteDraft,
}: HistoryPageProps) {
  const [activeTab, setActiveTab] = useState<"records" | "drafts">("records");
  
  const activeDraftsCount = drafts.filter((d) => d.status !== "converted_to_history").length;

  return (
    <div className="page-stack">
      <div className="page-title">
        <span className="section-kicker">分析与记录</span>
        <h2>复盘岗位，而不是只堆投递数量。</h2>
        <p>按公司、岗位、技能搜索完成的分析结果，或继续跟进未完成的草稿。</p>
      </div>

      <div className="history-tabs-header">
        <button
          type="button"
          className={`history-tab-btn ${activeTab === "records" ? "active" : ""}`}
          onClick={() => setActiveTab("records")}
        >
          已完成分析 ({records.length})
        </button>
        <button
          type="button"
          className={`history-tab-btn ${activeTab === "drafts" ? "active" : ""}`}
          onClick={() => setActiveTab("drafts")}
        >
          未完成草稿 ({activeDraftsCount})
        </button>
      </div>

      {activeTab === "records" ? (
        <>
          <Card>
            <HistoryFilterBar
              query={query}
              filter={filter}
              sort={sort}
              onQueryChange={onQueryChange}
              onFilterChange={onFilterChange}
              onSortChange={onSortChange}
            />
          </Card>
          <HistoryList
            records={records}
            onOpen={onOpen}
            onDelete={onDelete}
            onStatusChange={onStatusChange}
            onNewAnalysis={onNewAnalysis}
          />
        </>
      ) : (
        <DraftsTab
          drafts={drafts}
          onRestore={onRestoreDraft}
          onClone={onCloneDraft}
          onDelete={onDeleteDraft}
          onNewAnalysis={onNewAnalysis}
        />
      )}
    </div>
  );
}
