import type { HistoryFilter, HistorySort } from "../../types/analysis";

interface HistoryFilterBarProps {
  query: string;
  filter: HistoryFilter;
  sort: HistorySort;
  onQueryChange: (query: string) => void;
  onFilterChange: (filter: HistoryFilter) => void;
  onSortChange: (sort: HistorySort) => void;
}

const filters: { value: HistoryFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "strong_yes", label: "强烈建议投" },
  { value: "yes", label: "可以投" },
  { value: "maybe", label: "谨慎投" },
  { value: "no", label: "不建议投" },
  { value: "applied", label: "已投递" },
  { value: "rejected", label: "已拒绝" },
  { value: "interviewing", label: "已面试" },
];

export function HistoryFilterBar({
  query,
  filter,
  sort,
  onQueryChange,
  onFilterChange,
  onSortChange,
}: HistoryFilterBarProps) {
  return (
    <div className="history-filter">
      <input
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder="搜索公司、岗位、技能关键词..."
      />
      <select value={filter} onChange={(event) => onFilterChange(event.target.value as HistoryFilter)}>
        {filters.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
      <select value={sort} onChange={(event) => onSortChange(event.target.value as HistorySort)}>
        <option value="recent">最近分析</option>
        <option value="score">匹配度最高</option>
        <option value="priority">优先级最高</option>
      </select>
    </div>
  );
}
