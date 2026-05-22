import type { ResumeChunk, ResumeRetrievalResult } from "../types/resume";

const TECH_KEYWORDS = [
  "React",
  "TypeScript",
  "JavaScript",
  "Node.js",
  "Python",
  "Java",
  "SQL",
  "AWS",
  "Docker",
  "Kubernetes",
  "前端",
  "后端",
  "全栈",
  "实习",
  "校招",
  "算法",
  "系统设计",
  "RAG",
];

function tokenize(text: string): string[] {
  const english = text.toLowerCase().match(/[a-z0-9.+#-]{2,}/g) ?? [];
  const chinese = TECH_KEYWORDS.filter((keyword) => /[\u4e00-\u9fa5]/.test(keyword) && text.includes(keyword));
  return Array.from(new Set([...english, ...chinese.map((item) => item.toLowerCase())]));
}

function scoreChunk(jdText: string, jdTokens: string[], chunk: ResumeChunk): number {
  const chunkText = `${chunk.section ?? ""} ${chunk.content} ${(chunk.keywords ?? []).join(" ")}`.toLowerCase();
  const keywordScore = TECH_KEYWORDS.reduce((score, keyword) => {
    const lower = keyword.toLowerCase();
    return jdText.toLowerCase().includes(lower) && chunkText.includes(lower) ? score + 18 : score;
  }, 0);
  const tokenScore = jdTokens.reduce((score, token) => (chunkText.includes(token) ? score + 4 : score), 0);
  const sectionBonus = chunk.section?.includes("项目") ? 8 : chunk.section?.includes("技能") ? 6 : 0;
  return Math.min(100, keywordScore + tokenScore + sectionBonus);
}

export function mockRetrieveRelevantResumeChunks(
  jdText: string,
  chunks: ResumeChunk[],
  options: { topK?: number } = {},
): ResumeRetrievalResult {
  if (!jdText.trim()) throw new Error("JD 为空，无法检索简历片段");
  if (!chunks.length) throw new Error("简历还没有解析完成，无法检索");

  const jdTokens = tokenize(jdText);
  const topChunks = chunks
    .map((chunk) => ({ ...chunk, score: scoreChunk(jdText, jdTokens, chunk) }))
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    .slice(0, options.topK ?? 8);

  const sections = Array.from(new Set(topChunks.map((chunk) => chunk.section).filter(Boolean)));
  return {
    query: jdText,
    topChunks,
    retrievalSummary: topChunks.length
      ? `已从简历中检索到 ${topChunks.length} 个相关片段，主要来自 ${sections.join("、") || "简历正文"}。`
      : "没有找到足够相关的简历片段，建议补充项目经历或技能证据。",
  };
}
