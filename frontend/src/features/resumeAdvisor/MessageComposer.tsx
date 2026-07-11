import { useState } from "react";

export function MessageComposer({ onSend, disabled }: { onSend: (content: string) => Promise<void>; disabled: boolean }) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);

  async function submit() {
    if (!value.trim() || sending) return;
    setSending(true);
    try {
      await onSend(value.trim());
      setValue("");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="resume-advisor-composer">
      <textarea value={value} onChange={(event) => setValue(event.target.value)} disabled={disabled || sending} placeholder="补充事实、说明偏好，或追问为什么这样改" rows={2} />
      <button type="button" className="primary" onClick={() => void submit()} disabled={disabled || sending || !value.trim()}>{sending ? "发送中…" : "发送"}</button>
    </div>
  );
}
