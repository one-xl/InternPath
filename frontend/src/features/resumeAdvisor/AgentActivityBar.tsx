export interface AdvisorActivityView {
  active: boolean;
  title: string;
  detail?: string;
  cacheLabel?: string;
  providerCacheLabel?: string;
  firstTokenMs?: number | null;
}

export function AgentActivityBar({ activity }: { activity: AdvisorActivityView | null }) {
  if (!activity) return null;

  return (
    <div className={`resume-advisor-activity${activity.active ? " active" : ""}`} role="status" aria-live="polite" aria-atomic="true">
      <span className="resume-advisor-activity-pulse" aria-hidden="true" />
      <span className="resume-advisor-activity-copy">
        <strong>{activity.title}</strong>
        {activity.detail && <span>{activity.detail}</span>}
      </span>
      <span className="resume-advisor-activity-meta" aria-label="本轮运行指标">
        {activity.cacheLabel && <span>{activity.cacheLabel}</span>}
        {activity.providerCacheLabel && <span>{activity.providerCacheLabel}</span>}
        {typeof activity.firstTokenMs === "number" && <span>首 token {Math.max(0, activity.firstTokenMs)} ms</span>}
      </span>
    </div>
  );
}
