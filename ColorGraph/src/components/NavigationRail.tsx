import {
  Boxes,
  CircleUserRound,
  Command,
  FolderKanban,
  PackageOpen,
  Settings2,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import type { PanelId } from "../types";

interface NavigationRailProps {
  activePanel: PanelId;
  onChange: (panel: PanelId) => void;
}

const ITEMS: {
  id: PanelId;
  label: string;
  icon: typeof Command;
}[] = [
  { id: "agent", label: "创意 Agent", icon: Sparkles },
  { id: "grade", label: "调色", icon: Settings2 },
  { id: "graph", label: "节点图", icon: Workflow },
  { id: "quality", label: "质检", icon: ShieldCheck },
  { id: "assets", label: "资产", icon: PackageOpen },
];

export function NavigationRail({
  activePanel,
  onChange,
}: NavigationRailProps) {
  return (
    <aside className="nav-rail" aria-label="主导航">
      <div className="rail-top">
        <button
          className="rail-button rail-project"
          type="button"
          aria-label="项目"
          disabled
          title="最近项目会在启动时自动恢复"
        >
          <FolderKanban size={18} />
        </button>
        <div className="rail-divider" />
        {ITEMS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`rail-button ${activePanel === id ? "is-active" : ""}`}
            type="button"
            aria-label={label}
            data-tooltip={label}
            onClick={() => onChange(id)}
          >
            <Icon size={18} strokeWidth={1.7} />
          </button>
        ))}
      </div>
      <div className="rail-bottom">
        <button className="rail-button" type="button" aria-label="组件" disabled>
          <Boxes size={18} strokeWidth={1.7} />
        </button>
        <button className="rail-button" type="button" aria-label="命令面板" disabled>
          <Command size={18} strokeWidth={1.7} />
        </button>
        <button className="rail-avatar" type="button" aria-label="账户" disabled>
          <CircleUserRound size={21} strokeWidth={1.5} />
        </button>
      </div>
    </aside>
  );
}
