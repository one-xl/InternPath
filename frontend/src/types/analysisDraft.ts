import type { UploadedResumeFile, ParsedResume } from "./resume";
import type { AnalysisRunStatus, AnalysisStep, AnalysisStepId } from "./analysis";
import type { WorkMode, JobLevel } from "./job";

export type AnalysisDraftStatus =
  | "draft"
  | "analysis_failed"
  | "ready_to_analyze"
  | "converted_to_history";

export interface AnalysisDraft {
  id: string;
  createdAt: string;
  updatedAt: string;
  status: AnalysisDraftStatus;

  // Form Fields
  companyName?: string;
  jobTitle?: string;
  jdText: string;
  targetType: string;
  jobDirection: string;
  notes?: string;
  link?: string;
  location?: string;
  workMode?: WorkMode;
  level?: JobLevel;

  // Uploaded resume data
  resumeFile?: UploadedResumeFile;
  parsedResume?: ParsedResume;

  // Selected config references
  embeddingConfigId?: string;
  chatConfigId?: string;
  analysisSettingsId?: string;

  // Saved error contexts from failed attempts
  lastAnalysisAttempt?: {
    attemptedAt: string;
    failedAt?: string;
    failedStep?: AnalysisStepId;
    errorMessage?: string;
    analysisStatus?: AnalysisRunStatus;
    progressSteps?: AnalysisStep[];
  };

  // Safe snapshots for display (excluding sensitive API Keys)
  modelUsageSnapshot?: {
    embeddingProvider?: string;
    embeddingModelId?: string;
    chatProvider?: string;
    chatModelId?: string;
  };

  metadata?: {
    jdLength?: number;
    chunksCount?: number;
    source?: "manual_save" | "auto_save" | "failed_analysis";
  };
}
