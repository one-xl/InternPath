import type { AdvisorSloDashboard } from "./types";

const METRIC_LABELS: Record<string, string> = {
  queueMs: "队列 P95",
  providerFirstTokenMs: "Provider P95",
  endToEndFirstTokenMs: "端到端 P95",
};

export function AdvisorSloPanel({ dashboard }: { dashboard: AdvisorSloDashboard | null }) {
  if (!dashboard) return null;
  const metricEntries = Object.entries(dashboard.metrics).filter(([, metric]) => metric.p95Ms !== null);

  return (
    <aside className={`resume-advisor-slo${dashboard.alerts.length ? " warning" : ""}`} aria-label="简历顾问服务等级指标">
      <span className="resume-advisor-slo-title">24h SLO</span>
      {metricEntries.map(([name, metric]) => (
        <span key={name}>{METRIC_LABELS[name] || name} {metric.p95Ms} / {metric.thresholdMs} ms</span>
      ))}
      {dashboard.alerts.length > 0 && <span className="resume-advisor-slo-alert">告警 {dashboard.alerts.length}</span>}
    </aside>
  );
}
