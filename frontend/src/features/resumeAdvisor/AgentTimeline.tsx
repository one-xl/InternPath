import { useMemo } from "react";
import type { AdvisorEvent } from "./types";

const AGENT_LABELS: Record<string, string> = {
  job_decoder: "岗位解码 Agent",
  resume_rag_retriever: "证据检索 Agent",
  resume_copywriter: "简历改写 Agent",
  fact_verifier: "事实核验 Agent",
  hr_critic: "HR 审查 Agent",
};

function text(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value.trim() : "";
}

function timelineEntry(event: AdvisorEvent): { agent: string; detail: string; status: "running" | "done" } | null {
  const payload = event.payload || {};
  const agentId = text(payload, "agent");
  if (!agentId || !AGENT_LABELS[agentId]) return null;
  if (event.type === "progress") {
    return { agent: AGENT_LABELS[agentId], detail: text(payload, "summary") || "已进入该阶段。", status: "running" };
  }
  if (event.type === "tool_call") {
    return { agent: AGENT_LABELS[agentId], detail: `正在执行 ${text(payload, "toolName") || "核验工具"}。`, status: "running" };
  }
  if (event.type === "tool_result") {
    return { agent: AGENT_LABELS[agentId], detail: `${text(payload, "toolName") || "核验工具"}${payload.ok === true ? "已完成" : "未完成"}。`, status: payload.ok === true ? "done" : "running" };
  }
  return null;
}

export function AgentTimeline({ events }: { events: AdvisorEvent[] }) {
  const entries = useMemo(() => events
    .slice()
    .sort((left, right) => left.sequence - right.sequence)
    .flatMap((event) => {
      const entry = timelineEntry(event);
      return entry ? [{ ...entry, id: event.id }] : [];
    }), [events]);

  return (
    <section className="resume-advisor-agent-timeline" aria-label="多智能体执行记录">
      <div className="resume-advisor-agent-timeline-head">
        <h2>多智能体执行记录</h2>
        <span>持久化阶段，不伪装成聊天消息</span>
      </div>
      {entries.length > 0 ? (
        <ol>
          {entries.map((entry) => (
            <li key={entry.id} className={entry.status}>
              <strong>{entry.agent}</strong>
              <span>{entry.detail}</span>
              <small>{entry.status === "done" ? "已完成" : "处理中"}</small>
            </li>
          ))}
        </ol>
      ) : <p className="muted">开始分析后，这里会展示岗位解码、检索、事实核验和 HR 审查的真实阶段。</p>}
    </section>
  );
}
