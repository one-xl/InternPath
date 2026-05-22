import type { AnalysisResult } from "../../types/analysis";
import { decisionLabels, priorityLabels, riskLabels } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

const decisionTone = {
  strong_yes: "success",
  yes: "info",
  maybe: "warning",
  no: "danger",
} as const;

export function DecisionCard({ result }: { result: AnalysisResult }) {
  return (
    <Card className={`decision-card decision-${result.decision}`}>
      <div className="decision-layout">
        <div>
          <span className="section-kicker">投递决策</span>
          <h2>{decisionLabels[result.decision]}</h2>
          <p>{result.oneLineReason}</p>
          <div className="badge-row">
            <Badge tone={decisionTone[result.decision]}>{riskLabels[result.riskLevel]}</Badge>
            <Badge tone="neutral">{priorityLabels[result.priority]}</Badge>
          </div>
        </div>
        <div className="score-ring" aria-label={`匹配度 ${result.matchScore}`}>
          <strong>{result.matchScore}</strong>
          <span>match</span>
        </div>
      </div>

      <div className="decision-details-grid">
        <div className="decision-pros">
          <h4>已备核心优势</h4>
          <div className="pros-tags">
            {result.detectedKeywords && result.detectedKeywords.length > 0 ? (
              result.detectedKeywords.map((tag) => (
                <span key={tag} className="pro-tag">{tag}</span>
              ))
            ) : (
              <span className="neutral-tag">未识别到匹配核心词</span>
            )}
          </div>
        </div>
        <div className="decision-cons">
          <h4>潜在挑战与缺口</h4>
          <div className="cons-tags">
            {result.missingKeywords && result.missingKeywords.length > 0 ? (
              result.missingKeywords.map((tag) => (
                <span key={tag} className="con-tag">{tag}</span>
              ))
            ) : (
              <span className="neutral-tag">无显著技术/业务壁垒</span>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
