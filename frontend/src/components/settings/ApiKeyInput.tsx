import { useState } from "react";
import { maskApiKey } from "../../utils/modelConfigStorage";
import { Button } from "../ui/Button";

interface ApiKeyInputProps {
  value: string;
  onChange: (value: string) => void;
}

export function ApiKeyInput({ value, onChange }: ApiKeyInputProps) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="api-key-input">
      <input
        type={visible ? "text" : "password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="粘贴 API Key"
        autoComplete="off"
      />
      <Button type="button" variant="ghost" onClick={() => setVisible((current) => !current)}>
        {visible ? "隐藏" : "显示"}
      </Button>
      <Button type="button" variant="ghost" onClick={() => onChange("")}>
        清空
      </Button>
      <small>{maskApiKey(value)}</small>
    </div>
  );
}
