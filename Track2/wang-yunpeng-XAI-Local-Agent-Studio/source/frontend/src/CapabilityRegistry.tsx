// 能力注册表（节点⑥新增）
// 数据源：/api/capabilities → [{id,name,type,status,description,meta}]  type: agent|skill|tool
// 系统全部能力的统一视图（Agent 3 + Skill 6 + Tool 3）

import { useEffect, useMemo, useState } from "react";
import { Boxes, Bot, Sparkles, Wrench, Loader2, AlertCircle, RefreshCw, CircleDot } from "lucide-react";
import { fetchCapabilities, type Capability } from "./lib/api";

const TYPE_META: Record<string, { label: string; icon: JSX.Element; color: string }> = {
  agent: { label: "Agent 数字员工", icon: <Bot size={15} />, color: "emerald" },
  skill: { label: "Skill 技能", icon: <Sparkles size={15} />, color: "blue" },
  tool: { label: "Tool 工具 / 连接器", icon: <Wrench size={15} />, color: "amber" },
};

export default function CapabilityRegistry() {
  const [caps, setCaps] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<string>("all");

  const load = () => {
    setLoading(true);
    setError("");
    fetchCapabilities().then(setCaps).catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const groups = useMemo(() => {
    const g: Record<string, Capability[]> = { agent: [], skill: [], tool: [] };
    for (const c of caps) (g[c.type] || (g[c.type] = [])).push(c);
    return g;
  }, [caps]);

  const types = ["all", "agent", "skill", "tool"];
  const shown = filter === "all" ? caps : caps.filter((c) => c.type === filter);

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-1">
        <Boxes size={18} />
        <h2 className="text-lg font-semibold">能力注册表</h2>
        <button onClick={load} title="刷新" className="ml-auto p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <p className="text-xs text-zinc-400 mb-4">
        系统全部能力统一视图 · 共 {caps.length} 项（Agent {groups.agent?.length || 0} · Skill {groups.skill?.length || 0} · Tool {groups.tool?.length || 0}）· 数据来自 /api/capabilities
      </p>

      <div className="flex gap-2 mb-4">
        {types.map((t) => (
          <button key={t} onClick={() => setFilter(t)}
            className={`px-3 py-1 rounded-full text-xs border transition-colors ${
              filter === t
                ? "bg-blue-500 text-white border-blue-500"
                : "border-zinc-200 dark:border-zinc-700 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}>
            {t === "all" ? "全部" : TYPE_META[t]?.label || t}
          </button>
        ))}
      </div>

      {loading && <div className="flex items-center gap-2 justify-center py-10 text-zinc-400 text-xs"><Loader2 size={14} className="animate-spin" /> 加载能力清单…</div>}
      {error && <div className="flex items-center gap-2 text-red-500 text-xs"><AlertCircle size={14} /> {error}</div>}

      <div className="grid grid-cols-3 gap-3">
        {shown.map((c) => {
          const meta = TYPE_META[c.type] || { label: c.type, icon: <Boxes size={15} />, color: "zinc" };
          return (
            <div key={c.type + ":" + c.id + ":" + c.name} className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-${meta.color}-500`}>{meta.icon}</span>
                <span className="text-sm font-medium truncate">{c.name}</span>
                <span className="ml-auto flex items-center gap-1 text-[10px] text-emerald-500">
                  <CircleDot size={9} />{c.status}
                </span>
              </div>
              <div className="text-[10px] text-zinc-400 mb-1">{meta.label}</div>
              <div className="text-xs text-zinc-500 dark:text-zinc-400 break-words line-clamp-2">{c.description || "—"}</div>
              <div className="text-[10px] text-zinc-400 mt-2 font-mono truncate">{c.meta} · {c.id}</div>
            </div>
          );
        })}
      </div>
      {!loading && shown.length === 0 && !error && (
        <div className="text-center text-xs text-zinc-400 py-8">该类别下暂无能力</div>
      )}
    </main>
  );
}
