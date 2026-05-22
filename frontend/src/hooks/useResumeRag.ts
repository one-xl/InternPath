import { useState } from "react";
import { retrieveRelevantResumeChunks } from "../services/resumeService";
import type { ResumeChunk, ResumeRetrievalResult } from "../types/resume";

export function useResumeRag() {
  const [retrieval, setRetrieval] = useState<ResumeRetrievalResult | null>(null);
  const [isRetrieving, setIsRetrieving] = useState(false);
  const [error, setError] = useState("");

  async function retrieve(jdText: string, chunks: ResumeChunk[]) {
    setIsRetrieving(true);
    setError("");
    try {
      const result = await retrieveRelevantResumeChunks(jdText, chunks, { topK: 8 });
      setRetrieval(result);
      return result;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "检索服务失败，请重试";
      setError(message);
      return null;
    } finally {
      setIsRetrieving(false);
    }
  }

  function reset() {
    setRetrieval(null);
    setError("");
    setIsRetrieving(false);
  }

  return {
    retrieval,
    isRetrieving,
    error,
    retrieve,
    reset,
  };
}
