import {
  Check,
  ChevronDown,
  History,
  MoreHorizontal,
  RotateCcw,
  RotateCw,
} from "lucide-react";

interface WorkspaceHeaderProps {
  mediaName: string;
  saved: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
}

export function WorkspaceHeader({
  mediaName,
  saved,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
}: WorkspaceHeaderProps) {
  return (
    <div className="workspace-header">
      <div className="workspace-title">
        <span>{mediaName}</span>
        <button type="button" aria-label="项目菜单" disabled title="项目切换位于顶部栏">
          <ChevronDown size={13} />
        </button>
        <div className="save-state">
          <Check size={11} />
          {saved ? "已保存" : "保存中"}
        </div>
      </div>
      <div className="workspace-tools">
        <button
          type="button"
          aria-label="撤销"
          disabled={!canUndo}
          title={canUndo ? "撤销上一项图事务" : "暂无可撤销的图事务"}
          onClick={onUndo}
        >
          <RotateCcw size={15} />
        </button>
        <button
          type="button"
          aria-label="重做"
          disabled={!canRedo}
          title={canRedo ? "重做上一项图事务" : "暂无可重做的图事务"}
          onClick={onRedo}
        >
          <RotateCw size={15} />
        </button>
        <span />
        <button type="button" aria-label="历史记录" disabled title="当前 MVP 尚未启用历史面板">
          <History size={15} />
        </button>
        <button type="button" aria-label="更多" disabled title="当前 MVP 暂无更多操作">
          <MoreHorizontal size={16} />
        </button>
      </div>
    </div>
  );
}
