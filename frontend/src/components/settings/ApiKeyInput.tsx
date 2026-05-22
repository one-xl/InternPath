interface ApiKeyInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

export function ApiKeyInput({ value, onChange, placeholder = "输入 API Key；编辑已有配置时留空表示不修改" }: ApiKeyInputProps) {
  return (
    <div className="api-key-input" style={{ display: "flex", flexDirection: "column", gap: "6px", width: "100%" }}>
      <input
        type="password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete="off"
      />
      <span style={{ fontSize: "12px", color: "#a855f7", fontWeight: "500" }}>
        API Key 只会提交到后端加密保存；编辑已有配置时留空会保留原密钥。
      </span>
    </div>
  );
}
