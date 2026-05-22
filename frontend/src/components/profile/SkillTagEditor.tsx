import { useState } from "react";
import { Button } from "../ui/Button";

export function SkillTagEditor({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  function addValue() {
    const nextValue = draft.trim();
    if (!nextValue || values.includes(nextValue)) return;
    onChange([...values, nextValue]);
    setDraft("");
  }

  return (
    <div className="tag-editor">
      <label className="field">
        <span>{label}</span>
        <div className="inline-input">
          <input value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addValue();
            }
          }} />
          <Button type="button" onClick={addValue}>添加</Button>
        </div>
      </label>
      <div className="tag-row editable">
        {values.map((value) => (
          <button key={value} type="button" onClick={() => onChange(values.filter((item) => item !== value))}>
            {value} ×
          </button>
        ))}
      </div>
    </div>
  );
}
