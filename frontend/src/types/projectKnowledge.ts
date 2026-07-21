export interface ProjectKnowledgeDocument {
  id: number;
  title: string;
  file_name?: string;
  file_type?: string;
  source_type: string;
  status?: string;
  chunk_count?: number;
  error_message?: string;
  created_at?: string;
}

export type ProjectKnowledgeScope = "all" | "selected" | "none";

export interface ProjectRecommendation {
  documentId: string;
  chunkIds: string[];
  evidence: string[];
  summary: string;
  matchReason: string;
  resumeSuggestion: string;
  score: number;
}

export interface ProjectRerankResult {
  recommendations: ProjectRecommendation[];
  rerankMode: "llm" | "fallback";
  fallbackReason: string | null;
}
