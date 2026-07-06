export interface AgentModificationItem {
  section_name: string;
  section_index: number;
  original: string;
  new: string;
  reason: string;
}

export interface FactLedgerItem {
  sectionName: string;
  sectionIndex: number;
  status: "verified" | "review";
  source: "resume" | "jd_or_memory" | "needs_confirmation";
  addedFacts: string[];
  summary: string;
  reason: string;
}

export interface JdRadarItem {
  keyword: string;
  matched: boolean;
}

export interface JdRadar {
  score: number;
  matched: JdRadarItem[];
  missing: JdRadarItem[];
}

export interface ResumeVariant {
  name: string;
  focus: string;
  preview: string;
}

export interface InterviewQuestion {
  sectionName: string;
  question: string;
}

export interface ApplicationSnippet {
  label: string;
  text: string;
}

export interface OfferDecision {
  score: number;
  verdict: string;
  risks: string[];
}

export interface ActionPackCacheSummary {
  hitRate: number;
  hits: number;
  misses: number;
  savedModelCalls: number;
}

export interface ActionPackReview {
  status: string;
  note?: string;
}

export interface ActionPackInput {
  taskId?: string;
  resumeName?: string;
  updatedAt?: string;
  jdText: string;
  optimizedResumeMd: string;
  factLedger: FactLedgerItem[];
  jdRadar: JdRadar;
  resumeVariants: ResumeVariant[];
  interviewQuestions: InterviewQuestion[];
  applicationSnippets: ApplicationSnippet[];
  review?: ActionPackReview;
  offerDecision: OfferDecision;
  cacheSummary?: ActionPackCacheSummary;
}

const HARD_FACT_PATTERN = /(\d+(?:\.\d+)?\s*(?:%|％|万|k|K|ms|s|秒|天|周|月|年|人|次|倍|MB|GB|QPS|TPS)|20\d{2}[./-]?\d{0,2}|(?:一|二|三|四|五|六|七|八|九|十)[年月]|[A-Z][A-Za-z0-9+.#-]{1,}(?:\s+[A-Z][A-Za-z0-9+.#-]{1,})?)/g;

const STOP_WORDS = new Set([
  "and",
  "the",
  "with",
  "for",
  "that",
  "this",
  "岗位",
  "职责",
  "要求",
  "负责",
  "相关",
  "能力",
  "优先",
  "熟悉",
  "具备",
  "良好",
  "以上",
  "以及",
  "进行",
  "工作",
]);

const TECH_KEYWORDS = [
  "JavaScript",
  "TypeScript",
  "React",
  "Vue",
  "Node",
  "Python",
  "FastAPI",
  "Django",
  "Flask",
  "Java",
  "Spring",
  "Go",
  "Redis",
  "MySQL",
  "PostgreSQL",
  "SQLite",
  "Docker",
  "Kubernetes",
  "Linux",
  "RAG",
  "LLM",
  "Agent",
  "AI",
  "SQL",
  "REST",
  "GraphQL",
  "CI/CD",
];

const FACT_STATUS_TEXT: Record<FactLedgerItem["status"], string> = {
  verified: "已验证",
  review: "需确认",
};

const FACT_SOURCE_TEXT: Record<FactLedgerItem["source"], string> = {
  resume: "原简历",
  jd_or_memory: "JD/记忆",
  needs_confirmation: "人工确认",
};

function normalizeText(value: string): string {
  return (value || "").toLowerCase().replace(/\s+/g, " ").trim();
}

function unique(items: string[]): string[] {
  return Array.from(new Set(items.map((item) => item.trim()).filter(Boolean)));
}

function splitSentences(value: string): string[] {
  return (value || "")
    .split(/[\n。！？!?；;]/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function extractHardFacts(value: string): string[] {
  return unique(Array.from(value.matchAll(HARD_FACT_PATTERN)).map((match) => match[0]));
}

export function buildFactLedger(
  modificationLog: AgentModificationItem[],
  jdText: string,
): FactLedgerItem[] {
  const normalizedJd = normalizeText(jdText);
  return (modificationLog || []).map((item) => {
    const original = normalizeText(item.original || "");
    const addedFacts = extractHardFacts(item.new || "").filter((fact) => {
      const normalizedFact = normalizeText(fact);
      return normalizedFact && !original.includes(normalizedFact);
    });
    const supportedFacts = addedFacts.filter((fact) => normalizedJd.includes(normalizeText(fact)));
    const status = addedFacts.length === 0 || supportedFacts.length === addedFacts.length ? "verified" : "review";
    const source = addedFacts.length === 0
      ? "resume"
      : supportedFacts.length === addedFacts.length
        ? "jd_or_memory"
        : "needs_confirmation";
    return {
      sectionName: item.section_name,
      sectionIndex: item.section_index,
      status,
      source,
      addedFacts,
      summary: item.new ? splitSentences(item.new)[0] || item.new.slice(0, 90) : "本段仅做结构或表达优化",
      reason: item.reason || "针对 JD 进行表达优化",
    };
  });
}

export function extractJdKeywords(jdText: string): string[] {
  const techHits = TECH_KEYWORDS.filter((keyword) => normalizeText(jdText).includes(normalizeText(keyword)));
  const words = unique(
    Array.from(jdText.matchAll(/[A-Za-z][A-Za-z0-9+.#/-]{2,}|[\u4e00-\u9fff]{2,6}/g))
      .map((match) => match[0])
      .filter((word) => !STOP_WORDS.has(word.toLowerCase()))
      .slice(0, 36),
  );
  return unique([...techHits, ...words]).slice(0, 24);
}

export function buildJdRadar(jdText: string, resumeText: string): JdRadar {
  const keywords = extractJdKeywords(jdText);
  const normalizedResume = normalizeText(resumeText);
  const items = keywords.map((keyword) => ({
    keyword,
    matched: normalizedResume.includes(normalizeText(keyword)),
  }));
  const matched = items.filter((item) => item.matched);
  const missing = items.filter((item) => !item.matched);
  const score = items.length ? Math.round((matched.length / items.length) * 100) : 0;
  return { score, matched, missing };
}

function firstUsefulLines(text: string, limit = 8): string {
  return (text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .slice(0, limit)
    .join("\n");
}

export function buildResumeVariants(resumeText: string, radar: JdRadar): ResumeVariant[] {
  const base = firstUsefulLines(resumeText, 10) || "等待生成优化简历后提供变体预览。";
  const missing = radar.missing.slice(0, 6).map((item) => item.keyword).join("、") || "核心岗位要求";
  return [
    {
      name: "稳健保真版",
      focus: "用于正式投递，保留已验证事实和当前格式。",
      preview: base,
    },
    {
      name: "JD 关键词版",
      focus: "用于 ATS 初筛，优先补齐 JD 关键词，但不新增经历。",
      preview: `建议在现有真实经历中自然覆盖：${missing}\n\n${base}`,
    },
    {
      name: "面试故事版",
      focus: "用于面试前复盘，围绕项目背景、行动和结果组织表达。",
      preview: `围绕这些段落准备口述版本：\n${base}`,
    },
  ];
}

export function buildInterviewQuestions(
  modificationLog: AgentModificationItem[],
  radar: JdRadar,
): InterviewQuestion[] {
  const sectionQuestions = (modificationLog || []).slice(0, 6).map((item) => ({
    sectionName: item.section_name,
    question: `请展开说明「${item.section_name}」中这次优化提到的职责、技术选择和结果证据。`,
  }));
  const keywordQuestions = radar.missing.slice(0, 4).map((item) => ({
    sectionName: "JD 缺口",
    question: `JD 提到了「${item.keyword}」，你是否有真实经历可以补充？如果没有，面试中如何诚实说明学习计划？`,
  }));
  return [...sectionQuestions, ...keywordQuestions].slice(0, 10);
}

export function buildApplicationSnippets(resumeText: string, jdText: string): ApplicationSnippet[] {
  const lines = firstUsefulLines(resumeText, 6);
  const jdKeywords = extractJdKeywords(jdText).slice(0, 5).join("、") || "目标岗位要求";
  return [
    {
      label: "自我介绍",
      text: `您好，我的经历主要围绕 ${jdKeywords} 展开。以下是与岗位相关的经历摘要：\n${lines}`,
    },
    {
      label: "求职动机",
      text: `我关注该岗位，是因为它与我已有的项目经验和希望继续深入的方向高度相关，尤其是 ${jdKeywords}。`,
    },
    {
      label: "项目亮点",
      text: lines || "请先生成优化简历，再自动提取项目亮点。",
    },
  ];
}

export function evaluateOfferDecision(scores: Record<string, number>): OfferDecision {
  const values = Object.values(scores);
  const score = values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : 0;
  const risks = Object.entries(scores)
    .filter(([, value]) => value < 60)
    .map(([key]) => key);
  const verdict = score >= 80 ? "强烈建议推进" : score >= 65 ? "可以推进但需确认风险" : "谨慎推进";
  return { score, verdict, risks };
}

function toSingleLine(value: string): string {
  return (value || "").replace(/\s+/g, " ").trim();
}

function bulletList(items: string[], fallback: string): string {
  const normalized = items.map(toSingleLine).filter(Boolean);
  if (normalized.length === 0) return `- ${fallback}`;
  return normalized.map((item) => `- ${item}`).join("\n");
}

function numberedList(items: string[], fallback: string): string {
  const normalized = items.map(toSingleLine).filter(Boolean);
  if (normalized.length === 0) return `1. ${fallback}`;
  return normalized.map((item, index) => `${index + 1}. ${item}`).join("\n");
}

function keywordLine(items: JdRadarItem[], fallback: string): string {
  const keywords = items.map((item) => item.keyword).filter(Boolean).slice(0, 16);
  return keywords.length ? keywords.join("、") : fallback;
}

export function buildActionPackMarkdown(input: ActionPackInput): string {
  const verifiedFacts = input.factLedger.filter((item) => item.status === "verified").length;
  const reviewFacts = input.factLedger.length - verifiedFacts;
  const cache = input.cacheSummary;
  const cacheLine = cache
    ? `- 本地复用：${cache.hitRate}% 复用，节省 ${cache.savedModelCalls} 次模型调用（复用 ${cache.hits} / 新算 ${cache.misses}）`
    : "- 本地复用：未记录";
  const reviewNote = input.review?.note?.trim() || "暂无复盘备注";
  const jdSummary = firstUsefulLines(input.jdText, 8) || "未提供 JD 摘要";
  const resumeSummary = firstUsefulLines(input.optimizedResumeMd, 10) || "暂无优化简历内容";

  const ledgerSection = input.factLedger.map((item) => {
    const facts = item.addedFacts.length ? `；新增硬事实：${item.addedFacts.slice(0, 6).join("、")}` : "";
    return `- [${FACT_STATUS_TEXT[item.status]}｜${FACT_SOURCE_TEXT[item.source]}] ${item.sectionName}：${toSingleLine(item.summary)}${facts}。原因：${toSingleLine(item.reason)}`;
  });

  const variantSection = input.resumeVariants.flatMap((variant) => [
    `### ${variant.name}`,
    `定位：${variant.focus}`,
    "",
    variant.preview.trim() || "暂无预览",
  ]);

  const snippetSection = input.applicationSnippets.flatMap((snippet) => [
    `### ${snippet.label}`,
    snippet.text.trim() || "暂无内容",
  ]);

  return [
    `# InternPath 求职行动包${input.resumeName ? ` - ${input.resumeName}` : ""}`,
    bulletList([
      input.taskId ? `任务 ID：${input.taskId}` : "",
      input.updatedAt ? `最后更新：${input.updatedAt}` : "",
      `JD 命中：${input.jdRadar.score}%（已覆盖 ${input.jdRadar.matched.length} / 待补齐 ${input.jdRadar.missing.length}）`,
      `事实账本：${verifiedFacts} 条已验证，${reviewFacts} 条需确认`,
      `Offer 判断：${input.offerDecision.score}，${input.offerDecision.verdict}`,
    ], "暂无任务摘要"),
    "## 关键结论",
    [
      `- 优先投递版本：${input.resumeVariants[0]?.name || "稳健保真版"}`,
      `- 待补齐关键词：${keywordLine(input.jdRadar.missing, "暂无明显缺口")}`,
      cacheLine,
      `- 投递状态：${input.review?.status || "准备投递"}`,
    ].join("\n"),
    "## 事实与修改账本",
    ledgerSection.length ? ledgerSection.join("\n") : "- 暂无修改记录",
    "## JD 命中雷达",
    [
      `- 已覆盖：${keywordLine(input.jdRadar.matched, "暂无命中关键词")}`,
      `- 待补齐：${keywordLine(input.jdRadar.missing, "暂无待补齐关键词")}`,
    ].join("\n"),
    "## 简历 A/B 变体",
    variantSection.length ? variantSection.join("\n") : "暂无变体建议",
    "## 面试追问",
    numberedList(input.interviewQuestions.map((item) => `${item.sectionName}：${item.question}`), "暂无追问题目"),
    "## 网申填表话术",
    snippetSection.length ? snippetSection.join("\n\n") : "暂无网申话术",
    "## 投递复盘",
    [`- 当前状态：${input.review?.status || "准备投递"}`, `- 备注：${reviewNote}`].join("\n"),
    "## Offer 决策",
    [
      `- 综合分：${input.offerDecision.score}`,
      `- 判断：${input.offerDecision.verdict}`,
      `- 待确认风险：${input.offerDecision.risks.length ? input.offerDecision.risks.join("、") : "暂无明显低分项"}`,
    ].join("\n"),
    "## 优化简历摘要",
    resumeSummary,
    "## JD 摘要",
    jdSummary,
  ].join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
}
