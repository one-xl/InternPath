import { useCallback, useEffect, useMemo, useState } from "react";
import type { AnalysisDraft, AnalysisDraftStatus } from "../types/analysisDraft";
import type { AnalysisStep, AnalysisStepId } from "../types/analysis";
import type { UploadedResumeFile, ParsedResume } from "../types/resume";
import {
  fetchDrafts,
  saveDraftToServer,
  deleteDraftFromServer,
  clearConvertedDraftsOnServer,
} from "../services/draftService";
import { safeUUID } from "../utils/uuid";

export function useAnalysisDrafts(enabled = true) {
  const [drafts, setDrafts] = useState<AnalysisDraft[]>([]);

  const reloadDrafts = useCallback(async () => {
    if (!enabled) {
      setDrafts([]);
      return;
    }

    try {
      const data = await fetchDrafts();
      setDrafts(data);
    } catch (err) {
      console.error("[drafts] Failed to load from server:", err);
    }
  }, [enabled]);

  useEffect(() => {
    reloadDrafts();
  }, [reloadDrafts]);

  const latestDraft = useMemo(() => {
    return drafts.find((d) => d.status !== "converted_to_history") || null;
  }, [drafts]);

  const saveDraft = useCallback(
    (input: {
      id?: string;
      companyName?: string;
      jobTitle?: string;
      jdText: string;
      targetType: string;
      jobDirection: string;
      notes?: string;
      resumeFile?: UploadedResumeFile | null;
      parsedResume?: ParsedResume | null;
      embeddingConfigId?: string;
      chatConfigId?: string;
      analysisSettingsId?: string;
    }): AnalysisDraft => {
      const now = new Date().toISOString();
      const existingId = input.id;

      const targetDraft: AnalysisDraft = {
        id: existingId || safeUUID(),
        createdAt: now,
        updatedAt: now,
        status: "draft",
        companyName: input.companyName,
        jobTitle: input.jobTitle,
        jdText: input.jdText,
        targetType: input.targetType,
        jobDirection: input.jobDirection,
        notes: input.notes,
        resumeFile: input.resumeFile || undefined,
        parsedResume: input.parsedResume || undefined,
        embeddingConfigId: input.embeddingConfigId,
        chatConfigId: input.chatConfigId,
        analysisSettingsId: input.analysisSettingsId,
        metadata: {
          jdLength: input.jdText?.length || 0,
          chunksCount: input.parsedResume?.chunks?.length || 0,
          source: "manual_save",
        },
      };

      saveDraftToServer(targetDraft).then(() => reloadDrafts()).catch((err) => {
        console.error("[drafts] Server save failed:", err);
      });
      return targetDraft;
    },
    [reloadDrafts],
  );

  const saveFailedAnalysisDraft = useCallback(
    (input: {
      id?: string;
      companyName?: string;
      jobTitle?: string;
      jdText: string;
      targetType: string;
      jobDirection: string;
      notes?: string;
      resumeFile?: UploadedResumeFile | null;
      parsedResume?: ParsedResume | null;
      embeddingConfigId?: string;
      chatConfigId?: string;
      analysisSettingsId?: string;
      failedStep?: AnalysisStepId;
      errorMessage?: string;
      progressSteps?: AnalysisStep[];
      modelUsageSnapshot?: {
        embeddingProvider?: string;
        embeddingModelId?: string;
        chatProvider?: string;
        chatModelId?: string;
      };
    }): AnalysisDraft => {
      const now = new Date().toISOString();

      const targetDraft: AnalysisDraft = {
        id: input.id || safeUUID(),
        createdAt: now,
        updatedAt: now,
        status: "analysis_failed",
        companyName: input.companyName,
        jobTitle: input.jobTitle,
        jdText: input.jdText,
        targetType: input.targetType,
        jobDirection: input.jobDirection,
        notes: input.notes,
        resumeFile: input.resumeFile || undefined,
        parsedResume: input.parsedResume || undefined,
        embeddingConfigId: input.embeddingConfigId,
        chatConfigId: input.chatConfigId,
        analysisSettingsId: input.analysisSettingsId,
        lastAnalysisAttempt: {
          attemptedAt: now,
          failedAt: now,
          failedStep: input.failedStep,
          errorMessage: input.errorMessage,
          progressSteps: input.progressSteps,
        },
        modelUsageSnapshot: input.modelUsageSnapshot,
        metadata: {
          jdLength: input.jdText?.length || 0,
          chunksCount: input.parsedResume?.chunks?.length || 0,
          source: "failed_analysis",
        },
      };

      saveDraftToServer(targetDraft).then(() => reloadDrafts()).catch((err) => {
        console.error("[drafts] Server save failed:", err);
      });
      return targetDraft;
    },
    [reloadDrafts],
  );

  const deleteDraft = useCallback(
    (id: string) => {
      deleteDraftFromServer(id).then(() => reloadDrafts()).catch((err) => {
        console.error("[drafts] Delete failed:", err);
      });
    },
    [reloadDrafts],
  );

  const updateDraftStatus = useCallback(
    (id: string, status: AnalysisDraftStatus) => {
      const existing = drafts.find((d) => d.id === id);
      if (existing) {
        const updated = { ...existing, status, updatedAt: new Date().toISOString() };
        saveDraftToServer(updated).then(() => reloadDrafts()).catch((err) => {
          console.error("[drafts] Status update failed:", err);
        });
      }
    },
    [drafts, reloadDrafts],
  );

  const clearConverted = useCallback(() => {
    clearConvertedDraftsOnServer().then(() => reloadDrafts()).catch((err) => {
      console.error("[drafts] Clear converted failed:", err);
    });
  }, [reloadDrafts]);

  return {
    drafts,
    latestDraft,
    saveDraft,
    saveFailedAnalysisDraft,
    deleteDraft,
    updateDraftStatus,
    clearConverted,
    reloadDrafts,
  };
}
