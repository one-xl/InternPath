import type { ResumeChunk } from "../types/resume";

/**
 * 校验并清洗大语言模型返回的简历片段引用 (citedResumeChunks 与 resumeAdvice 的 basedOnChunkIds)。
 * 确保所有引用的 ID 都在本次召回的 retrievedChunks 中真实存在。
 *
 * 如果某条建议 (assessment/advice) 原本声明了引用，但过滤后没有任何有效引用：
 * - 其 basedOnChunkIds 会被置空
 * - 它的优先级降级为 "low"
 * - 其 issue / suggestion 追加中文说明 "模型返回的证据引用无效或缺少有效证据" 并归入 "evidence_insufficient" 标记。
 */
export function validateModelCitations(
  result: any,
  retrievedChunks: ResumeChunk[]
): any {
  if (!result) return result;

  const validChunkIds = new Set((retrievedChunks || []).map((chunk) => chunk.id));

  // 1. 过滤并校验 citedResumeChunks
  if (Array.isArray(result.citedResumeChunks)) {
    result.citedResumeChunks = result.citedResumeChunks.filter((id: string) =>
      validChunkIds.has(id)
    );
  } else {
    result.citedResumeChunks = [];
  }

  // 2. 过滤并校验 resumeAdvice 里的 basedOnChunkIds
  if (Array.isArray(result.resumeAdvice)) {
    result.resumeAdvice = result.resumeAdvice.map((advice: any) => {
      const originalChunks = advice.basedOnChunkIds ?? [];
      const filteredChunks = originalChunks.filter((id: string) =>
        validChunkIds.has(id)
      );

      // 如果模型本来返回了引用，但全部是虚假 ID（过滤后变为空数组）：
      if (originalChunks.length > 0 && filteredChunks.length === 0) {
        return {
          ...advice,
          basedOnChunkIds: [],
          priority: "low",
          issue: `[evidence_insufficient] ${advice.issue} (模型返回的证据引用无效或缺少有效证据)`,
          suggestion: `模型返回的证据引用无效或缺少有效证据，原建议暂无法关联有效简历片段。原建议：${advice.suggestion}`,
        };
      }

      return {
        ...advice,
        basedOnChunkIds: filteredChunks,
      };
    });
  }

  return result;
}
