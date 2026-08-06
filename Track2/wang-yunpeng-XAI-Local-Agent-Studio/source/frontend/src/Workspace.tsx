// 工作台 — 系统总览（看板 + Agent + 拓扑 三 Tab）
import { useState } from "react";
import Dashboard from "./Dashboard";
import AgentWorkspace from "./AgentWorkspace";
import TaskCanvas from "./TaskCanvas";

const TABS = [
  { key: "dashboard", label: "看板", render: () => <Dashboard /> },
  { key: "agents", label: "Agent", render: () => <AgentWorkspace /> },
  { key: "topology", label: "拓扑", render: () => <TaskCanvas /> },
];

export default function Workspace() {
  const [tab, setTab] = useState("dashboard");

  return (
    <div className="h-full flex flex-col bg-zinc-50 dark:bg-zinc-950">
      {/* Tab 切换栏 */}
      <div className="flex items-center gap-0.5 px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-1.5 rounded-lg text-xs font-medium transition-all ${
              tab === t.key
                ? "bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400"
                : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            {t.label}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-zinc-400">工作台</span>
      </div>

      {/* Tab 内容 */}
      <div className="flex-1 overflow-hidden">
        {TABS.find((t) => t.key === tab)?.render()}
      </div>
    </div>
  );
}
