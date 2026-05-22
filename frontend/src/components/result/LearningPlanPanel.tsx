import type { LearningSuggestion } from "../../types/analysis";

export function LearningPlanPanel({ suggestions }: { suggestions: LearningSuggestion[] }) {
  if (!suggestions || suggestions.length === 0) return null;
  return (
    <details className="learning-details">
      <summary>学习路线与技能强攻建议 ({suggestions.length} 阶段)</summary>
      <div className="timeline">
        {suggestions.map((item) => (
          <article key={item.id}>
            <span>{item.order}</span>
            <div>
              <h3>{item.skill}</h3>
              <p>
                <strong>预计用时：</strong>{item.estimatedTime} &nbsp;·&nbsp; <strong>实战方向：</strong>{item.practiceDirection}
              </p>
              <small>面试焦点：{item.interviewFocus}</small>
            </div>
          </article>
        ))}
      </div>
    </details>
  );
}
