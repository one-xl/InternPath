import { useState } from "react";
import type { AdvisorMessage } from "./types";

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function textItems(value: unknown): string[] {
  return Array.isArray(value)
    ? value.flatMap((item) => {
      const text = asText(item);
      return text ? [text] : [];
    })
    : [];
}

export function AgentQuestionCard({
  message,
  onAnswer,
  active = true,
}: {
  message: AdvisorMessage;
  onAnswer: (answer: string, remember: boolean) => Promise<void>;
  active?: boolean;
}) {
  const payload = message.payload as { why?: unknown; target?: unknown; evidenceTypes?: unknown; questionKey?: unknown };
  const content = asText(message.content);
  const questionKey = asText(payload.questionKey)?.replace(/^(?:requirement|fact):/, "") || null;
  const why = asText(payload.why);
  const target = asText(payload.target);
  const evidenceTypes = textItems(payload.evidenceTypes);
  const [answer, setAnswer] = useState("");
  const [remember, setRemember] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState("");

  async function submitAnswer(content: string) {
    const value = content.trim();
    if (!active || !value || submitting || submitted) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      await onAnswer(value, remember);
      setSubmitted(true);
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : "提交失败，请重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <article className="resume-advisor-question">
      {content && <p className="resume-advisor-message assistant">{content}</p>}
      {!active && <p className="muted" role="status">已回答 / 已失效</p>}
      {active && submitted && <p className="muted" role="status">已提交，正在继续分析。</p>}
      {!active || submitted ? null : (
        <>
          {(questionKey || why || target || evidenceTypes.length > 0) && (
            <dl className="resume-advisor-question-context">
              {questionKey && <div><dt>待补充事项</dt><dd>{questionKey}</dd></div>}
              {why && <div><dt>依据要求</dt><dd>{why}</dd></div>}
              {target && <div><dt>关联位置</dt><dd>{target}</dd></div>}
              {evidenceTypes.length > 0 && <div><dt>可提供材料</dt><dd>{evidenceTypes.join("、")}</dd></div>}
            </dl>
          )}
          <label>
            补充真实证据
            <textarea
              aria-label="补充真实证据"
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              disabled={submitting}
              placeholder="填写实际职责、技术选择、结果或可核验数据"
              rows={3}
            />
          </label>
          <div className="resume-advisor-actions">
            <button type="button" disabled={submitting || !answer.trim()} onClick={() => void submitAnswer(answer)}>{submitting ? "提交中…" : "提交事实"}</button>
          </div>
          <label className="resume-advisor-remember">
            <input type="checkbox" checked={remember} disabled={submitting} onChange={(event) => setRemember(event.target.checked)} />
            将本次回答保存为长期事实
          </label>
          {submitError && <p className="resume-advisor-warning" role="alert">{submitError}</p>}
        </>
      )}
    </article>
  );
}
