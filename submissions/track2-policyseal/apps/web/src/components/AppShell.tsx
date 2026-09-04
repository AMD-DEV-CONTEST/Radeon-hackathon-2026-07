import { FileLock2, Plus, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import type { ApiState, DemoRole } from "../lib/types";
import { DemoRoleSwitch } from "../features/approvals/DemoRoleSwitch";
import { Button } from "./ui/Button";
import { RuntimeStatus } from "./RuntimeStatus";

interface AppShellProps {
  apiState: ApiState;
  apiVersion?: string;
  role: DemoRole;
  onRoleChange: (role: DemoRole) => void;
  onNewTask: () => void;
  children: ReactNode;
}

export function AppShell({
  apiState,
  apiVersion,
  role,
  onRoleChange,
  onNewTask,
  children,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar__top">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              <ShieldCheck size={19} strokeWidth={1.9} />
            </span>
            <span>PolicySeal</span>
          </div>

          <nav className="primary-nav" aria-label="Primary navigation">
            <button className="primary-nav__item primary-nav__item--active" type="button">
              <FileLock2 size={16} aria-hidden="true" />
              <span>Disclosure tasks</span>
            </button>
          </nav>
        </div>

        <div className="sidebar__bottom">
          <DemoRoleSwitch role={role} onRoleChange={onRoleChange} />
          <RuntimeStatus state={apiState} version={apiVersion} />
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <p className="section-label">Local disclosure workspace</p>
            <h1>Disclosure tasks</h1>
          </div>
          <Button
            variant="primary"
            icon={<Plus size={16} aria-hidden="true" />}
            onClick={onNewTask}
          >
            New task
          </Button>
        </header>
        {children}
      </main>
    </div>
  );
}
