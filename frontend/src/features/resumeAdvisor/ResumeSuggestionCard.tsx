import { useState } from "react";
import { ResumeDiffView } from "../../components/resume/ResumeDiffView";
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
  const [revisionFeedback, setRevisionFeedback] = useState("");
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

  async function requestRevision() {
    const feedback = revisionFeedback.trim();
    if (!feedback) return;
    await onAction("needs_revision", feedback);
    setRevisionFeedback("");
  }

  return (
    <article className="resume-advisor-suggestion">
      <div className="resume-advisor-suggestion-head">
        <span className={`priority ${suggestion.priority}`}>{suggestion.priority === "high" ? "高优先级" : "建议"}</span>
        <button type="button" className="link-button" onClick={onFocus}>定位原文</button>
      </div>
      <h3>{suggestion.issue}</h3>
      <p className="muted">{suggestion.target.locationLabel}{suggestion.target.locatorConfidence === "approximate" ? " · 近似定位" : ""}</p>
      <ResumeDiffView
        modificationLog={[{
          id: suggestion.id,
          section_name: suggestion.target.sectionName,
          section_index: suggestion.version,
          original: suggestion.originalText,
          new: suggestion.proposedText,
          reason: suggestion.target.locationLabel,
          locationLabel: suggestion.target.locationLabel,
        }]}
      />
      <p>{suggestion.rationale}</p>
      {suggestion.factIssues.length > 0 && <p className="resume-advisor-warning">需要补充证据：{suggestion.factIssues.join("；")}</p>}
      <div className="resume-advisor-actions">
        {suggestion.status === "proposed" && <button type="button" onClick={() => void onAction("accepted")}>采用</button>}
        {suggestion.status === "proposed" && <button type="button" onClick={() => void onAction("rejected")}>保留原文</button>}
        {suggestion.status === "accepted" && <button type="button" onClick={() => void onAction("applied")}>我已粘贴</button>}
        {suggestion.version > 1 && <button type="button" onClick={() => void onAction("restore")}>恢复此版本</button>}
        <button type="button" disabled={!copyable} onClick={() => void copySuggestion}>复制本条</button>
      </div>
      {suggestion.status !== "rejected" && suggestion.status !== "applied" && (
        <div className="resume-advisor-revision-request">
          <label>
            修改要求
            <textarea
              aria-label="修改要求"
              value={revisionFeedback}
              onChange={(event) => setRevisionFeedback(event.target.value)}
              placeholder="输入希望保留或调整的内容"
              rows={2}
            />
          </label>
          <button type="button" disabled={!revisionFeedback.trim()} onClick={() => void requestRevision()}>请求修改</button>
        </div>
      )}
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
