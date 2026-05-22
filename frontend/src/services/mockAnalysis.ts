import type { AnalysisResult, LearningSuggestion, MatchDimension, ResumeAdvice } from "../types/analysis";
import type { JobDraft, JobLevel } from "../types/job";
import type { CandidateProfile } from "../types/profile";
import { clampScore } from "../utils/format";
import { decisionFromScore, priorityFromScore, riskFromScore } from "../utils/score";

const KEYWORDS = [
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
];

const levelWeight: Record<JobLevel, number> = {
  intern: 10,
  campus: 8,
  junior: 4,
  middle: -10,
  unknown: 0,
};

function normalize(text: string): string {
  return text.toLowerCase();
}

function includesKeyword(text: string, keyword: string): boolean {
  const lower = normalize(text);
  return lower.includes(keyword.toLowerCase());
}

function detectKeywords(text: string): string[] {
  return KEYWORDS.filter((keyword) => includesKeyword(text, keyword));
}

function profileText(profile: CandidateProfile, draft: JobDraft): string {
  return [
    profile.resumeText,
    profile.targetRole,
    profile.education,
    profile.skillStack.join(" "),
    profile.preferredDirections.join(" "),
    profile.projects.map((project) => `${project.name} ${project.role} ${project.description} ${project.techStack.join(" ")} ${project.impact}`).join(" "),
    draft.resumeText,
    draft.projectText,
    draft.skillsText,
    draft.goalText,
  ].join(" ");
}

function scoreDimension(label: string, score: number, tags: string[], explanation: string): MatchDimension {
  return {
    id: label,
    label,
    score: clampScore(score),
    tags,
    explanation,
  };
}

function buildAdvice(missing: string[], detected: string[], projectMatched: boolean): ResumeAdvice[] {
  const advice: ResumeAdvice[] = [];

  if (missing.length) {
    advice.push({
      id: "missing-keywords",
      priority: "high",
      issue: `JD 中的 ${missing.slice(0, 3).join("、")} 暂未在材料中形成明确证据。`,
      suggestion: "把相关课程、项目片段或练习成果补进简历，至少让筛选系统能看到关键词和上下文。",
      example: `围绕 ${missing[0]} 补充一条项目经历：负责需求拆解、核心实现和结果验证，并说明你具体完成了什么。`,
      impact: "直接影响关键词筛选和第一轮匹配判断。",
    });
  }

  if (!projectMatched) {
    advice.push({
      id: "project-fit",
      priority: "high",
      issue: "当前材料里项目经历和岗位关键词的绑定还不够紧。",
      suggestion: "选择一个最接近岗位的项目，把技术选型、职责边界、结果指标写完整。",
      example: `在项目描述中加入“使用 ${detected[0] ?? "核心技术"} 完成核心模块，覆盖接口联调、异常处理和交付结果”。`,
      impact: "会影响面试官判断你是否真的做过类似事情。",
    });
  }

  advice.push({
    id: "metrics",
    priority: "medium",
    issue: "简历表达如果只有职责，没有结果，会显得不可验证。",
    suggestion: "补充数据指标、规模、性能、用户量、准确率或交付周期。",
    example: "将“负责后台接口开发”改为“独立实现 8 个核心接口，支撑列表筛选、权限校验和异常回滚，接口平均响应低于 200ms”。",
    impact: "增强可信度和简历可读性。",
  });

  advice.push({
    id: "language",
    priority: "low",
    issue: "部分经历可以更贴近 JD 的岗位语言。",
    suggestion: "把泛泛的“学习过、了解过”替换为“实现过、优化过、验证过”。",
    example: "将“了解 TypeScript”改为“在项目中使用 TypeScript 建模表单状态、接口响应和核心业务实体”。",
    impact: "提升表达专业感，降低空泛感。",
  });

  return advice;
}

function buildLearning(missing: string[], detected: string[]): LearningSuggestion[] {
  const gaps = missing.length ? missing : detected.slice(0, 2);
  return gaps.slice(0, 5).map((skill, index) => ({
    id: `${skill}-${index}`,
    skill,
    order: index + 1,
    estimatedTime: index === 0 ? "2-3 天" : "3-5 天",
    practiceDirection: skill === "算法" ? "刷数组、哈希、双指针和动态规划基础题" : `做一个能展示 ${skill} 的小模块或重构片段`,
    interviewFocus: skill === "系统设计" ? "准备缓存、限流、异步任务和数据库设计表达" : `准备 ${skill} 的项目使用场景、踩坑和取舍`,
  }));
}

export function createEmptyDraft(): JobDraft {
  return {
    company: "",
    title: "",
    link: "",
    location: "",
    workMode: "unknown",
    level: "intern",
    jdText: "",
    targetType: "实习 / 初级",
    jobDirection: "前端 / 全栈 / AI 应用",
    resumeText: "",
    projectText: "",
    skillsText: "",
    goalText: "",
    useDefaultProfile: true,
  };
}

import { safeUUID } from "../utils/uuid";

export function analyzeJobDraft(draft: JobDraft, profile: CandidateProfile): AnalysisResult {
  const detectedKeywords = detectKeywords(draft.jdText);
  const candidateText = profileText(profile, draft);
  const matchedKeywords = detectedKeywords.filter((keyword) => includesKeyword(candidateText, keyword));
  const missingKeywords = detectedKeywords.filter((keyword) => !matchedKeywords.includes(keyword));
  const keywordCoverage = detectedKeywords.length ? matchedKeywords.length / detectedKeywords.length : 0.35;
  const projectMatched = profile.projects.some((project) =>
    detectedKeywords.some((keyword) => includesKeyword(`${project.description} ${project.techStack.join(" ")}`, keyword)),
  ) || detectedKeywords.some((keyword) => includesKeyword(draft.projectText, keyword));
  const blockedPenalty = profile.blockedDirections.some((direction) => includesKeyword(draft.jdText, direction)) ? 14 : 0;
  const goalBonus = profile.preferredDirections.some((direction) => includesKeyword(draft.jdText, direction)) ? 8 : 0;
  const levelBonus = levelWeight[draft.level];
  const projectBonus = projectMatched ? 12 : -6;
  const resumeLengthBonus = candidateText.length > 360 ? 6 : 0;
  const matchScore = clampScore(38 + keywordCoverage * 42 + projectBonus + goalBonus + levelBonus + resumeLengthBonus - blockedPenalty);
  const decision = decisionFromScore(matchScore);
  const riskLevel = riskFromScore(matchScore);
  const priority = priorityFromScore(matchScore);

  const dimensions: MatchDimension[] = [
    scoreDimension(
      "技能匹配",
      keywordCoverage * 100,
      matchedKeywords,
      matchedKeywords.length ? `材料覆盖了 ${matchedKeywords.join("、")}。` : "暂未识别到明确技能覆盖。",
    ),
    scoreDimension(
      "项目经历匹配",
      projectMatched ? 78 : 42,
      projectMatched ? ["项目相关"] : ["证据不足"],
      projectMatched ? "已有项目经历能承接岗位关键词。" : "项目经历需要更明确地绑定岗位要求。",
    ),
    scoreDimension("学历 / 背景匹配", profile.education ? 72 : 52, profile.education ? [profile.education] : ["待补充"], "背景信息越具体，判断越稳定。"),
    scoreDimension("年限 / 级别匹配", 62 + levelBonus * 2, [draft.level], "根据岗位级别 and 个人目标粗略估计。"),
    scoreDimension("关键词覆盖", keywordCoverage * 100, detectedKeywords, `JD 检出 ${detectedKeywords.length || 0} 个关键标签。`),
    scoreDimension("潜在短板", 100 - missingKeywords.length * 13, missingKeywords, missingKeywords.length ? `主要缺口：${missingKeywords.join("、")}。` : "暂无明显短板。"),
  ];

  const oneLineReason =
    decision === "strong_yes"
      ? "岗位要求和你的材料高度贴合，建议优先投递并快速改简历。"
      : decision === "yes"
        ? "整体匹配不错，补齐关键证据后值得投递。"
        : decision === "maybe"
          ? "存在可补短板，建议先改简历或补项目证据再投。"
          : "当前材料和岗位要求距离较大，不建议投入太多时间。";

  return {
    id: safeUUID(),
    createdAt: new Date().toISOString(),
    draft,
    decision,
    matchScore,
    riskLevel,
    priority,
    oneLineReason,
    detectedKeywords,
    missingKeywords,
    dimensions,
    resumeAdvice: buildAdvice(missingKeywords, detectedKeywords, projectMatched),
    learningSuggestions: buildLearning(missingKeywords, detectedKeywords),
    nextActions: [
      "先把高优先级简历建议改完",
      "补充 1 条最贴近 JD 的项目证据",
      decision === "no" ? "把该岗位放入观察或放弃列表" : "准备一版投递简历并记录投递状态",
    ],
  };
}
