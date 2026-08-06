// Task Canvas（节点⑤真实数据接线）
// 数据源：/api/agents（拓扑节点动态生成）+ /api/status（底栏真实状态）
// 画布渲染统一复用 CanvasCore（MiniCanvas），本组件仅负责「数据 → 节点/连线」的拓扑建模。
// readOnly + styleMode="fixed"：只读展示，精确保留业务自定义配色。

import { useEffect, useMemo, useState } from "react";
import { MarkerType } from "reactflow";
import { fetchAgents, fetchStatus, type AgentInfo } from "./lib/api";
import { MiniCanvas } from "./MiniCanvas";

const AGENT_STYLE: Record<string, { bg: string; border: string }> = {
  researcher: { bg: "#ecfdf5", border: "2px solid #10b981" },
  engineer: { bg: "#fffbeb", border: "2px solid #f59e0b" },
  pm: { bg: "#eff6ff", border: "2px solid #3b82f6" },
};

export default function TaskCanvas() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [statusLine, setStatusLine] = useState("连接后端中…");

  useEffect(() => {
    fetchAgents().then(setAgents).catch(() => {});
    fetchStatus()
      .then((s) => {
        const mem = s.memory as any;
        setStatusLine(
          `引擎 ${s.xai_engine || "?"} · 模型 ${s.model || "?"} · 项目 ${s.project?.name || "-"} · 待审批 ${s.pending_approvals ?? 0}${mem?.ok ? " · Memory OK" : ""}`
        );
      })
      .catch(() => setStatusLine("后端连接失败"));
  }, []);

  const { nodes, edges } = useMemo(() => {
    const workers = agents.filter((a) => a.role !== "pm");
    const pm = agents.find((a) => a.role === "pm");
    const n: any[] = [
      { id: "goal", position: { x: 300, y: 0 }, data: { label: "用户目标" }, style: { background: "#f0fdf4", border: "2px solid #22c55e", borderRadius: 12, padding: 10, fontSize: 12, width: 140 } },
      { id: "planner", position: { x: 300, y: 100 }, data: { label: (pm ? pm.name : "Planner") + "\n分析 → 拆解 → 分配" }, style: { background: "#eff6ff", border: "2px solid #3b82f6", borderRadius: 12, padding: 10, fontSize: 11, width: 150 } },
      ...workers.map((a, i) => ({
        id: a.id,
        position: { x: 120 + i * 360, y: 220 },
        data: { label: `${a.name}\n${a.role} · ${a.backend}` },
        style: { ...(AGENT_STYLE[a.role] || { bg: "#f8fafc", border: "2px solid #64748b" }), background: (AGENT_STYLE[a.role] || { bg: "#f8fafc" }).bg, borderRadius: 12, padding: 10, fontSize: 11, width: 150 },
      })),
      { id: "result", position: { x: 300, y: 340 }, data: { label: "结果交付" }, style: { background: "#f0fdf4", border: "2px solid #22c55e", borderRadius: 12, padding: 10, fontSize: 12, width: 140 } },
      { id: "memory", position: { x: 300, y: 440 }, data: { label: "Memory 8 层" }, style: { background: "#f8fafc", border: "2px solid #64748b", borderRadius: 12, padding: 10, fontSize: 11, width: 130 } },
    ];
    const e: any[] = [
      { id: "e-goal", source: "goal", target: "planner", markerEnd: { type: MarkerType.ArrowClosed } },
      ...workers.map((a) => ({ id: "e-to-" + a.id, source: "planner", target: a.id, markerEnd: { type: MarkerType.ArrowClosed } })),
      ...workers.map((a) => ({ id: "e-from-" + a.id, source: a.id, target: "result", markerEnd: { type: MarkerType.ArrowClosed } })),
      { id: "e-mem", source: "result", target: "memory", markerEnd: { type: MarkerType.ArrowClosed } },
    ];
    return { nodes: n, edges: e };
  }, [agents]);

  return (
    <main className="flex-1 flex flex-col bg-zinc-50 dark:bg-zinc-950 h-full">
      <div className="p-4 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0">
        <h2 className="text-sm font-semibold">Task Canvas — 智能任务地图</h2>
        <p className="text-[10px] text-zinc-400 mt-0.5">节点来自后端实时 Agent 注册表（/api/agents）· 可拖拽</p>
      </div>
      <div className="flex-1 relative">
        <MiniCanvas nodes={nodes} edges={edges} viewMode="dag" readOnly styleMode="fixed" onPersist={() => {}} />
      </div>
      <div className="p-2 border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-[10px] text-zinc-400 text-center shrink-0">
        {statusLine}
      </div>
    </main>
  );
}
