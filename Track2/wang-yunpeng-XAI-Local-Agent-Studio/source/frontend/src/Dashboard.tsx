// Dashboard（节点⑤真实数据接线）
// 数据源：/api/status + /api/agents + /api/memory/stats（均实测可用）
// ⚠️ 不用 /api/dashboard：运行实例报 "_EVENT_LOCK is not defined"（漂移，见记忆 2026-07-23）

import { useEffect, useState } from "react";
import { Activity, Users, Database, Loader2, AlertCircle, CircleDot, Coins } from "lucide-react";
import { fetchStatus, fetchAgents, fetchMemoryStats, fetchUsageStats, type AgentInfo, type MemoryStats, type SystemStatus, type UsageStats } from "./lib/api";

const ROLE_LABEL: Record<string, string> = {
  researcher: "思考者 · 研究/规划/推理",
  engineer: "工程师 · 编码/文件/测试",
  pm: "协调者 · 调度/分配/整合",
};

function subsystemState(s: any): { ok: boolean; text: string } {
  if (!s) return { ok: false, text: "未知" };
  if (typeof s === "string") return { ok: s === "running" || s === "ok", text: s };
  return { ok: !!s.ok, text: s.ok ? "正常" : (s.error || "异常") };
}

export default function Dashboard() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [mem, setMem] = useState<MemoryStats | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.allSettled([fetchStatus(), fetchAgents(), fetchMemoryStats(), fetchUsageStats()]).then(([s, a, m, u]) => {
      if (s.status === "fulfilled") setStatus(s.value);
      if (a.status === "fulfilled") setAgents(a.value);
      if (m.status === "fulfilled") setMem(m.value);
      if (u.status === "fulfilled") setUsage(u.value);
      if (s.status === "rejected" && a.status === "rejected" && m.status === "rejected")
        setError("后端连接失败");
      setLoading(false);
    });
  }, []);

  const memTotal = mem ? Object.values(mem.layers || {}).reduce((n, l) => n + (l.count || 0), 0) : 0;
  const memLayers = mem ? Object.keys(mem.layers || {}).length : 0;
  const engineOk = status?.xai_engine === "running";
  const hermes = subsystemState(status?.hermes);
  const openclaw = subsystemState(status?.openclaw);

  if (loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-6 bg-zinc-50 dark:bg-zinc-950 h-full">
        <div className="flex items-center gap-2 text-zinc-400 text-sm"><Loader2 size={16} className="animate-spin" /> 加载系统状态…</div>
      </main>
    );
  }

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      <h2 className="text-lg font-semibold mb-1">AI 生命状态</h2>
      <p className="text-xs text-zinc-400 mb-6">当前系统运行概况 · 数据来自运行后端实时接口</p>

      {error && (
        <div className="flex items-center gap-2 mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-300 text-xs">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Activity size={15} className={engineOk ? "text-emerald-500" : "text-red-500"} />
            引擎 {engineOk ? "运行中" : status?.xai_engine || "离线"}
          </div>
          <div className="text-xs text-zinc-400 mt-1">
            模型 {status?.model || "-"} · Hermes {hermes.ok ? "✓" : "✗"} · OpenClaw {openclaw.ok ? "✓" : "✗"}
          </div>
        </div>
        <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Users size={15} className="text-blue-500" /> {agents.length} Agent 就绪
          </div>
          <div className="text-xs text-zinc-400 mt-1">{agents.map((a) => a.name).join(" / ") || "无 Agent"}</div>
        </div>
        <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Database size={15} className="text-amber-500" /> {memTotal} 条记忆
          </div>
          <div className="text-xs text-zinc-400 mt-1">{memLayers} 层记忆核心</div>
        </div>
      </div>

      <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800 mb-4">
        <div className="text-xs text-zinc-400 mb-1">当前项目</div>
        <div className="text-sm font-medium">{status?.project?.name || "默认工作区"}</div>
        <div className="text-xs text-zinc-400 mt-1">
          {status?.project?.id || ""} · 待审批 {status?.pending_approvals ?? 0} 项
        </div>
      </div>

      {usage && usage.status === "ok" && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800 mb-4">
          <div className="flex items-center gap-2 text-sm font-medium mb-2">
            <Coins size={15} className="text-violet-500" /> Token 用量
            <span className="text-xs text-zinc-400 font-normal ml-auto">近 {usage.window_days ?? 30} 天</span>
          </div>
          <div className="grid grid-cols-4 gap-3 text-xs">
            <div>
              <div className="text-zinc-400">今日</div>
              <div className="text-sm font-semibold mt-0.5">{(usage.today.total_tokens / 1000).toFixed(1)}k</div>
              <div className="text-[10px] text-zinc-400">{usage.today.calls} 次调用</div>
            </div>
            <div>
              <div className="text-zinc-400">总量</div>
              <div className="text-sm font-semibold mt-0.5">{(usage.total.total_tokens / 1000).toFixed(1)}k</div>
              <div className="text-[10px] text-zinc-400">{usage.total.calls} 次调用</div>
            </div>
            <div>
              <div className="text-zinc-400">预估花费</div>
              <div className="text-sm font-semibold mt-0.5">
                {usage.total.est_cost_cny != null ? `¥${usage.total.est_cost_cny.toFixed(2)}` : "—"}
              </div>
              <div className="text-[10px] text-zinc-400">仅云端模型</div>
            </div>
            <div>
              <div className="text-zinc-400">模型 TOP</div>
              {usage.by_model.slice(0, 2).map((m) => (
                <div key={m.model} className="text-[10px] text-zinc-500 mt-0.5 truncate">
                  {m.model || "?"} · {(m.total_tokens / 1000).toFixed(1)}k
                </div>
              ))}
              {usage.by_model.length === 0 && <div className="text-[10px] text-zinc-400 mt-0.5">暂无记录</div>}
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {agents.map((a) => (
          <div key={a.id} className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-2 mb-2">
              <CircleDot size={10} className="text-emerald-400" />
              <span className="text-sm font-medium">{a.name}</span>
            </div>
            <div className="text-xs text-zinc-500 mb-1">{ROLE_LABEL[a.role] || a.role}</div>
            <div className="text-[10px] text-zinc-400">backend: {a.backend}</div>
            <div className="text-[10px] text-zinc-400 mt-2 font-mono">{a.id}</div>
          </div>
        ))}
        {agents.length === 0 && (
          <div className="col-span-3 text-center text-xs text-zinc-400 py-6">后端未返回 Agent 列表</div>
        )}
      </div>
    </main>
  );
}
