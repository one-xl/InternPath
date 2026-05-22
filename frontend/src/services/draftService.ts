import type { AnalysisDraft } from "../types/analysisDraft";
import { apiFetch } from "./apiClient";

export async function fetchDrafts(): Promise<AnalysisDraft[]> {
  const data = await apiFetch<{ drafts: any[] }>("/api/drafts");
  return (data.drafts || []).map(mapServerDraft);
}

export async function saveDraftToServer(draft: AnalysisDraft): Promise<{ id: string }> {
  return apiFetch<{ id: string }>("/api/drafts", {
    method: "POST",
    body: JSON.stringify({
      id: draft.id,
      status: draft.status,
      input_json: draft,
      failed_step: draft.lastAnalysisAttempt?.failedStep,
      error_message: draft.lastAnalysisAttempt?.errorMessage,
    }),
  });
}

export async function deleteDraftFromServer(id: string): Promise<void> {
  await apiFetch(`/api/drafts/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function clearConvertedDraftsOnServer(): Promise<void> {
  await apiFetch("/api/drafts/clear-converted", { method: "POST" });
}

function mapServerDraft(raw: any): AnalysisDraft {
  const input = raw.input_json || {};
  return {
    id: raw.id,
    createdAt: raw.created_at || input.createdAt || new Date().toISOString(),
    updatedAt: raw.updated_at || input.updatedAt || new Date().toISOString(),
    status: raw.status || "draft",
    companyName: input.companyName,
    jobTitle: input.jobTitle,
    jdText: input.jdText || "",
    targetType: input.targetType || "",
    jobDirection: input.jobDirection || "",
    notes: input.notes,
    resumeFile: input.resumeFile,
    parsedResume: input.parsedResume,
    embeddingConfigId: input.embeddingConfigId,
    chatConfigId: input.chatConfigId,
    analysisSettingsId: input.analysisSettingsId,
    lastAnalysisAttempt: input.lastAnalysisAttempt,
    modelUsageSnapshot: input.modelUsageSnapshot,
    metadata: input.metadata,
  };
}
