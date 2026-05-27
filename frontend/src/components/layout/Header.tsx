import { Button } from "../ui/Button";

interface HeaderProps {
  onNewAnalysis: () => void;
  onHistory: () => void;
  isMobile?: boolean;
}

export function Header({ onNewAnalysis, onHistory, isMobile }: HeaderProps) {
  return (
    <header className="top-header">
      <div>
        <p className="eyebrow">实习通 InternPath</p>
        <h1>求职决策台</h1>
        <span>JD 分析、投递判断、简历改造、学习建议</span>
      </div>
      {/* 移动端隐藏操作按钮（已移入汉堡菜单） */}
      {!isMobile && (
        <div className="header-actions">
          <Button variant="secondary" onClick={onHistory}>
            查看历史
          </Button>
          <Button variant="primary" onClick={onNewAnalysis}>
            新建分析
          </Button>
        </div>
      )}
    </header>
  );
}
