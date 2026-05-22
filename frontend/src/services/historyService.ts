import type { AnalysisResult, HistoryRecord } from "../types/analysis";
import { apiFetch } from "./apiClient";

export async function fetchHistory(limit = 30): Promise<HistoryRecord[]> {
  const data = await apiFetch<{ records: HistoryRecord[] }>(`/api/history?limit=${limit}`);
  return data.records || [];
}

export async function saveHistoryRecord(record: AnalysisResult & { status?: string }): Promise<{ id: string }> {
  return apiFetch<{ id: string }>("/api/history", {
    method: "POST",
    body: JSON.stringify({ result: record, status: record.status || "watching" }),
  });
}

export async function deleteHistoryRecord(id: string): Promise<boolean> {
  const data = await apiFetch<{ deleted: boolean }>(`/api/history/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  return data.deleted;
}

export async function updateHistoryRecordStatus(id: string, status: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/history/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}
