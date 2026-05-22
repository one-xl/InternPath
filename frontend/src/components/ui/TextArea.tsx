import type { TextareaHTMLAttributes } from "react";

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  helper?: string;
}

export function TextArea({ label, helper, value, ...props }: TextAreaProps) {
  const count = typeof value === "string" ? value.length : 0;
  return (
    <label className="field">
      <span>
        {label}
        <small>{count} 字</small>
      </span>
      <textarea value={value} {...props} />
      {helper && <em>{helper}</em>}
    </label>
  );
}
