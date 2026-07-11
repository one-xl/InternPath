export type SessionStatus = "ACTIVE" | "WAITING_FOR_USER" | "READY_FOR_CONFIRMATION" | "SATISFIED" | "ARCHIVED" | "FAILED";
export type SuggestionStatus = "proposed" | "accepted" | "needs_revision" | "rejected" | "applied";

export interface ResumeSummary {
  id: string;
  name: string;
  size: number;
  type: string;
  contentHash?: string;
  versionNo?: number;
  isCurrent?: boolean;
}

export interface AdvisorSession {
  id: string;
  resumeId: string;
  jdText: string;
  title: string;
  sessionStatus: SessionStatus;
  activeRunId?: string | null;
  lastMessageAt?: string | null;
  createdAt?: string;
}

export interface AdvisorMessage {
  id: string;
  sequence: number;
  role: "user" | "assistant" | string;
  content: string;
  messageKind: "text" | "question" | "suggestion" | "completion" | "error" | string;
  payload: Record<string, unknown>;
}

export interface AdvisorRun {
  id: string;
  status: string;
  traceId?: string;
  createdAt?: string;
  startedAt?: string;
  finishedAt?: string;
  queueMs?: number | null;
}

export interface AdvisorEvent {
  id: string;
  sequence: number;
  runId?: string | null;
  type: string;
  messageId?: string | null;
  suggestionId?: string | null;
  payload: Record<string, unknown>;
  createdAt?: string;
}

export interface ResumeBlock {
  id: string;
  order: number;
  kind: "heading" | "paragraph" | "bullet" | "table_cell" | "textbox";
  sectionId: string;
  sectionName: string;
  itemLabel?: string;
  text: string;
  textHash: string;
  contextBefore?: string;
  contextAfter?: string;
  sourceBlockId?: string;
  sourceBlockIds?: string[];
  legacyBlockIds?: string[];
  locationLabel: string;
  locatorConfidence: "exact" | "high" | "approximate";
  locator: { sourceFormat: "pdf" | "docx" | "txt"; pageNumber?: number; bbox?: [number, number, number, number]; paragraphIndex?: number; textboxIndex?: number; textboxParagraphIndex?: number; tableIndex?: number; rowIndex?: number; lineStart?: number; lineEnd?: number };
}

export interface ResumePreview {
  sourceFormat: "pdf" | "docx" | "txt";
  hasOriginalFile: boolean;
  inlinePreviewAvailable: boolean;
  locationNotice: string;
}

export interface ResumeSuggestion {
  id: string;
  version: number;
  target: {
    blockId: string;
    sectionId: string;
    sectionName: string;
    itemLabel?: string;
    sourceFormat: "pdf" | "docx" | "txt";
    pageNumber?: number;
    locationLabel: string;
    locatorConfidence: "exact" | "high" | "approximate";
  };
  priority: "high" | "medium" | "low";
  issue: string;
  originalText: string;
  proposedText: string;
  copyText: string;
  rationale: string;
  expectedImpact: string;
  jdRequirementIds: string[];
  resumeEvidenceBlockIds: string[];
  factStatus: "supported" | "needs_user" | "unsupported";
  factIssues: string[];
  status: SuggestionStatus;
}

export interface AdvisorSnapshot {
  session: AdvisorSession;
  run: AdvisorRun | null;
  messages: AdvisorMessage[];
  suggestions: ResumeSuggestion[];
}

export interface AdvisorSloMetric {
  count: number;
  p95Ms: number | null;
  thresholdMs: number;
  met: boolean | null;
}

export interface AdvisorSloDashboard {
  windowHours: number;
  runCount: number;
  metrics: Record<string, AdvisorSloMetric>;
  alerts: Array<{
    code: string;
    severity: string;
    metric?: string;
    observedP95Ms?: number;
    thresholdMs?: number;
  }>;
}
