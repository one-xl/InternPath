import { useState, type KeyboardEvent } from "react";

export function MessageComposer({ onSend, disabled }: { onSend: (content: string) => Promise<void>; disabled: boolean }) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!value.trim() || sending) return;
    setSending(true);
    setError("");
    try {
      await onSend(value.trim());
      setValue("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "消息发送失败，请重试。");
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void submit();
  }

  return (
    <div className="resume-advisor-composer" aria-label="对话输入框">
      <textarea aria-label="输入消息" value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={onKeyDown} disabled={disabled || sending} placeholder="补充事实、说明偏好，或追问为什么这样改" rows={2} />
      <button type="button" className="primary" onClick={() => void submit()} disabled={disabled || sending || !value.trim()}>{sending ? "发送中…" : "发送"}</button>
      {error && <p className="resume-advisor-composer-error" role="alert">{error}</p>}
    </div>
  );
}
