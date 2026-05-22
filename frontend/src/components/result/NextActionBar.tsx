import type { AnalysisResult } from "../../types/analysis";
import { Button } from "../ui/Button";

interface NextActionBarProps {
  result: AnalysisResult;
  isSaved: boolean;
  onSave: () => void;
  onCopyAdvice: () => void;
  onMarkApplied: () => void;
  onAbandon: () => void;
}

export function NextActionBar({ isSaved, onSave, onCopyAdvice, onMarkApplied, onAbandon }: NextActionBarProps) {
  return (
    <div className="next-action-bar">
      <Button variant="primary" onClick={onSave} disabled={isSaved}>
        {isSaved ? "已保存到历史" : "保存到历史"}
      </Button>
      <Button variant="secondary" onClick={onCopyAdvice}>
        复制简历修改建议
      </Button>
      <Button variant="secondary" onClick={onMarkApplied}>
        标记为已投递
      </Button>
      <Button variant="ghost" onClick={onAbandon}>
        放弃该岗位
      </Button>
    </div>
  );
}
