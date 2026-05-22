import type { ParsedJobDescription, ParsedJobRequirement } from "./jobParser";
import type { ResumeChunk } from "../types/resume";
import type { EmbeddingModelConfig } from "../types/modelConfig";
import { embedTextWithConfig, cosineSimilarity } from "./embeddingClient";

export interface MatchedEvidence {
  evidence_id: string;
  evidence_text: string;
  evidence_type: string;
  similarity: number; // 0.0 to 1.0
  source_section: string;
}

export interface RequirementMatch {
  requirement_id: string;
  requirement_text: string;
  priority: "must_have" | "nice_to_have" | "unknown";
  is_hard_requirement: boolean;
  matched_evidence: MatchedEvidence[];
  best_similarity: number; // 0.0 to 1.0
  has_potential_evidence: boolean;
}

export interface RequirementsMatchesResult {
  requirement_matches: RequirementMatch[];
}

export async function retrieveEvidenceForRequirements(
  parsedJD: ParsedJobDescription,
  embeddedChunks: ResumeChunk[],
  embeddingConfig: EmbeddingModelConfig,
  options: { topK?: number; threshold?: number } = {}
): Promise<RequirementsMatchesResult> {
  const topK = options.topK ?? 3;
  const threshold = options.threshold ?? 0.35; // Similarity threshold (0.0 to 1.0)
  const requirementMatches: RequirementMatch[] = [];

  for (const req of parsedJD.requirements) {
    // 1. Vectorize requirement text
    let reqEmbedding: number[];
    try {
      reqEmbedding = await embedTextWithConfig(req.text, embeddingConfig);
    } catch (error) {
      console.error(`[evidenceRetriever] Failed to embed requirement ${req.id}:`, error);
      reqEmbedding = [];
    }

    const matchedEvidenceList: MatchedEvidence[] = [];

    if (reqEmbedding.length > 0) {
      // 2. Score similarity against all embedded resume chunks
      const scoredChunks = embeddedChunks.map((chunk) => {
        const sim = cosineSimilarity(reqEmbedding, chunk.embedding ?? []);
        return {
          chunk,
          similarity: sim
        };
      });

      // Sort by similarity descending
      scoredChunks.sort((a, b) => b.similarity - a.similarity);

      // Take top K chunks
      const topScored = scoredChunks.slice(0, topK);

      for (const item of topScored) {
        matchedEvidenceList.push({
          evidence_id: item.chunk.id,
          evidence_text: item.chunk.content,
          evidence_type: item.chunk.section || "other",
          similarity: Number(item.similarity.toFixed(4)),
          source_section: item.chunk.section || "other"
        });
      }
    }

    // 3. Find the best similarity score
    const bestSimilarity = matchedEvidenceList.length > 0
      ? Math.max(...matchedEvidenceList.map((e) => e.similarity))
      : 0.0;

    const hasPotentialEvidence = bestSimilarity >= threshold;

    requirementMatches.push({
      requirement_id: req.id,
      requirement_text: req.text,
      priority: req.priority,
      is_hard_requirement: req.is_hard_requirement,
      matched_evidence: matchedEvidenceList,
      best_similarity: bestSimilarity,
      has_potential_evidence: hasPotentialEvidence
    });
  }

  return {
    requirement_matches: requirementMatches
  };
}
