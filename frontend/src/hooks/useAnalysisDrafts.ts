import { useCallback, useMemo, useState } from "react";
import type { AnalysisDraft, AnalysisDraftStatus } from "../types/analysisDraft";
import type { AnalysisStep, AnalysisStepId } from "../types/analysis";
import type { UploadedResumeFile, ParsedResume } from "../types/resume";
import {
  getAnalysisDrafts,
  saveAnalysisDraft,
  createAnalysisDraft,
  updateAnalysisDraft,
  deleteAnalysisDraft,
  clearConvertedDrafts,
  getLatestDraft,
} from "../utils/analysisDraftStorage";

export function useAnalysisDrafts() {
  const [drafts, setDrafts] = useState<AnalysisDraft[]>(() => getAnalysisDrafts());

  const reloadDrafts = useCallback(() => {
    setDrafts(getAnalysisDrafts());
  }, []);

  const latestDraft = useMemo(() => {
    return drafts.find((d) => d.status !== "converted_to_history") || null;
  }, [drafts]);

  /**
   * Save current input values manually as a draft.
   */
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
      const draftsList = getAnalysisDrafts();
      const existingId = input.id;
      
      const now = new Date().toISOString();

      let targetDraft: AnalysisDraft;

      if (existingId && draftsList.some((d) => d.id === existingId)) {
        // Update existing
        targetDraft = {
          id: existingId,
          createdAt: draftsList.find((d) => d.id === existingId)!.createdAt,
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
      } else {
        // Create new
        targetDraft = {
          id: existingId || crypto.randomUUID(),
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
      }

      saveAnalysisDraft(targetDraft);
      reloadDrafts();
      return targetDraft;
    },
    [reloadDrafts],
  );

  /**
   * Automatically save a failed analysis as a draft.
   */
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
        id: input.id || crypto.randomUUID(),
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

      saveAnalysisDraft(targetDraft);
      reloadDrafts();
      return targetDraft;
    },
    [reloadDrafts],
  );

  /**
   * Delete a draft by ID.
   */
  const deleteDraft = useCallback(
    (id: string) => {
      deleteAnalysisDraft(id);
      reloadDrafts();
    },
    [reloadDrafts],
  );

  /**
   * Update a draft's status or fields.
   */
  const updateDraftStatus = useCallback(
    (id: string, status: AnalysisDraftStatus) => {
      updateAnalysisDraft(id, { status });
      reloadDrafts();
    },
    [reloadDrafts],
  );

  /**
   * Clear all converted drafts.
   */
  const clearConverted = useCallback(() => {
    clearConvertedDrafts();
    reloadDrafts();
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
