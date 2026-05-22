import type { ParsedResume, ResumeChunk, UploadedResumeFile } from "../types/resume";
import { getFileExtension } from "./fileValidation";
import { safeUUID } from "./uuid";

const SAMPLE_SKILLS = [
  "React",
  "TypeScript",
  "JavaScript",
  "Node.js",
  "Python",
  "SQL",
  "Docker",
  "前端工程化",
  "RAG",
  "数据分析",
];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function makeResumeFile(file: File): UploadedResumeFile {
  return {
    id: safeUUID(),
    name: file.name,
    size: file.size,
    type: file.type || getFileExtension(file.name),
    uploadedAt: new Date().toISOString(),
    status: "parsed",
  };
}

function detectKeywords(text: string): string[] {
  const lower = text.toLowerCase();
  return SAMPLE_SKILLS.filter((keyword) => lower.includes(keyword.toLowerCase()));
}

function makeChunk(file: UploadedResumeFile, index: number, section: string, content: string): ResumeChunk {
  return {
    id: `${file.id}-chunk-${index}`,
    resumeFileId: file.id,
    index,
    section,
    content,
    keywords: detectKeywords(content),
    metadata: {
      heading: section,
      source: file.name,
    },
  };
}

export async function mockParseResumeFile(file: File): Promise<ParsedResume> {
  await sleep(780);
  const resumeFile = makeResumeFile(file);
  const baseText = [
    "基本信息：候选人希望寻找前端、全栈或 AI 应用方向的实习与初级岗位。",
    "技能：熟悉 React、TypeScript、JavaScript、Node.js、Python、SQL，了解 Docker 与 RAG 应用开发流程。",
    "项目经历：完成过个人求职决策台、数据看板、AI 辅助分析工具，负责前端交互、状态管理、接口联调和结果可视化。",
    "项目经历：在业务工具中使用 React + TypeScript 搭建模块化组件，优化表单输入、历史记录、分析结果展示和本地持久化。",
    "教育经历：计算机相关背景，持续补充算法、系统设计、工程化与后端接口能力。",
  ].join("\n\n");

  const chunks = [
    makeChunk(resumeFile, 0, "求职目标", "候选人希望寻找前端、全栈或 AI 应用方向的实习与初级岗位，偏好能持续沉淀个人工具和工程能力的团队。"),
    makeChunk(resumeFile, 1, "技能", "熟悉 React、TypeScript、JavaScript、Node.js、Python、SQL，了解 Docker、RAG 检索增强生成和基础后端接口开发。"),
    makeChunk(resumeFile, 2, "项目经历", "个人求职决策台：使用 React + Vite + TypeScript 搭建 JD 分析、投递决策、简历改造建议和历史记录流程，关注表单体验、状态反馈和可维护组件拆分。"),
    makeChunk(resumeFile, 3, "项目经历", "AI 辅助分析工具：参与文本清洗、关键词提取、结果结构化展示和本地持久化，能够把模型输出转成可执行的产品建议。"),
    makeChunk(resumeFile, 4, "教育经历", "计算机相关背景，持续准备算法、系统设计、前端工程化、接口联调与项目表达。"),
  ];

  return {
    file: resumeFile,
    rawText: baseText,
    cleanedText: baseText,
    chunks,
    extractedProfile: {
      skills: SAMPLE_SKILLS.slice(0, 8),
      projects: ["个人求职决策台", "数据看板", "AI 辅助分析工具"],
      education: ["计算机相关背景"],
      experiences: ["前端交互", "接口联调", "文本分析"],
    },
  };
}
