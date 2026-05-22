import { useMemo, useState } from "react";
import type { ApplicationStatus, HistoryFilter, HistoryRecord, HistorySort } from "../types/analysis";
import { loadFromStorage, saveToStorage } from "../utils/storage";

const HISTORY_KEY = "internpath.history.v2";

const priorityRank = { P0: 0, P1: 1, P2: 2, P3: 3 };

export function useHistory() {
  const [records, setRecords] = useState<HistoryRecord[]>(() => loadFromStorage(HISTORY_KEY, []));
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [sort, setSort] = useState<HistorySort>("recent");

  function commit(nextRecords: HistoryRecord[]) {
    setRecords(nextRecords);
    saveToStorage(HISTORY_KEY, nextRecords);
  }

  function saveRecord(record: HistoryRecord) {
    commit([record, ...records.filter((item) => item.id !== record.id)]);
  }

  function updateStatus(id: string, status: ApplicationStatus) {
    commit(records.map((record) => (record.id === id ? { ...record, status } : record)));
  }

  function deleteRecord(id: string) {
    commit(records.filter((record) => record.id !== id));
  }

  const filteredRecords = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const list = records.filter((record) => {
      const haystack = [
        record.draft.company,
        record.draft.title,
        record.draft.jdText,
        record.detectedKeywords.join(" "),
        record.oneLineReason,
        record.resumeFile?.name ?? "",
        record.retrievedResumeChunks?.map((chunk) => `${chunk.section ?? ""} ${chunk.content}`).join(" ") ?? "",
      ]
        .join(" ")
        .toLowerCase();
      const queryMatched = normalizedQuery ? haystack.includes(normalizedQuery) : true;
      const filterMatched =
        filter === "all" || record.decision === filter || record.status === filter;
      return queryMatched && filterMatched;
    });

    return [...list].sort((a, b) => {
      if (sort === "score") return b.matchScore - a.matchScore;
      if (sort === "priority") return priorityRank[a.priority] - priorityRank[b.priority];
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });
  }, [filter, query, records, sort]);

  return {
    records,
    filteredRecords,
    query,
    filter,
    sort,
    setQuery,
    setFilter,
    setSort,
    saveRecord,
    updateStatus,
    deleteRecord,
  };
}
