import type { InboxSnapshot, ActionStatus } from "../types";
import { SourceIcon, type SourceIconName } from "./SourceIcon";

export type DrawerTarget =
  | "plan"
  | "members"
  | "inventory"
  | "inbox"
  | "settings";

type NavTarget = DrawerTarget | "new";

type SidebarProps = {
  collapsed: boolean;
  busy: boolean;
  activeTarget: DrawerTarget | null;
  actionStatus: ActionStatus;
  inbox: InboxSnapshot | null;
  inboxSeen: boolean;
  onToggle: () => void;
  onSelect: (target: NavTarget) => void;
};

const NAV_ITEMS: Array<{ target: NavTarget; label: string; icon: SourceIconName }> = [
  { target: "new", label: "新对话", icon: "plus" },
  { target: "plan", label: "本餐状态", icon: "meal" },
  { target: "members", label: "家庭成员", icon: "family" },
  { target: "inventory", label: "库存", icon: "box" },
  { target: "inbox", label: "模拟信箱", icon: "mail" },
  { target: "settings", label: "设置", icon: "gear" }
];

export function Sidebar({
  collapsed,
  busy,
  activeTarget,
  actionStatus: _actionStatus,
  inbox,
  inboxSeen,
  onToggle,
  onSelect
}: SidebarProps) {
  const showInboxDot = Boolean(inbox?.items.length && !inboxSeen);

  return (
    <aside className={`nav-rail ${collapsed ? "is-collapsed" : "is-expanded"}`}>
      <div className="rail-brand">
        <SourceIcon className="brand-icon" name="plate" size={28} />
        <span className="brand-name">PrivatePlate</span>
        <button
          className="rail-toggle"
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "展开导航栏" : "收起导航栏"}
          aria-expanded={!collapsed}
          title={collapsed ? "展开导航栏" : "收起导航栏"}
        >
          <SourceIcon name={collapsed ? "plus" : "x"} size={18} />
        </button>
      </div>

      <p className="rail-caption">家庭用餐空间</p>
      <div className="rail-rule" />

      <nav className="rail-nav" aria-label="主导航">
        {NAV_ITEMS.map((item) => {
          const active = item.target !== "new" && activeTarget === item.target;
          return (
            <button
              className={`nav-item ${active ? "active" : ""}`}
              type="button"
              key={item.target}
              disabled={busy && item.target === "new"}
              onClick={() => onSelect(item.target)}
              aria-current={active ? "page" : undefined}
              title={collapsed ? item.label : undefined}
            >
              <SourceIcon name={item.icon} size={22} />
              <span className="nav-label">{item.label}</span>
              {item.target === "inbox" && showInboxDot ? (
                <span className="nav-unread-dot" aria-label="有新消息" />
              ) : null}
            </button>
          );
        })}
      </nav>

      <div className="rail-footer">
        <div className="rail-footer-rule" />
        <span className="rail-footer-label">家庭空间</span>
        <div className="household-chip">
          <span className="household-avatar">小林</span>
          <span className="space-name">小林一家</span>
        </div>
      </div>
    </aside>
  );
}
