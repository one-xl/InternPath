export type ResumeFileStatus =
  | "idle"
  | "selected"
  | "uploading"
  | "uploaded"
  | "parsing"
  | "parsed"
  | "indexing"
  | "indexed"
  | "failed";

export interface UploadedResumeFile {
  id: string;
  name: string;
  size: number;
  type: string;
  uploadedAt: string;
  status: ResumeFileStatus;
  errorMessage?: string;
}

export interface ResumeChunk {
  id: string;
  resumeFileId: string;
  index: number;
  content: string;
  section?: string;
  keywords?: string[];
  score?: number;
  embedding?: number[];
  sectionId?: string;
  sectionType?: string;
  sectionTitle?: string;
  hierarchy?: string[];
  semanticType?: string;
  importance?: number;
  retrievalReasons?: string[];
  embeddingText?: string;
  metadata?: {
    pageNumber?: number;
    heading?: string;
    source?: string;
    sectionType?: string;
    sectionTitle?: string;
    hierarchy?: string[];
    semanticType?: string;
    importance?: number;
  };
}

export interface ParsedResume {
  file: UploadedResumeFile;
  rawText: string;
  cleanedText: string;
  chunks: ResumeChunk[];
  extractedProfile?: {
    name?: string;
    email?: string;
    phone?: string;
    education?: string[];
    skills?: string[];
    projects?: string[];
    experiences?: string[];
  };
}

export interface ResumeRetrievalResult {
  query: string;
  topChunks: ResumeChunk[];
  retrievalSummary: string;
}
