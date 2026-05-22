import { TextArea } from "../ui/TextArea";

interface JDTextAreaProps {
  value: string;
  onChange: (value: string) => void;
}

export function JDTextArea({ value, onChange }: JDTextAreaProps) {
  return (
    <TextArea
      label="完整 JD"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      rows={12}
      placeholder="粘贴岗位职责、任职要求、加分项、岗位说明..."
      helper="建议至少包含岗位职责和任职要求；系统会先检索简历片段，再调用 Doubao 生成结构化判断。"
    />
  );
}
