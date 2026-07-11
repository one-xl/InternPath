import { useState } from "react";
import type { AdvisorMessage } from "./types";

export function AgentQuestionCard({ message, onAnswer }: { message: AdvisorMessage; onAnswer: (answer: string, remember: boolean) => Promise<void> }) {
  const payload = message.payload as { why?: string; target?: string; evidenceTypes?: string[]; questionKey?: string };
  const label = String(payload.questionKey || "这项经历").replace(/^requirement:/, "");
  const [remember, setRemember] = useState(false);
  return (
    <article className="resume-advisor-question">
      <p className="resume-advisor-message assistant">{message.content}</p>
      <p><strong>为什么需要：</strong>{payload.why || "需要先确认事实，才能避免写入不真实的声明。"}</p>
      <p><strong>会影响：</strong>{payload.target || "下一条建议"}</p>
      {payload.evidenceTypes?.length ? <p><strong>可以提供：</strong>{payload.evidenceTypes.join("、")}</p> : null}
      <div className="resume-advisor-actions">
        <button type="button" onClick={() => void onAnswer(`没有 ${label} 相关真实经历。`, remember)}>没有这项经历</button>
        <button type="button" onClick={() => void onAnswer(`跳过 ${label}，暂不补充。`, remember)}>跳过</button>
      </div>
      <label className="resume-advisor-remember">
        <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
        将本次回答保存为长期事实
      </label>
    </article>
  );
}
