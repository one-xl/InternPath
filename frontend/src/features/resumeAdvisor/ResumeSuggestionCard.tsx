import { useState } from "react";
import { copyText } from "./copyText";
import type { AdvisorFact, ResumeSuggestion } from "./types";

export function ResumeSuggestionCard({
  suggestion,
  onAction,
  onFocus,
  facts = [],
}: {
  suggestion: ResumeSuggestion;
  onAction: (action: "accepted" | "rejected" | "needs_revision" | "applied" | "restore", feedback?: string) => Promise<void>;
  onFocus: () => void;
  facts?: AdvisorFact[];
}) {
  const [notice, setNotice] = useState("");
  const copyable = suggestion.factStatus === "supported" && ["accepted", "applied"].includes(suggestion.status);
  const supportingFacts = facts.filter((fact) => (suggestion.userFactIds || []).includes(fact.id));

  async function copySuggestion() {
    try {
      await copyText(suggestion.copyText);
      setNotice("已复制本条建议。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "复制失败，请手动复制。");
    }
  }

  return (
    <article className="resume-advisor-suggestion">
      <div className="resume-advisor-suggestion-head">
        <span className={`priority ${suggestion.priority}`}>{suggestion.priority === "high" ? "高优先级" : "建议"}</span>
        <button type="button" className="link-button" onClick={onFocus}>定位原文</button>
      </div>
      <h3>{suggestion.issue}</h3>
      <p className="muted">{suggestion.target.locationLabel}{suggestion.target.locatorConfidence === "approximate" ? " · 近似定位" : ""}</p>
      <div className="resume-advisor-original"><small>原文</small>{suggestion.originalText}</div>
      <div className="resume-advisor-proposed"><small>建议粘贴内容</small>{suggestion.proposedText}</div>
      <p>{suggestion.rationale}</p>
      {suggestion.factIssues.length > 0 && <p className="resume-advisor-warning">需要补充证据：{suggestion.factIssues.join("；")}</p>}
      <div className="resume-advisor-actions">
        {suggestion.status === "proposed" && <button type="button" onClick={() => void onAction("accepted")}>采用</button>}
        {suggestion.status === "proposed" && <button type="button" onClick={() => void onAction("rejected")}>保留原文</button>}
        {suggestion.status !== "rejected" && suggestion.status !== "applied" && <button type="button" onClick={() => void onAction("needs_revision", "请改短一点，保留所有可核验事实。")}>改短一点</button>}
        {suggestion.status !== "rejected" && suggestion.status !== "applied" && <button type="button" onClick={() => void onAction("needs_revision", "请使用更克制的表达，不强化角色或结果。")}>更克制</button>}
        {suggestion.status !== "rejected" && suggestion.status !== "applied" && <button type="button" onClick={() => void onAction("needs_revision", "请仅在已有真实证据允许时补充量化表达，否则保留非量化表述。")}>真实证据下量化</button>}
        {suggestion.status === "accepted" && <button type="button" onClick={() => void onAction("applied")}>我已粘贴</button>}
        {suggestion.version > 1 && <button type="button" onClick={() => void onAction("restore")}>恢复此版本</button>}
        <button type="button" disabled={!copyable} onClick={() => void copySuggestion}>复制本条</button>
      </div>
      <details className="resume-advisor-evidence">
        <summary>查看依据</summary>
        <p>简历证据：{suggestion.resumeEvidenceBlockIds.join("、") || "无"}</p>
        <p>JD 要求：{suggestion.jdRequirementIds.join("、") || "无"}</p>
        {supportingFacts.length > 0 && <p>用户补充：{supportingFacts.map((fact) => fact.claimValue).join("；")}</p>}
      </details>
      <p className="resume-advisor-status">状态：{suggestion.status}</p>
      <p className="sr-only" aria-live="polite">{notice}</p>
    </article>
  );
}
