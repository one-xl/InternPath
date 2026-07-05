import type { AnalysisResult, HistoryRecord } from "../types/analysis";
import type { CandidateProfile } from "../types/profile";
import type { PageKey } from "../types/navigation";
import { decisionLabels, formatDateTime, statusLabels } from "../utils/format";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";

interface DashboardPageProps {
  records: HistoryRecord[];
  latestResult: AnalysisResult | null;
  profile: CandidateProfile;
  onNewAnalysis: () => void;
  onOpenLatest: () => void;
  onHistory: () => void;
  onNavigate: (page: PageKey) => void;
}

export function DashboardPage({ records, latestResult, profile, onNewAnalysis, onOpenLatest, onHistory, onNavigate }: DashboardPageProps) {
  const safeRecords = records ?? [];

  const appliedCount = safeRecords.filter((record) => record && record.status === "applied").length;
  const interviewCount = safeRecords.filter((record) => record && record.status === "interviewing").length;
  const worthCount = safeRecords.filter((record) => record && (record.decision === "strong_yes" || record.decision === "yes")).length;
  const averageScore = safeRecords.length
    ? Math.round(safeRecords.reduce((sum, record) => sum + (record?.matchScore ?? 0), 0) / safeRecords.length)
    : 0;

  return (
    <div className="page-stack">
      <section className="dashboard-hero">
        <div>
          <span className="section-kicker">当前阶段</span>
          <h2>从岗位判断开始，而不是从焦虑开始。</h2>
          <p>先判断是否值得投，再决定怎么改简历、补项目并准备面试。</p>
        </div>
        <Button variant="primary" onClick={onNewAnalysis}>新建岗位分析</Button>
      </section>

      <section className="workflow-guide-panel">
        <div className="workflow-guide-header">
          <h3 className="workflow-guide-title">InternPath 求职五步流程</h3>
          <p className="workflow-guide-subtitle">第一次使用？按这条路径完成岗位判断、简历修改和投递复盘</p>
        </div>
        <div className="workflow-grid">
          <div className="workflow-card" onClick={() => onNavigate("settings")}>
            <span className="workflow-step-num">01 服务连通</span>
            <h4 className="workflow-step-title">服务连通</h4>
            <p className="workflow-step-desc">先确认分析与生成服务可用，后续流程才会稳定出结果。</p>
          </div>
          <div className="workflow-card" onClick={() => onNavigate("profile")}>
            <span className="workflow-step-num">02 导入简历</span>
            <h4 className="workflow-step-title">个人材料</h4>
            <p className="workflow-step-desc">在「个人材料」中上传并解析简历，生成结构化画像。</p>
          </div>
          <div className="workflow-card" onClick={() => onNavigate("new")}>
            <span className="workflow-step-num">03 投递决策</span>
            <h4 className="workflow-step-title">投递决策</h4>
            <p className="workflow-step-desc">点击「新建岗位分析」按钮，输入岗位 JD，得到匹配度判断和待补强项。</p>
          </div>
          <div className="workflow-card" onClick={() => onNavigate("agent-resume")}>
            <span className="workflow-step-num">04 定向优化</span>
            <h4 className="workflow-step-title">定向优化</h4>
            <p className="workflow-step-desc">进入「简历定向优化」，调整简历段落，下载 DOCX 简历和修改对照表。</p>
          </div>
          <div className="workflow-card" onClick={() => onNavigate("history")}>
            <span className="workflow-step-num">05 求职归档</span>
            <h4 className="workflow-step-title">求职归档</h4>
            <p className="workflow-step-desc">在「历史记录」中跟进投递状态（已投递、面试中），沉淀个人岗位库。</p>
          </div>
        </div>
      </section>

      <div className="stats-grid">
        <Card><strong>{safeRecords.length}</strong><span>历史分析</span></Card>
        <Card><strong>{worthCount}</strong><span>建议投递</span></Card>
        <Card><strong>{appliedCount}</strong><span>已投递</span></Card>
        <Card><strong>{interviewCount}</strong><span>面试中</span></Card>
        <Card><strong>{averageScore}</strong><span>平均匹配度</span></Card>
      </div>

      <div className="dashboard-grid">
        <Card
          title="最近一次岗位分析"
          description="结果会在这里沉淀成下一步行动。"
          action={latestResult ? <Button onClick={onOpenLatest}>查看结果</Button> : null}
        >
          {latestResult ? (
            <div className="latest-summary">
              <h3>{latestResult.draft?.company || "未知公司"} · {latestResult.draft?.title || "未命名岗位"}</h3>
              <p>{latestResult.oneLineReason || "无摘要说明"}</p>
              <div className="summary-line">
                <strong>{latestResult.matchScore ?? 0}</strong>
                <span>{latestResult.decision ? (decisionLabels[latestResult.decision] || latestResult.decision) : "未知决策"}</span>
                <span>{latestResult.createdAt ? formatDateTime(latestResult.createdAt) : ""}</span>
              </div>
            </div>
          ) : (
            <EmptyState title="还没有分析结果" description="创建一次岗位分析后，最近摘要会出现在这里。" actionLabel="开始分析" onAction={onNewAnalysis} />
          )}
        </Card>

        <Card title="推荐下一步行动" description="让工作台每天都有一个明确出口。">
          <ol className="action-list">
            <li>维护 Profile：当前目标是 {profile?.targetRole || "未设置"}</li>
            <li>选择一个新 JD，先跑投递决策</li>
            <li>把高优先级简历建议改到简历里</li>
            <li>在历史记录中更新投递状态，持续复盘方向</li>
          </ol>
        </Card>
      </div>

      <Card title="最近历史" action={<Button onClick={onHistory}>全部历史</Button>}>
        {safeRecords.slice(0, 4).length ? (
          <div className="compact-history">
            {safeRecords.slice(0, 4).map((record) => {
              if (!record) return null;
              return (
                <div key={record.id}>
                  <strong>{record.draft?.company || "未知公司"} · {record.draft?.title || "未命名岗位"}</strong>
                  <span>
                    {record.matchScore ?? 0} · {record.decision ? (decisionLabels[record.decision] || record.decision) : "未知决策"} · {record.status ? (statusLabels[record.status] || record.status) : "未知状态"}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="muted">暂无历史记录。</p>
        )}
      </Card>
    </div>
  );
}
