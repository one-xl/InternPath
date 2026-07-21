import { useEffect, useRef } from "react";
import type { AdvisorFact, AdvisorMessage, ResumeSuggestion } from "./types";

type PayloadRecord = Record<string, unknown>;

type QualityReview = {
  critique: string | null;
  suggestions: string[];
  issues: string[];
  dimensions: ReviewDimension[];
  score: number | null;
  reviewer: string | null;
  locationLabel: string | null;
  issue: string | null;
};

type ReviewDimension = {
  label: string;
  verdict: string | null;
  rationale: string | null;
  evidence: string[];
};

function asRecord(value: unknown): PayloadRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as PayloadRecord : null;
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function textItems(value: unknown): string[] {
  if (typeof value === "string") return asText(value) ? [value.trim()] : [];
  if (!Array.isArray(value)) return [];

  return value.flatMap((item) => {
    const text = asText(item);
    if (text) return [text];
    const record = asRecord(item);
    return record ? textItems(record.text ?? record.message ?? record.detail ?? record.issue) : [];
  });
}

function uniqueText(items: string[]): string[] {
  return [...new Set(items)];
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    const text = asText(value);
    if (text) return text;
  }
  return null;
}

function reviewDimension(value: unknown, fallbackLabel: string): ReviewDimension | null {
  const record = asRecord(value);
  if (!record) return null;
  const verdict = firstText(record.verdict, record.status);
  const rationale = firstText(record.rationale, record.critique, record.explanation, record.detail);
  const evidence = uniqueText(textItems(record.evidence_basis ?? record.evidenceBasis ?? record.evidence));
  if (!verdict && !rationale && evidence.length === 0) return null;

  return {
    label: firstText(record.label, record.name, record.dimension, record.id) || fallbackLabel,
    verdict,
    rationale,
    evidence,
  };
}

function reviewDimensions(review: PayloadRecord): ReviewDimension[] {
  const reservedKeys = new Set(["score", "is_passed", "critique", "suggestions", "issues", "reviewer", "dimensions"]);
  const namedDimensions = Object.entries(review)
    .filter(([key]) => !reservedKeys.has(key))
    .flatMap(([key, value]) => {
      const dimension = reviewDimension(value, key);
      return dimension ? [dimension] : [];
    });
  const listedDimensions = Array.isArray(review.dimensions)
    ? review.dimensions.flatMap((value, index) => {
      const dimension = reviewDimension(value, `维度 ${index + 1}`);
      return dimension ? [dimension] : [];
    })
    : Object.entries(asRecord(review.dimensions) || {}).flatMap(([label, value]) => {
      const dimension = reviewDimension(value, label);
      return dimension ? [dimension] : [];
    });

  return [...namedDimensions, ...listedDimensions];
}

function getQualityReview(message: AdvisorMessage): QualityReview {
  const payload = asRecord(message.payload) || {};
  const quality = asRecord(payload.quality) || {};
  const nestedReview = asRecord(quality.hr_review) || asRecord(quality.review) || asRecord(payload.hr_review) || asRecord(payload.review) || {};
  const target = asRecord(payload.target) || {};
  const critique = firstText(quality.critique, nestedReview.critique, payload.critique);
  const suggestions = uniqueText([
    ...textItems(quality.suggestions),
    ...textItems(nestedReview.suggestions),
    ...textItems(payload.suggestions),
  ]);
  const issues = uniqueText([
    ...textItems(quality.issues),
    ...textItems(nestedReview.issues),
    ...textItems(payload.issues),
  ]).filter((item) => item !== critique);

  return {
    critique,
    suggestions,
    issues,
    dimensions: reviewDimensions(nestedReview),
    score: typeof quality.score === "number" && Number.isFinite(quality.score)
      ? quality.score
      : typeof nestedReview.score === "number" && Number.isFinite(nestedReview.score) ? nestedReview.score : null,
    reviewer: firstText(quality.reviewer, nestedReview.reviewer, payload.reviewer),
    locationLabel: firstText(target.locationLabel, payload.locationLabel),
    issue: firstText(payload.issue, target.issue),
  };
}

function isQualityRejection(message: AdvisorMessage): boolean {
  const payload = asRecord(message.payload) || {};
  const quality = asRecord(payload.quality);
  return quality?.is_passed === false || payload.errorCode === "quality_gate_failed";
}

function QualityGateMessage({ message }: { message: AdvisorMessage }) {
  const review = getQualityReview(message);
  const content = asText(message.content);
  const hasReview = Boolean(
    content
    || review.reviewer
    || review.score !== null
    || review.locationLabel
    || review.issue
    || review.critique
    || review.suggestions.length
    || review.issues.length
    || review.dimensions.length,
  );

  if (!hasReview) return <MachineStatusMessage message={message} />;

  return (
    <article className="resume-advisor-quality-gate" aria-label="审查结果">
      {content && <p className="resume-advisor-message assistant">{content}</p>}
      {(review.reviewer || review.score !== null || review.locationLabel || review.issue) && (
        <dl>
          {review.reviewer && <div><dt>审查来源</dt><dd>{review.reviewer}</dd></div>}
          {review.score !== null && <div><dt>评分</dt><dd>{review.score} / 100</dd></div>}
          {review.locationLabel && <div><dt>修改位置</dt><dd>{review.locationLabel}</dd></div>}
          {review.issue && <div><dt>改写目标</dt><dd>{review.issue}</dd></div>}
        </dl>
      )}
      {review.critique && <section><h3>审查意见</h3><p>{review.critique}</p></section>}
      {review.suggestions.length > 0 && (
        <section>
          <h3>改进建议</h3>
          <ul>{review.suggestions.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}</ul>
        </section>
      )}
      {review.issues.length > 0 && (
        <section>
          <h3>问题</h3>
          <ul>{review.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
        </section>
      )}
      {review.dimensions.length > 0 && (
        <section>
          <h3>维度评估</h3>
          <dl>
            {review.dimensions.map((dimension) => (
              <div key={dimension.label}>
                <dt>{dimension.label}{dimension.verdict ? `：${dimension.verdict}` : ""}</dt>
                {dimension.rationale && <dd>{dimension.rationale}</dd>}
                {dimension.evidence.length > 0 && <dd>{dimension.evidence.join("；")}</dd>}
              </div>
            ))}
          </dl>
        </section>
      )}
    </article>
  );
}

function MachineStatusMessage({ message }: { message: AdvisorMessage }) {
  const payload = asRecord(message.payload) || {};
  const entries = [
    ["阶段", asText(payload.mode)],
    ["状态", asText(payload.modelStatus) || asText(payload.status)],
    ["代码", asText(payload.errorCode)],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]));

  if (!entries.length) return null;

  return (
    <aside className="resume-advisor-status" aria-label="处理状态">
      <dl>{entries.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </aside>
  );
}

function orderMessagesBySequence(messages: AdvisorMessage[]): AdvisorMessage[] {
  return messages
    .map((message, index) => ({ message, index }))
    .sort((left, right) => {
      const leftSequence = Number.isFinite(left.message.sequence) ? left.message.sequence : null;
      const rightSequence = Number.isFinite(right.message.sequence) ? right.message.sequence : null;
      if (leftSequence !== null && rightSequence !== null) return leftSequence - rightSequence || left.index - right.index;
      if (leftSequence !== null) return -1;
      if (rightSequence !== null) return 1;
      return left.index - right.index;
    })
    .map(({ message }) => message);
}

function renderMessage(message: AdvisorMessage) {
  const content = asText(message.content);
  if (content) {
    return <article className={`resume-advisor-message ${message.role === "user" ? "user" : "assistant"}`}>{content}</article>;
  }
  if (isQualityRejection(message) || message.messageKind === "error" || message.messageKind === "completion") {
    return <MachineStatusMessage message={message} />;
  }
  return null;
}

export function ConversationThread({
  messages,
  suggestions: _legacySuggestions,
  onSuggestionAction: _legacyOnSuggestionAction,
  onFocusSuggestion: _legacyOnFocusSuggestion,
  onQuestionAnswer: _onQuestionAnswer,
  streamingContent = "",
  facts = [],
}: {
  messages: AdvisorMessage[];
  /** @deprecated Suggestions are intentionally rendered in SuggestionWorkspace. */
  suggestions?: ResumeSuggestion[];
  /** @deprecated Suggestions are intentionally rendered in SuggestionWorkspace. */
  onSuggestionAction?: (id: string, action: "accepted" | "rejected" | "needs_revision" | "applied" | "restore", feedback?: string) => Promise<void>;
  /** @deprecated Suggestions are intentionally rendered in SuggestionWorkspace. */
  onFocusSuggestion?: (suggestion: ResumeSuggestion) => void;
  onQuestionAnswer?: (answer: string, remember: boolean) => Promise<void>;
  streamingContent?: string;
  facts?: AdvisorFact[];
}) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const orderedMessages = orderMessagesBySequence(messages);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages.length, streamingContent.length]);

  return (
    <section className="resume-advisor-conversation" aria-label="简历顾问对话">
      {orderedMessages.map((message) => <div key={message.id}>{renderMessage(message)}</div>)}
      {streamingContent && (
        <article className="resume-advisor-message assistant streaming" aria-label="模型正在流式回复" aria-live="off">
          {streamingContent}<span className="resume-advisor-stream-caret" aria-hidden="true" />
        </article>
      )}
      {facts.length > 0 && (
        <details className="resume-advisor-evidence">
          <summary>已记录事实</summary>
          <ul>
            {facts.map((fact) => (
              <li key={fact.id}>{fact.status === "denied" ? "明确不存在" : "已确认"} · {fact.claimValue}{fact.scope === "global" ? " · 长期" : " · 本次会话"}</li>
            ))}
          </ul>
        </details>
      )}
      {!messages.length && <p className="muted">选择简历并粘贴 JD 后开始一轮可核验的逐段优化。</p>}
      <div ref={bottomRef} />
    </section>
  );
}
