import type { AnalysisResult, HistoryRecord } from "../types/analysis";
import { apiFetch } from "./apiClient";

export async function fetchHistory(limit = 30): Promise<HistoryRecord[]> {
  const data = await apiFetch<{ records: any[] }>(`/api/history?limit=${limit}`);
  return (data.records || []).map((r) => {
    let resultObj = r;
    if (r.result_json) {
      if (typeof r.result_json === "string") {
        try {
          resultObj = JSON.parse(r.result_json);
        } catch {
          resultObj = r;
        }
      } else if (typeof r.result_json === "object") {
        resultObj = r.result_json;
      }
    } else if (r.resultJson) {
      if (typeof r.resultJson === "string") {
        try {
          resultObj = JSON.parse(r.resultJson);
        } catch {
          resultObj = r;
        }
      } else if (typeof r.resultJson === "object") {
        resultObj = r.resultJson;
      }
    }

    return {
      ...resultObj,
      id: r.id,
      status: r.status,
      createdAt: r.created_at || r.createdAt || resultObj?.createdAt || r.created_at || new Date().toISOString(),
    };
  });
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
