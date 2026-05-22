import type { JobDraft } from "./job";
import type { ModelUsage } from "./modelConfig";
import type { ParsedResume, ResumeChunk, UploadedResumeFile } from "./resume";

export type Decision = "strong_yes" | "yes" | "maybe" | "no";
export type RiskLevel = "low" | "medium" | "high";
export type Priority = "P0" | "P1" | "P2" | "P3";
export type ApplicationStatus = "watching" | "applied" | "rejected" | "interviewing" | "abandoned";

export interface MatchDimension {
  id: string;
  label: string;
  score: number;
  tags: string[];
  explanation: string;
}

export interface ResumeAdvice {
  id: string;
  priority: "high" | "medium" | "low";
  issue: string;
  suggestion: string;
  example: string;
  impact: string;
  basedOnChunkIds?: string[];
  target_requirement_id?: string;
  resume_section?: string;
  risk?: "do_not_exaggerate" | "needs_more_evidence" | "safe_to_rewrite";
}

export interface LearningSuggestion {
  id: string;
  skill: string;
  order: number;
  estimatedTime: string;
  practiceDirection: string;
  interviewFocus: string;
  gap?: string;
  priority?: "high" | "medium" | "low";
  reason?: string;
}

export interface RequirementAssessment {
  requirement_id: string;
  requirement_text: string;
  status: "matched" | "partial" | "missing" | "unknown";
  confidence: "high" | "medium" | "low";
  evidence_used: string[];
  reason: string;
  gap: string;
  fixable_by_resume_rewrite: boolean;
}

export interface AnalysisResult {
  id: string;
  createdAt: string;
  draft: JobDraft;
  sourceDraftId?: string;
  candidateMaterial?: string;
  resumeFile?: UploadedResumeFile;
  parsedResume?: ParsedResume;
  retrievedResumeChunks?: ResumeChunk[];
  retrievalSummary?: string;
  retrievalScore?: number;
  modelUsage?: ModelUsage;
  citedResumeChunks?: string[];
  decision: Decision;
  matchScore: number;
  riskLevel: RiskLevel;
  priority: Priority;
  oneLineReason: string;
  detectedKeywords: string[];
  missingKeywords: string[];
  dimensions: MatchDimension[];
  resumeAdvice: ResumeAdvice[];
  learningSuggestions: LearningSuggestion[];
  nextActions: string[];
  
  // Rearchitected pipeline structural outcomes
  parsedJD?: any; // ParsedJobDescription
  requirementMatches?: any; // RequirementsMatchesResult
  hardConstraintsResult?: any; // HardConstraintsResult
  requirementAssessments?: RequirementAssessment[];
}

export interface HistoryRecord extends AnalysisResult {
  status: ApplicationStatus;
}

export type HistoryFilter = "all" | Decision | ApplicationStatus;
export type HistorySort = "recent" | "score" | "priority";

export type AnalysisRunStatus =
  | "idle"
  | "validating"
  | "embedding_resume"
  | "embedding_jd"
  | "retrieving"
  | "analyzing"
  | "saving"
  | "success"
  | "failed";

export type AnalysisStepId =
  | "validate"
  | "resume_embedding"
  | "jd_embedding"
  | "retrieve_chunks"
  | "gemini_analysis"
  | "save_history"
  | "render_result";

export type AnalysisStepStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "skipped";

export interface AnalysisStep {
  id: AnalysisStepId;
  title: string;
  description: string;
  status: AnalysisStepStatus;
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
  errorMessage?: string;
  metadata?: {
    chunksCount?: number;
    embeddedChunksCount?: number;
    retrievedChunksCount?: number;
    embeddingModelId?: string;
    chatModelId?: string;
    retryCount?: number;
  };
}


