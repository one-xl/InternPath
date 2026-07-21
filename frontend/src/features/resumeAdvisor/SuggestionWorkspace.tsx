import { ResumeSuggestionCard } from "./ResumeSuggestionCard";
import type { AdvisorFact, ResumeSuggestion } from "./types";

const VISIBLE_STATUSES = new Set(["proposed", "accepted", "needs_revision"]);

export function SuggestionWorkspace({
  suggestions,
  onSuggestionAction,
  onFocusSuggestion,
  facts,
}: {
  suggestions: ResumeSuggestion[];
  onSuggestionAction: (id: string, action: "accepted" | "rejected" | "needs_revision" | "applied" | "restore", feedback?: string) => Promise<void>;
  onFocusSuggestion: (suggestion: ResumeSuggestion) => void;
  facts: AdvisorFact[];
}) {
  const activeSuggestions = suggestions.filter((suggestion) => VISIBLE_STATUSES.has(suggestion.status));

  return (
    <aside className="resume-advisor-workspace" aria-label="修改建议工作区">
      <div className="resume-advisor-workspace-head">
        <h2>修改建议工作区</h2>
        <p>已通过证据与质量校验的建议在这里处理，不会混入多智能体对话。</p>
      </div>
      <div className="resume-advisor-workspace-list">
        {activeSuggestions.map((suggestion) => (
          <ResumeSuggestionCard
            key={suggestion.id}
            suggestion={suggestion}
            onAction={(action, feedback) => onSuggestionAction(suggestion.id, action, feedback)}
            onFocus={() => onFocusSuggestion(suggestion)}
            facts={facts}
          />
        ))}
        {!activeSuggestions.length && <p className="muted">等待通过核验的有效建议。</p>}
      </div>
    </aside>
  );
}
