import type { AnalysisResult } from "../../types/analysis";
import { Card } from "../ui/Card";

export function MatchScorePanel({ result }: { result: AnalysisResult }) {
  return (
    <Card title="匹配分析" description="按技能、项目、背景、级别和关键词覆盖拆开看。">
      <div className="dimension-list">
        {(result.dimensions ?? []).map((dimension) => (
          <article key={dimension.id} className="dimension-row">
            <div>
              <strong>{dimension.label}</strong>
              <p>{dimension.explanation}</p>
              <div className="tag-row" style={{ marginTop: "10px" }}>
                {dimension.tags.slice(0, 4).map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            </div>
            <div className="dimension-meter">
              <span>{dimension.score} %</span>
              <div>
                <i style={{ width: `${dimension.score}%` }} />
              </div>
            </div>
          </article>
        ))}
      </div>
    </Card>
  );
}
