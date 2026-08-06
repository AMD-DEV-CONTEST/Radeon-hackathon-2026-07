// 执行时间线（节点⑤真实数据接线）
// 数据源：/api/workflow/history → { history: [...] }（当前为空 → 真实空态，不再伪造假事件）

import { useEffect, useState } from "react";
import { Clock, Loader2, AlertCircle, Inbox, RefreshCw } from "lucide-react";
import { fetchWorkflowHistory } from "./lib/api";

function fmtTs(v: any): string {
  if (!v) return "-";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(String(v).replace(" ", "T"));
  if (isNaN(d.getTime())) return String(v);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function Timeline() {
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    fetchWorkflowHistory().then(setEvents).catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-1">
        <Clock size={18} />
        <h2 className="text-lg font-semibold">执行时间线</h2>
        <button onClick={load} title="刷新" className="ml-auto p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <p className="text-xs text-zinc-400 mb-6">工作流执行历史 · 数据来自后端 /api/workflow/history</p>

      {loading && <div className="flex items-center gap-2 justify-center py-10 text-zinc-400 text-xs"><Loader2 size={14} className="animate-spin" /> 加载执行历史…</div>}
      {error && <div className="flex items-center gap-2 text-red-500 text-xs"><AlertCircle size={14} /> {error}</div>}

      {!loading && !error && events.length === 0 && (
        <div className="flex flex-col items-center gap-3 py-16 text-zinc-400">
          <Inbox size={28} strokeWidth={1.2} />
          <div className="text-sm">暂无工作流执行记录</div>
          <div className="text-[11px]">在控制台发起任务后，执行过程将在这里可追溯</div>
        </div>
      )}

      <div className="space-y-0">
        {events.map((e: any, i: number) => (
          <div key={i} className="flex gap-4">
            <div className="w-16 text-right shrink-0">
              <div className="text-[10px] text-zinc-400">{fmtTs(e.ts || e.time || e.created_at)}</div>
              <div className={`mt-1 w-2 h-2 rounded-full mx-auto ${e.status === "done" || e.status === "success" ? "bg-emerald-400" : e.status === "running" ? "bg-amber-400 animate-pulse" : "bg-zinc-200 dark:bg-zinc-700"}`} />
              {i < events.length - 1 && <div className="w-0.5 h-12 bg-zinc-200 dark:bg-zinc-700 mx-auto mt-1" />}
            </div>
            <div className="pb-5 min-w-0">
              <div className="text-xs font-medium truncate">{e.agent || e.name || "workflow"} · {e.action || e.step || e.type || "执行"}</div>
              <div className="text-[10px] text-zinc-400 mt-0.5 break-words">{e.detail || e.description || JSON.stringify(e).slice(0, 120)}</div>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
