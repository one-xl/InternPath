import type { AnalysisDraft, AnalysisDraftStatus } from "../types/analysisDraft";
import { loadFromStorage, saveToStorage } from "./storage";
import { safeUUID } from "./uuid";

const DRAFTS_STORAGE_KEY = "job-desk:analysis-drafts";

/**
 * Get all drafts from localStorage, sorted by updatedAt descending.
 */
export function getAnalysisDrafts(): AnalysisDraft[] {
  const drafts = loadFromStorage<AnalysisDraft[]>(DRAFTS_STORAGE_KEY, []);
  // Ensure sensitive API Keys are never in drafts
  return drafts
    .map((draft) => {
      // Security measure: sanitize anything resembling a key if it leaked in
      if (draft.embeddingConfigId) {
        // Strip API keys if they exist in the draft itself
        const d = { ...draft };
        if ((d as any).embeddingConfig?.apiKey) delete (d as any).embeddingConfig.apiKey;
        if ((d as any).chatConfig?.apiKey) delete (d as any).chatConfig.apiKey;
        return d;
      }
      return draft;
    })
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
}

/**
 * Get a draft by ID.
 */
export function getAnalysisDraftById(id: string): AnalysisDraft | null {
  const drafts = getAnalysisDrafts();
  return drafts.find((d) => d.id === id) || null;
}

/**
 * Save a single draft (inserts or updates). Handles QuotaExceededError.
 */
export function saveAnalysisDraft(draft: AnalysisDraft): void {
  const drafts = getAnalysisDrafts();
  const existingIdx = drafts.findIndex((d) => d.id === draft.id);

  const updatedDraft = {
    ...draft,
    updatedAt: new Date().toISOString(),
  };

  if (existingIdx >= 0) {
    drafts[existingIdx] = updatedDraft;
  } else {
    drafts.push(updatedDraft);
  }

  try {
    saveToStorage(DRAFTS_STORAGE_KEY, drafts);
  } catch (error: any) {
    console.error("[draft-storage] Save failed due to localStorage limits:", error);
    if (
      error.name === "QuotaExceededError" ||
      error.name === "NS_ERROR_DOM_QUOTA_REACHED" ||
      error.message?.includes("quota") ||
      error.message?.includes("limit")
    ) {
      throw new Error("草稿保存失败，浏览器本地存储空间不足。可尝试移除大文件解析结果后再保存。");
    }
    throw new Error("草稿保存失败，请稍后重试。");
  }
}

/**
 * Create a new draft.
 */
export function createAnalysisDraft(input: Omit<AnalysisDraft, "id" | "createdAt" | "updatedAt" | "status">): AnalysisDraft {
  const now = new Date().toISOString();
  const draft: AnalysisDraft = {
    ...input,
    id: safeUUID(),
    createdAt: now,
    updatedAt: now,
    status: "draft",
  };

  saveAnalysisDraft(draft);
  return draft;
}

/**
 * Patch an existing draft.
 */
export function updateAnalysisDraft(id: string, patch: Partial<Omit<AnalysisDraft, "id" | "createdAt">>): AnalysisDraft {
  const existing = getAnalysisDraftById(id);
  if (!existing) {
    throw new Error(`Draft with ID ${id} not found.`);
  }

  const updated: AnalysisDraft = {
    ...existing,
    ...patch,
    updatedAt: new Date().toISOString(),
  };

  saveAnalysisDraft(updated);
  return updated;
}

/**
 * Delete a draft.
 */
export function deleteAnalysisDraft(id: string): void {
  const drafts = getAnalysisDrafts();
  const filtered = drafts.filter((d) => d.id !== id);
  try {
    saveToStorage(DRAFTS_STORAGE_KEY, filtered);
  } catch (error) {
    console.error("[draft-storage] Delete failed:", error);
    throw new Error("删除草稿失败，请稍后重试。");
  }
}

/**
 * Mark a draft as successfully converted to a history record.
 */
export function markDraftConvertedToHistory(id: string, historyId?: string): void {
  try {
    updateAnalysisDraft(id, {
      status: "converted_to_history",
      metadata: {
        source: "manual_save",
        ...(getAnalysisDraftById(id)?.metadata || {}),
      },
    });
  } catch (error) {
    console.error(`[draft-storage] Failed to mark draft ${id} as converted:`, error);
  }
}

/**
 * Clear all drafts marked as converted to history records.
 */
export function clearConvertedDrafts(): void {
  const drafts = getAnalysisDrafts();
  const activeDrafts = drafts.filter((d) => d.status !== "converted_to_history");
  saveToStorage(DRAFTS_STORAGE_KEY, activeDrafts);
}

/**
 * Get the latest active draft that can be restored (excluding converted ones).
 */
export function getLatestDraft(): AnalysisDraft | null {
  const drafts = getAnalysisDrafts();
  const activeDrafts = drafts.filter((d) => d.status !== "converted_to_history");
  return activeDrafts.length > 0 ? activeDrafts[0] : null;
}
