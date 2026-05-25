import type { AnalysisResult, Decision, LearningSuggestion, MatchDimension, Priority, ResumeAdvice, RiskLevel } from "../types/analysis";
import type { ChatModelConfig } from "../types/modelConfig";
import type { ResumeChunk } from "../types/resume";
import { safeParseModelJson } from "../utils/safeParseModelJson";
import { validateModelCitations } from "../utils/citationValidator";
import { callGeminiWithConfig, classifyGeminiError } from "./geminiClient";

export interface ChatAnalysisInput {
  jdText: string;
  targetType: string;
  jobDirection: string;
  retrievedChunks: ResumeChunk[];
  config: ChatModelConfig;
  parsedJD?: any;
  requirementMatches?: any;
  hardConstraintsResult?: any;
  userExtraContext?: string;
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

function mapDecision(decision: string | undefined, score: number): Decision {
  if (decision === "strong_apply" || decision === "strong_yes") return "strong_yes";
  if (decision === "apply" || decision === "yes") return "yes";
  if (decision === "cautious" || decision === "maybe" || decision === "apply_after_revision") return "maybe";
  if (decision === "not_recommended" || decision === "no" || decision === "low_priority") return "no";
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
  // If we have structured JD and matches, we perform structural, evidence-constrained evaluation
  if (input.parsedJD && input.requirementMatches) {
    return `你是一名严格、客观、不讨好用户的求职分析专家。
你必须基于提供的 JD 结构化结果、简历证据片段、向量召回结果和硬性条件检查结果进行分析。
向量相似度只代表语义相关，不代表用户满足岗位要求。
你不能编造用户没有提供的经历。
你不能把“学习过”当成“熟练掌握”。
你不能把课程项目直接等同于生产经验。
你必须区分 matched、partial、missing、unknown。
如果证据不足，必须输出 unknown 或 evidence_insufficient。
如果存在硬性风险，必须优先指出。
请输出严格 JSON，不要输出 markdown，不要包含 markdown 代码块。

【分析输入】
1. 岗位结构化 JD:
${JSON.stringify(input.parsedJD, null, 2)}

2. 针对每个岗位要求的简历向量召回证据 (requirementMatches):
${JSON.stringify(input.requirementMatches, null, 2)}

3. 硬性条件筛查结果 (hardConstraintsResult):
${JSON.stringify(input.hardConstraintsResult, null, 2)}

4. 候选人补充说明:
${input.userExtraContext || "无"}

【输出 JSON 格式要求】
必须严格符合以下 JSON 模式 (JSON Schema)：
{
  "requirement_assessments": [
    {
      "requirement_id": "req_001",
      "requirement_text": "JD要求原文",
      "status": "matched | partial | missing | unknown",
      "confidence": "high | medium | low",
      "evidence_used": ["关联的简历片段 ID，如 chunk id"],
      "reason": "具体匹配判断理由，基于证据对比",
      "gap": "缺失细节或不匹配之处",
      "fixable_by_resume_rewrite": true
    }
  ],
  "decision": {
    "decision": "strong_apply | apply | apply_after_revision | low_priority | not_recommended",
    "confidence": "high | medium | low",
    "overall_score": 85,
    "summary": "一句话投递决策总结",
    "why_this_decision": ["决策理由 1", "决策理由 2"],
    "main_risks": ["潜在缺口或硬性条件风险 1", "潜在缺口 2"],
    "main_opportunities": ["已具备优势或机会 1", "机会 2"]
  },
  "matchBreakdown": {
    "techStack": 90,
    "projectExperience": 80,
    "educationBackground": 85,
    "keywordCoverage": 75,
    "seniorityFit": 80,
    "competitionLevel": 70,
    "evidenceStrength": 80,
    "resumeImprovementPotential": 85
  },
  "resume_rewrite_suggestions": [
    {
      "target_requirement_id": "req_001",
      "resume_section": "项目经历/工作经历/技能",
      "current_problem": "当前简历表达的问题",
      "rewrite_strategy": "改写策略与方向",
      "example_rewrite": "改写后的高契合度对比表达，符合 STAR 原则和量化要求，不虚构经历",
      "risk": "do_not_exaggerate | needs_more_evidence | safe_to_rewrite"
    }
  ],
  "learning_plan": [
    {
      "gap": "对应缺失的技能或业务背景",
      "topic": "推荐学习或刷题的主题",
      "priority": "high | medium | low",
      "reason": "推荐理由，与岗位的关联性",
      "suggested_action": "具体的学习/刷题行动指南",
      "estimated_effort": "2天 / 5天 / 2周"
    }
  ],
  "interview_prep": [
    {
      "topic": "常问高频技术点",
      "question_type": "技术问答 / 场景设计 / 取舍分析",
      "reason": "JD 强相关且简历中仅偏理论"
    }
  ]
}
`;
  }

  // Fallback old flat layout format
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

function mapDimensions(breakdown: any): MatchDimension[] {
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

// Rich Schema for the multi-stage structural parsing
const JobAnalysisSchema = {
  type: "object",
  properties: {
    requirement_assessments: {
      type: "array",
      items: {
        type: "object",
        properties: {
          requirement_id: { type: "string" },
          requirement_text: { type: "string" },
          status: { type: "string", enum: ["matched", "partial", "missing", "unknown"] },
          confidence: { type: "string", enum: ["high", "medium", "low"] },
          evidence_used: { type: "array", items: { type: "string" } },
          reason: { type: "string" },
          gap: { type: "string" },
          fixable_by_resume_rewrite: { type: "boolean" }
        },
        required: ["requirement_id", "requirement_text", "status", "confidence", "evidence_used", "reason", "gap", "fixable_by_resume_rewrite"]
      }
    },
    decision: {
      type: "object",
      properties: {
        decision: { type: "string", enum: ["strong_apply", "apply", "apply_after_revision", "low_priority", "not_recommended"] },
        confidence: { type: "string", enum: ["high", "medium", "low"] },
        overall_score: { type: "integer" },
        summary: { type: "string" },
        why_this_decision: { type: "array", items: { type: "string" } },
        main_risks: { type: "array", items: { type: "string" } },
        main_opportunities: { type: "array", items: { type: "string" } }
      },
      required: ["decision", "confidence", "overall_score", "summary", "why_this_decision", "main_risks", "main_opportunities"]
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
        resumeImprovementPotential: { type: "integer" }
      },
      required: [
        "techStack",
        "projectExperience",
        "educationBackground",
        "keywordCoverage",
        "seniorityFit",
        "competitionLevel",
        "evidenceStrength",
        "resumeImprovementPotential"
      ]
    },
    resume_rewrite_suggestions: {
      type: "array",
      items: {
        type: "object",
        properties: {
          target_requirement_id: { type: "string" },
          resume_section: { type: "string" },
          current_problem: { type: "string" },
          rewrite_strategy: { type: "string" },
          example_rewrite: { type: "string" },
          risk: { type: "string", enum: ["do_not_exaggerate", "needs_more_evidence", "safe_to_rewrite"] }
        },
        required: ["target_requirement_id", "resume_section", "current_problem", "rewrite_strategy", "example_rewrite", "risk"]
      }
    },
    learning_plan: {
      type: "array",
      items: {
        type: "object",
        properties: {
          gap: { type: "string" },
          topic: { type: "string" },
          priority: { type: "string", enum: ["high", "medium", "low"] },
          reason: { type: "string" },
          suggested_action: { type: "string" },
          estimated_effort: { type: "string" }
        },
        required: ["gap", "topic", "priority", "reason", "suggested_action", "estimated_effort"]
      }
    },
    interview_prep: {
      type: "array",
      items: {
        type: "object",
        properties: {
          topic: { type: "string" },
          question_type: { type: "string" },
          reason: { type: "string" }
        },
        required: ["topic", "question_type", "reason"]
      }
    }
  },
  required: [
    "requirement_assessments",
    "decision",
    "matchBreakdown",
    "resume_rewrite_suggestions",
    "learning_plan",
    "interview_prep"
  ]
};

// Original schema fallback
const LegacyJobAnalysisSchema = {
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

export async function analyzeJobWithChatConfig(
  input: ChatAnalysisInput
): Promise<Omit<AnalysisResult, "id" | "createdAt" | "draft"> & { chatModelId?: string }> {
  if (
    input.config.provider !== "gemini" &&
    input.config.provider !== "custom" &&
    input.config.provider !== "openai-compatible"
  ) {
    throw new Error("当前仅支持 Gemini 或自定义/OpenAI 兼容大语言模型配置");
  }
  
  const isMultiStage = Boolean(input.parsedJD && input.requirementMatches);
  const currentSchema = isMultiStage ? JobAnalysisSchema : LegacyJobAnalysisSchema;

  async function executeAnalysis(modelId: string, useSchema: boolean): Promise<string> {
    return await callGeminiWithConfig({
      config: {
        ...input.config,
        modelId,
      },
      prompt: buildPrompt(input),
      forceJson: true,
      responseSchema: useSchema ? currentSchema : undefined,
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
        const classification = classifyGeminiError(error, undefined, input.config.name || input.config.modelId);

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
      const primaryClassification = classifyGeminiError(primaryError, undefined, input.config.name || input.config.modelId);
      
      if (primaryClassification.errorType === "high_demand" && input.config.fallbackModelId?.trim()) {
        finalModelId = input.config.fallbackModelId.trim();
        text = await runWithRetryAndFallback(finalModelId, true);
      } else {
        throw primaryError;
      }
    }
  } catch (finalError: any) {
    const classification = classifyGeminiError(finalError, undefined, input.config.name || input.config.modelId);
    const error = new Error(classification.message);
    (error as any).errorType = classification.errorType;
    (error as any).status = classification.status;
    (error as any).responseBody = classification.responseBody;
    throw error;
  }

  const parsed = safeParseModelJson<any>(text);

  let score = 50;
  let rawDecision = "cautious";
  let summary = "Gemini 已基于 JD 和检索片段完成判断。";
  let strengths: string[] = [];
  let risks: string[] = [];
  let matchBreakdown = parsed.matchBreakdown ?? {};

  if (isMultiStage && parsed.decision && typeof parsed.decision === "object") {
    // New structural mapping
    score = clampScore(parsed.decision.overall_score, 50);
    rawDecision = parsed.decision.decision || "cautious";
    summary = parsed.decision.summary || summary;
    strengths = Array.isArray(parsed.decision.main_opportunities) ? parsed.decision.main_opportunities : [];
    risks = Array.isArray(parsed.decision.main_risks) ? parsed.decision.main_risks : [];
  } else {
    // Old mapping
    score = clampScore(parsed.score, 50);
    rawDecision = parsed.decision || "cautious";
    summary = parsed.summary || summary;
    strengths = Array.isArray(parsed.strengths) ? parsed.strengths : [];
    risks = Array.isArray(parsed.risks) ? parsed.risks : [];
  }

  // Adjust score and recommendation if there is a blocking hard risk
  if (input.hardConstraintsResult?.has_blocking_risk) {
    if (rawDecision === "strong_apply" || rawDecision === "apply") {
      rawDecision = "cautious";
    }
    score = Math.min(score, 50); // Hard constraint blocker caps match score at 50
  }

  const decision = mapDecision(rawDecision, score);

  let advice: ResumeAdvice[] = [];
  if (isMultiStage && Array.isArray(parsed.resume_rewrite_suggestions)) {
    // Construct rich compatible advice
    advice = parsed.resume_rewrite_suggestions.slice(0, 8).map((s: any, idx: number) => {
      // Find corresponding chunks from assessments
      let basedOnChunkIds: string[] = [];
      if (s.target_requirement_id && Array.isArray(parsed.requirement_assessments)) {
        const matchingAss = parsed.requirement_assessments.find(
          (ass: any) => ass && ass.requirement_id === s.target_requirement_id
        );
        if (matchingAss && Array.isArray(matchingAss.evidence_used)) {
          basedOnChunkIds = matchingAss.evidence_used.filter(Boolean);
        }
      }

      // Look up JD requirement priority from requirementMatches
      let reqPriority: string = "unknown";
      if (s.target_requirement_id && input.requirementMatches?.requirement_matches) {
        const match = input.requirementMatches.requirement_matches.find(
          (m: any) => m && m.requirement_id === s.target_requirement_id
        );
        if (match) {
          reqPriority = match.priority; // "must_have" or "nice_to_have"
        }
      }

      // Calculate priority:
      // - "needs_more_evidence" -> high
      // - "safe_to_rewrite" -> high if core must_have, otherwise medium
      // - other -> medium if core must_have, otherwise low
      let priority: "high" | "medium" | "low" = "low";
      if (s.risk === "needs_more_evidence") {
        priority = "high";
      } else if (s.risk === "safe_to_rewrite") {
        priority = reqPriority === "must_have" ? "high" : "medium";
      } else {
        priority = reqPriority === "must_have" ? "medium" : "low";
      }

      return {
        id: `advice-${idx}`,
        priority,
        issue: `【${s.resume_section || "简历表达"}】针对岗位要求 ID "${s.target_requirement_id || "未知要求"}" 的不足之处：${s.current_problem}`,
        suggestion: s.rewrite_strategy,
        example: s.example_rewrite,
        impact: priority === "high" ? "需补充强力真实经历/证书证据，避免虚构" : priority === "medium" ? "安全改写表述，大幅提升简历契合度" : "细节微调润色，提供更丰富的量化支撑",
        basedOnChunkIds,
        target_requirement_id: s.target_requirement_id,
        resume_section: s.resume_section,
        risk: s.risk
      };
    });
  } else {
    advice = mapAdvice(parsed.resumeAdvice);
  }

  let suggestions: LearningSuggestion[] = [];
  if (isMultiStage && Array.isArray(parsed.learning_plan)) {
    suggestions = parsed.learning_plan.slice(0, 6).map((l: any, idx: number) => ({
      id: `learning-${idx}`,
      skill: l.topic || l.gap || "专业背景提升",
      order: idx + 1,
      estimatedTime: l.estimated_effort || "3-7 天",
      practiceDirection: `【缺口: ${l.gap}】行动指南: ${l.suggested_action}`,
      interviewFocus: `【重点】${l.reason}`,
      gap: l.gap,
      priority: l.priority,
      reason: l.reason
    }));
  } else {
    suggestions = mapLearning(parsed.learningRoadmap);
  }

  // Next actions
  const nextActions = [
    "针对硬性条件和筛查结论进行自查与核实",
    "优先改造【必须改 (高优先级)】的简历表达",
    "围绕岗位核心缺口做针对性的项目实践和学习",
    "准备面试中的取舍论证和场景设计"
  ];
  if (isMultiStage && Array.isArray(parsed.interview_prep) && parsed.interview_prep.length > 0) {
    parsed.interview_prep.slice(0, 2).forEach((prep: any) => {
      nextActions.push(`准备面试问题：${prep.topic} (类型: ${prep.question_type}，原因: ${prep.reason})`);
    });
  }

  // Set the cited chunks
  let citedResumeChunks: string[] = [];
  if (isMultiStage && Array.isArray(parsed.requirement_assessments)) {
    // Gather all evidence chunk ids referenced in assessments
    const ids = new Set<string>();
    parsed.requirement_assessments.forEach((ass: any) => {
      if (Array.isArray(ass.evidence_used)) {
        ass.evidence_used.forEach((id: string) => {
          if (id) ids.add(id);
        });
      }
    });
    citedResumeChunks = Array.from(ids);
  } else {
    citedResumeChunks = parsed.citedResumeChunks ?? [];
  }

  const resultObj = {
    chatModelId: finalModelId,
    decision,
    matchScore: score,
    riskLevel: riskFromScore(score),
    priority: priorityFromScore(score),
    oneLineReason: summary,
    detectedKeywords: strengths.slice(0, 8),
    missingKeywords: risks.slice(0, 8),
    dimensions: mapDimensions(matchBreakdown),
    resumeAdvice: advice,
    learningSuggestions: suggestions,
    nextActions,
    citedResumeChunks,
    
    // Custom pipeline outcomes for step-by-step history trace
    parsedJD: input.parsedJD,
    requirementMatches: input.requirementMatches,
    hardConstraintsResult: input.hardConstraintsResult,
    requirementAssessments: parsed.requirement_assessments || []
  };

  return validateModelCitations(resultObj, input.retrievedChunks);
}
