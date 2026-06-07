import { useCallback, useEffect, useMemo, useState } from "react";
import type { ApplicationStatus, HistoryFilter, HistoryRecord, HistorySort } from "../types/analysis";
import { fetchHistory, saveHistoryRecord, deleteHistoryRecord, updateHistoryRecordStatus } from "../services/historyService";

const priorityRank = { P0: 0, P1: 1, P2: 2, P3: 3 };

export function useHistory(enabled = true) {
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [sort, setSort] = useState<HistorySort>("recent");

  const reload = useCallback(async () => {
    if (!enabled) {
      setRecords([]);
      return;
    }

    try {
      const data = await fetchHistory(100);
      setRecords(data);
    } catch (err) {
      console.error("[history] Failed to load from server:", err);
    }
  }, [enabled]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Auto-polling for active background tasks (polls every 5s if active, stops when done)
  useEffect(() => {
    if (!enabled) return;
    const hasActiveTask = records.some(
      (r) => r.status === "pending" || r.status === "processing"
    );
    if (!hasActiveTask) return;

    const interval = setInterval(() => {
      void reload();
    }, 5000);

    return () => clearInterval(interval);
  }, [records, reload, enabled]);

  async function saveRecord(record: HistoryRecord) {
    try {
      await saveHistoryRecord(record);
      await reload();
    } catch (err: any) {
      console.error("[history] Save failed:", err);
      throw new Error("历史记录保存失败，但你的输入内容已保留。");
    }
  }

  async function updateStatus(id: string, status: ApplicationStatus) {
    try {
      await updateHistoryRecordStatus(id, status);
      setRecords((prev) => prev.map((r) => (r.id === id ? { ...r, status } : r)));
    } catch (err) {
      console.error("[history] Status update failed:", err);
    }
  }

  async function deleteRecord(id: string) {
    try {
      await deleteHistoryRecord(id);
      setRecords((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      console.error("[history] Delete failed:", err);
    }
  }

  const filteredRecords = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const list = records.filter((record) => {
      const haystack = [
        record.draft?.company,
        record.draft?.title,
        record.draft?.jdText,
        record.detectedKeywords?.join(" "),
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
      if (sort === "score") return (b.matchScore ?? 0) - (a.matchScore ?? 0);
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
    reload,
  };
}
