import type { AnalysisResult, Decision, LearningSuggestion, MatchDimension, Priority, ResumeAdvice, RiskLevel } from "../types/analysis";
import type { ChatModelConfig } from "../types/modelConfig";
import type { ResumeChunk } from "../types/resume";
import { safeParseModelJson } from "../utils/safeParseModelJson";
import { callGeminiWithConfig, classifyGeminiError } from "./geminiClient";

interface ChatAnalysisInput {
  jdText: string;
  targetType: string;
  jobDirection: string;
  retrievedChunks: ResumeChunk[];
  config: ChatModelConfig;
}

interface GeminiResumeAdvice {
  id?: string;
  priority?: "high" | "medium" | "low";
  problem?: string;
  reason?: string;
  suggestion?: string;
  example?: string;
  expectedImpact?: string;
  basedOnChunkIds?: string[];
}

interface GeminiAnalysis {
  decision?: "strong_apply" | "apply" | "cautious" | "not_recommended";
  score?: number;
  summary?: string;
  strengths?: string[];
  risks?: string[];
  matchBreakdown?: Record<string, number | null>;
  resumeAdvice?: GeminiResumeAdvice[];
  learningRoadmap?: {
    skills?: string[];
    practiceTopics?: string[];
    projectSuggestions?: string[];
    interviewPreparation?: string[];
  } | null;
  citedResumeChunks?: string[];
}

function clampScore(value: unknown, fallback = 50): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function mapDecision(decision: GeminiAnalysis["decision"], score: number): Decision {
  if (decision === "strong_apply") return "strong_yes";
  if (decision === "apply") return "yes";
  if (decision === "cautious") return "maybe";
  if (decision === "not_recommended") return "no";
  if (score >= 85) return "strong_yes";
  if (score >= 70) return "yes";
  if (score >= 50) return "maybe";
  return "no";
}

function riskFromScore(score: number): RiskLevel {
  if (score >= 75) return "low";
  if (score >= 50) return "medium";
  return "high";
}

function priorityFromScore(score: number): Priority {
  if (score >= 85) return "P0";
  if (score >= 70) return "P1";
  if (score >= 50) return "P2";
  return "P3";
}

function buildPrompt(input: ChatAnalysisInput): string {
  const chunks = input.retrievedChunks.map((chunk) => ({
    id: chunk.id,
    section: chunk.section,
    score: chunk.score,
    keywords: chunk.keywords ?? [],
    content: chunk.content,
  }));

  return `
You are a rigorous job-fit analysis system for a personal job decision desk.

Analysis rules:
- Analyze only from the JD and retrievedChunks.
- Do not invent resume experience that is not present in retrievedChunks.
- If evidence is insufficient, mark it clearly as a risk or missing evidence.
- Do not judge match only by keywords. Consider tech stack, project depth, seniority, result metrics, education background, competition level, evidence strength, and resume improvement potential.
- resumeAdvice must include basedOnChunkIds.
- citedResumeChunks must list the referenced chunk ids.

Output requirements:
- Return valid JSON only.
- Do not return Markdown.
- Do not wrap the JSON in code fences.
- Do not add explanations before or after the JSON.
- Do not write "Here is".
- The first character must be {.
- The last character must be }.

Output schema:
{
  "decision": "strong_apply | apply | cautious | not_recommended",
  "score": 0,
  "summary": "",
  "strengths": [],
  "risks": [],
  "matchBreakdown": {
    "techStack": 0,
    "projectExperience": 0,
    "educationBackground": 0,
    "keywordCoverage": 0,
    "seniorityFit": 0,
    "competitionLevel": 0,
    "evidenceStrength": 0,
    "resumeImprovementPotential": 0
  },
  "resumeAdvice": [
    {
      "id": "",
      "priority": "high | medium | low",
      "problem": "",
      "reason": "",
      "suggestion": "",
      "example": "",
      "expectedImpact": "",
      "basedOnChunkIds": []
    }
  ],
  "learningRoadmap": {
    "skills": [],
    "practiceTopics": [],
    "projectSuggestions": [],
    "interviewPreparation": []
  },
  "citedResumeChunks": []
}

Input:
${JSON.stringify(
  {
    jdText: input.jdText,
    targetType: input.targetType,
    jobDirection: input.jobDirection,
    retrievedChunks: chunks,
  },
  null,
  2,
)}
`;
}

function dimension(id: string, label: string, score: unknown, explanation: string): MatchDimension {
  return {
    id,
    label,
    score: clampScore(score),
    tags: [],
    explanation,
  };
}

function mapDimensions(breakdown: GeminiAnalysis["matchBreakdown"]): MatchDimension[] {
  const source = breakdown ?? {};
  return [
    dimension("techStack", "技能匹配", source.techStack, "基于 JD 技术栈和检索片段的技术证据判断。"),
    dimension("projectExperience", "项目经历匹配", source.projectExperience, "基于项目深度、职责边界和交付结果判断。"),
    dimension("educationBackground", "学历 / 背景匹配", source.educationBackground, "基于教育背景和岗位门槛判断。"),
    dimension("keywordCoverage", "关键词覆盖", source.keywordCoverage, "基于 JD 关键词在检索片段中的覆盖判断。"),
    dimension("seniorityFit", "年限 / 级别匹配", source.seniorityFit, "基于岗位级别和简历证据判断。"),
    dimension("competitionLevel", "岗位竞争难度", source.competitionLevel, "竞争难度越高，越需要强证据支撑。"),
    dimension("evidenceStrength", "证据强度", source.evidenceStrength, "检索片段是否足以支撑投递判断。"),
    dimension("resumeImprovementPotential", "简历改造空间", source.resumeImprovementPotential, "通过改写和补证据能提升多少匹配度。"),
  ];
}

function mapAdvice(items: GeminiResumeAdvice[] | undefined): ResumeAdvice[] {
  return (items ?? []).slice(0, 8).map((item, index) => ({
    id: item.id || `advice-${index}`,
    priority: item.priority === "high" || item.priority === "low" ? item.priority : "medium",
    issue: item.problem || item.reason || "简历表达和 JD 的绑定不够明确。",
    suggestion: item.suggestion || "基于已检索片段重写，不要新增未发生的经历。",
    example: item.example || "请补充可验证的动作、技术栈和结果指标。",
    impact: item.expectedImpact || "提升岗位筛选通过率和面试追问质量。",
    basedOnChunkIds: item.basedOnChunkIds ?? [],
  }));
}

function mapLearning(roadmap: GeminiAnalysis["learningRoadmap"]): LearningSuggestion[] {
  const skills = roadmap?.skills?.length ? roadmap.skills : ["项目表达"];
  return skills.slice(0, 6).map((skill, index) => ({
    id: `learning-${index}`,
    skill,
    order: index + 1,
    estimatedTime: "2-5 天",
    practiceDirection: roadmap?.practiceTopics?.[index] || roadmap?.projectSuggestions?.[index] || `围绕 ${skill} 做一个可展示练习。`,
    interviewFocus: roadmap?.interviewPreparation?.[index] || `准备 ${skill} 的项目场景、取舍和结果。`,
  }));
}

const JobAnalysisSchema = {
  type: "object",
  properties: {
    decision: {
      type: "string",
      enum: ["strong_apply", "apply", "cautious", "not_recommended"],
    },
    score: {
      type: "integer",
    },
    summary: {
      type: "string",
    },
    strengths: {
      type: "array",
      items: {
        type: "string",
      },
    },
    risks: {
      type: "array",
      items: {
        type: "string",
      },
    },
    matchBreakdown: {
      type: "object",
      properties: {
        techStack: { type: "integer" },
        projectExperience: { type: "integer" },
        educationBackground: { type: "integer" },
        keywordCoverage: { type: "integer" },
        seniorityFit: { type: "integer" },
        competitionLevel: { type: "integer" },
        evidenceStrength: { type: "integer" },
        resumeImprovementPotential: { type: "integer" },
      },
      required: [
        "techStack",
        "projectExperience",
        "educationBackground",
        "keywordCoverage",
        "seniorityFit",
        "competitionLevel",
        "evidenceStrength",
        "resumeImprovementPotential",
      ],
    },
    resumeAdvice: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },
          priority: { type: "string", enum: ["high", "medium", "low"] },
          problem: { type: "string" },
          reason: { type: "string" },
          suggestion: { type: "string" },
          example: { type: "string" },
          expectedImpact: { type: "string" },
          basedOnChunkIds: {
            type: "array",
            items: { type: "string" },
          },
        },
        required: ["priority", "problem", "suggestion", "basedOnChunkIds"],
      },
    },
    learningRoadmap: {
      type: "object",
      properties: {
        skills: { type: "array", items: { type: "string" } },
        practiceTopics: { type: "array", items: { type: "string" } },
        projectSuggestions: { type: "array", items: { type: "string" } },
        interviewPreparation: { type: "array", items: { type: "string" } },
      },
    },
    citedResumeChunks: {
      type: "array",
      items: { type: "string" },
    },
  },
  required: [
    "decision",
    "score",
    "summary",
    "strengths",
    "risks",
    "matchBreakdown",
    "resumeAdvice",
    "learningRoadmap",
    "citedResumeChunks",
  ],
};

function asStringList(value: string[] | undefined): string[] {
  return (value ?? []).filter((item) => item.trim());
}

export async function analyzeJobWithChatConfig(input: ChatAnalysisInput): Promise<Omit<AnalysisResult, "id" | "createdAt" | "draft"> & { chatModelId?: string }> {
  if (input.config.provider !== "gemini") throw new Error("当前仅支持 Gemini 大语言模型配置");
  
  async function executeAnalysis(modelId: string, useSchema: boolean): Promise<string> {
    return await callGeminiWithConfig({
      config: {
        ...input.config,
        modelId,
      },
      prompt: buildPrompt(input),
      forceJson: true,
      responseSchema: useSchema ? JobAnalysisSchema : undefined,
      overrideGenerationConfig: {
        responseMimeType: "application/json",
        maxOutputTokens: Math.max(input.config.maxOutputTokens ?? 8192, 8192),
        thinkingConfig: {
          thinkingLevel: "minimal"
        }
      }
    });
  }

  let finalModelId = input.config.modelId;
  let text = "";

  async function runWithRetryAndFallback(modelId: string, isFallback: boolean): Promise<string> {
    const retryDelays = [2000, 5000, 10000];
    let attempt = 0;

    while (true) {
      try {
        try {
          return await executeAnalysis(modelId, true);
        } catch (error: any) {
          const msg = error.message || String(error);
          if (msg.includes("400") || msg.includes("responseSchema")) {
            return await executeAnalysis(modelId, false);
          }
          throw error;
        }
      } catch (error: any) {
        const classification = classifyGeminiError(error);

        if (classification.errorType === "high_demand" && input.config.fallbackModelId?.trim() && !isFallback) {
          throw error;
        }

        if (!classification.retryable || attempt >= retryDelays.length) {
          throw error;
        }

        const delay = retryDelays[attempt];
        attempt++;
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
  }

  try {
    try {
      text = await runWithRetryAndFallback(input.config.modelId, false);
    } catch (primaryError: any) {
      const primaryClassification = classifyGeminiError(primaryError);
      
      if (primaryClassification.errorType === "high_demand" && input.config.fallbackModelId?.trim()) {
        finalModelId = input.config.fallbackModelId.trim();
        text = await runWithRetryAndFallback(finalModelId, true);
      } else {
        throw primaryError;
      }
    }
  } catch (finalError: any) {
    const classification = classifyGeminiError(finalError);
    const error = new Error(classification.message);
    (error as any).errorType = classification.errorType;
    (error as any).status = classification.status;
    (error as any).responseBody = classification.responseBody;
    throw error;
  }

  const parsed = safeParseModelJson<GeminiAnalysis>(text);

  const score = clampScore(parsed.score, 50);
  const decision = mapDecision(parsed.decision, score);
  const strengths = asStringList(parsed.strengths);
  const risks = asStringList(parsed.risks);
  return {
    chatModelId: finalModelId,
    decision,
    matchScore: score,
    riskLevel: riskFromScore(score),
    priority: priorityFromScore(score),
    oneLineReason: parsed.summary || "Gemini 已基于 JD 和检索片段完成判断。",
    detectedKeywords: strengths.slice(0, 8),
    missingKeywords: risks.slice(0, 8),
    dimensions: mapDimensions(parsed.matchBreakdown),
    resumeAdvice: mapAdvice(parsed.resumeAdvice),
    learningSuggestions: mapLearning(parsed.learningRoadmap),
    nextActions: ["处理高优先级简历建议", "保存到历史并标记投递状态", "按学习路线补齐关键缺口"],
    citedResumeChunks: parsed.citedResumeChunks ?? [],
  };
}
