import type { ApplicationStatus, Decision, Priority, RiskLevel } from "../types/analysis";
import type { JobLevel, WorkMode } from "../types/job";

export const decisionLabels: Record<Decision, string> = {
  strong_yes: "强烈建议投",
  yes: "可以投",
  maybe: "谨慎投",
  no: "不建议投",
};

export const riskLabels: Record<RiskLevel, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
};

export const priorityLabels: Record<Priority, string> = {
  P0: "P0 立即处理",
  P1: "P1 本周处理",
  P2: "P2 备选观察",
  P3: "P3 暂不投入",
};

export const statusLabels: Record<ApplicationStatus, string> = {
  watching: "观察中",
  applied: "已投递",
  rejected: "已拒绝",
  interviewing: "面试中",
  abandoned: "已放弃",
  pending: "排队中",
  processing: "分析中",
  failed: "分析失败",
};

export const workModeLabels: Record<WorkMode, string> = {
  remote: "远程",
  onsite: "现场",
  hybrid: "混合",
  unknown: "未注明",
};

export const levelLabels: Record<JobLevel, string> = {
  intern: "实习",
  campus: "校招",
  junior: "初级",
  middle: "中级",
  unknown: "未注明",
};

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function clampScore(score: number): number {
  return Math.max(0, Math.min(100, Math.round(score)));
}
