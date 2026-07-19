import { useState } from "react";
import type { AdvisorMessage } from "./types";

export function AgentQuestionCard({
  message,
  onAnswer,
  active = true,
}: {
  message: AdvisorMessage;
  onAnswer: (answer: string, remember: boolean) => Promise<void>;
  active?: boolean;
}) {
  const payload = message.payload as { why?: string; target?: string; evidenceTypes?: string[]; questionKey?: string };
  const label = String(payload.questionKey || "这项经历").replace(/^requirement:/, "");
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
      <p className="resume-advisor-message assistant">{message.content}</p>
      {!active && <p className="muted" role="status">已回答 / 已失效</p>}
      {active && submitted && <p className="muted" role="status">已提交，正在继续分析。</p>}
      {!active || submitted ? null : (
        <>
          <p><strong>为什么需要：</strong>{payload.why || "需要先确认事实，才能避免写入不真实的声明。"}</p>
          <p><strong>会影响：</strong>{payload.target || "下一条建议"}</p>
          {payload.evidenceTypes?.length ? <p><strong>可以提供：</strong>{payload.evidenceTypes.join("、")}</p> : null}
          <div className="resume-advisor-actions">
            <button type="button" disabled={submitting} onClick={() => void submitAnswer(`没有 ${label} 相关真实经历。`)}>没有这项经历</button>
            <button type="button" disabled={submitting} onClick={() => void submitAnswer(`跳过 ${label}，暂不补充。`)}>跳过</button>
          </div>
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
