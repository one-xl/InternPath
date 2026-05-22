import type { Decision, Priority, RiskLevel } from "../types/analysis";

export function decisionFromScore(score: number): Decision {
  if (score >= 85) return "strong_yes";
  if (score >= 70) return "yes";
  if (score >= 50) return "maybe";
  return "no";
}

export function riskFromScore(score: number): RiskLevel {
  if (score >= 75) return "low";
  if (score >= 50) return "medium";
  return "high";
}

export function priorityFromScore(score: number): Priority {
  if (score >= 85) return "P0";
  if (score >= 70) return "P1";
  if (score >= 50) return "P2";
  return "P3";
}
