import { useEffect, useRef } from "react";
import type { AdvisorFact, AdvisorMessage, ResumeSuggestion } from "./types";
import { ResumeSuggestionCard } from "./ResumeSuggestionCard";
import { AgentQuestionCard } from "./AgentQuestionCard";

type QualityGatePayload = {
  quality?: { is_passed?: boolean; score?: number; issues?: unknown };
  target?: { locationLabel?: unknown };
  issue?: unknown;
};

function QualityGateMessage({ message }: { message: AdvisorMessage }) {
  const payload = message.payload as QualityGatePayload;
  const quality = payload.quality;
  const issues = Array.isArray(quality?.issues) ? quality.issues.filter((issue): issue is string => typeof issue === "string" && Boolean(issue.trim())) : [];
  const locationLabel = typeof payload.target?.locationLabel === "string" ? payload.target.locationLabel : "当前段落";
  const issue = typeof payload.issue === "string" ? payload.issue : "本条改写";

  return (
    <article className="resume-advisor-quality-gate" aria-label="本地质量检查结果">
      <h3>这条建议暂不能复制</h3>
      <p>{message.content}</p>
      <dl>
        <div><dt>修改位置</dt><dd>{locationLabel}</dd></div>
        <div><dt>本条目的</dt><dd>{issue}</dd></div>
        {typeof quality?.score === "number" && <div><dt>检查结果</dt><dd>本地质量分：{quality.score} / 100</dd></div>}
      </dl>
      <strong>未通过的规则</strong>
      <ul>{issues.map((reason) => <li key={reason}>{reason}</li>)}</ul>
      <p className="muted">可直接在下方说明想保留的事实、希望缩短的内容或表达偏好，我会据此重新生成。</p>
    </article>
  );
}

function findActiveQuestionId(messages: AdvisorMessage[]): string | null {
  let hasLaterUserMessage = false;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "user") {
      hasLaterUserMessage = true;
      continue;
    }
    if (!hasLaterUserMessage && message.messageKind === "question") return message.id;
  }
  return null;
}

export function ConversationThread({
  messages,
  suggestions,
  onSuggestionAction,
  onFocusSuggestion,
  onQuestionAnswer,
  streamingContent = "",
  facts = [],
}: {
  messages: AdvisorMessage[];
  suggestions: ResumeSuggestion[];
  onSuggestionAction: (id: string, action: "accepted" | "rejected" | "needs_revision" | "applied" | "restore", feedback?: string) => Promise<void>;
  onFocusSuggestion: (suggestion: ResumeSuggestion) => void;
  onQuestionAnswer: (answer: string, remember: boolean) => Promise<void>;
  streamingContent?: string;
  facts?: AdvisorFact[];
}) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const activeQuestionId = findActiveQuestionId(messages);
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages.length, streamingContent.length, suggestions.length]);

  return (
    <section className="resume-advisor-conversation" aria-label="简历顾问对话">
      {messages.map((message) => {
        const quality = (message.payload as QualityGatePayload).quality;
        if (message.messageKind === "question") return <AgentQuestionCard key={message.id} message={message} active={message.id === activeQuestionId} onAnswer={onQuestionAnswer} />;
        if (quality && quality.is_passed === false) return <QualityGateMessage key={message.id} message={message} />;
        return <article key={message.id} className={`resume-advisor-message ${message.role === "user" ? "user" : "assistant"}`}>{message.content}</article>;
      })}
      {suggestions.map((suggestion) => (
        <ResumeSuggestionCard
          key={suggestion.id}
          suggestion={suggestion}
          onAction={(action, feedback) => onSuggestionAction(suggestion.id, action, feedback)}
          onFocus={() => onFocusSuggestion(suggestion)}
          facts={facts}
        />
      ))}
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
