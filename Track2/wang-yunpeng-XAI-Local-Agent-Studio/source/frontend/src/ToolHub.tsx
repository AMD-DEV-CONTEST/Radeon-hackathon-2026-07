// 工具中心（节点⑥新增）
// 数据源：/api/skills（技能）+ /api/mcp/list（MCP）+ /api/connectors（连接器）三 Tab

import { useEffect, useState } from "react";
import { Wrench, Sparkles, Plug, Server, Loader2, AlertCircle, RefreshCw, CircleDot, CircleSlash } from "lucide-react";
import { fetchSkills, fetchMcpList, fetchConnectors, fetchGatewayStatus, type SkillDef, type McpEntry, type ConnectorEntry, type GatewayStatus } from "./lib/api";

type Tab = "skills" | "mcp" | "connectors";

export default function ToolHub() {
  const [tab, setTab] = useState<Tab>("skills");
  const [skills, setSkills] = useState<SkillDef[]>([]);
  const [mcps, setMcps] = useState<McpEntry[]>([]);
  const [conns, setConns] = useState<ConnectorEntry[]>([]);
  const [gw, setGw] = useState<GatewayStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    Promise.allSettled([fetchSkills(), fetchMcpList(), fetchConnectors(), fetchGatewayStatus()]).then(([s, m, c, g]) => {
      if (s.status === "fulfilled") setSkills(s.value);
      if (m.status === "fulfilled") setMcps(m.value);
      if (c.status === "fulfilled") setConns(c.value);
      if (g.status === "fulfilled") setGw(g.value);
      if (s.status === "rejected" && m.status === "rejected" && c.status === "rejected") setError("后端连接失败");
      setLoading(false);
    });
  };
  useEffect(load, []);

  const tabs: { key: Tab; label: string; icon: JSX.Element; count: number }[] = [
    { key: "skills", label: "技能", icon: <Sparkles size={14} />, count: skills.length },
    { key: "mcp", label: "MCP 服务", icon: <Server size={14} />, count: mcps.length },
    { key: "connectors", label: "连接器", icon: <Plug size={14} />, count: conns.length },
  ];

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-1">
        <Wrench size={18} />
        <h2 className="text-lg font-semibold">工具中心</h2>
        <button onClick={load} title="刷新" className="ml-auto p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <p className="text-xs text-zinc-400 mb-4">技能 / MCP 服务 / 连接器统一管理 · 数据来自后端实时接口</p>

      {gw?.simulated && (
        <div className="flex items-start gap-2 mb-4 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-300">
          <CircleSlash size={14} className="mt-0.5 shrink-0" />
          <span><b>模拟模式：</b>{gw.note}</span>
        </div>
      )}

      <div className="flex gap-2 mb-4 border-b border-zinc-200 dark:border-zinc-800">
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs border-b-2 -mb-px transition-colors ${
              tab === t.key ? "border-blue-500 text-blue-600 dark:text-blue-400 font-medium" : "border-transparent text-zinc-400 hover:text-zinc-600"
            }`}>
            {t.icon}{t.label}<span className="text-[10px] text-zinc-400">({t.count})</span>
          </button>
        ))}
      </div>

      {loading && <div className="flex items-center gap-2 justify-center py-10 text-zinc-400 text-xs"><Loader2 size={14} className="animate-spin" /> 加载工具清单…</div>}
      {error && <div className="flex items-center gap-2 text-red-500 text-xs mb-3"><AlertCircle size={14} /> {error}</div>}

      {!loading && tab === "skills" && (
        <div className="space-y-3">
          {skills.map((s) => (
            <div key={s.name} className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-2 mb-1">
                <Sparkles size={14} className="text-blue-500" />
                <span className="text-sm font-medium">{s.name}</span>
                <span className="ml-auto text-[10px] text-zinc-400">来源: {s.source}</span>
              </div>
              <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mb-1">触发: {s.trigger || "—"}</div>
              <div className="text-xs text-zinc-500 dark:text-zinc-400 whitespace-pre-wrap break-words bg-zinc-50 dark:bg-zinc-950 rounded p-2 mt-1">{s.body || "—"}</div>
            </div>
          ))}
          {skills.length === 0 && <div className="text-center text-xs text-zinc-400 py-8">暂无技能</div>}
        </div>
      )}

      {!loading && tab === "mcp" && (
        <div className="grid grid-cols-2 gap-3">
          {mcps.map((m) => (
            <div key={m.id} className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-2 mb-1">
                <Server size={14} className="text-purple-500" />
                <span className="text-sm font-medium">{m.name}</span>
                <span className={`ml-auto flex items-center gap-1 text-[10px] ${m.enabled ? "text-emerald-500" : "text-zinc-400"}`}>
                  {m.enabled ? <CircleDot size={9} /> : <CircleSlash size={9} />}{m.enabled ? "启用" : "停用"}
                </span>
              </div>
              <div className="text-[11px] text-zinc-400">类型: {m.type}</div>
              <div className="text-[11px] text-zinc-500 dark:text-zinc-400 font-mono truncate">{m.command || m.url || "—"} {m.args?.join(" ")}</div>
            </div>
          ))}
          {mcps.length === 0 && <div className="col-span-2 text-center text-xs text-zinc-400 py-8">暂无 MCP 服务</div>}
        </div>
      )}

      {!loading && tab === "connectors" && (
        <div className="grid grid-cols-2 gap-3">
          {conns.map((c) => (
            <div key={c.name} className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-2 mb-1">
                <Plug size={14} className={c.status === "active" ? "text-emerald-500" : "text-zinc-400"} />
                <span className="text-sm font-medium">{c.name}</span>
                <span className={`ml-auto flex items-center gap-1 text-[10px] ${c.status === "active" ? "text-emerald-500" : "text-zinc-400"}`}>
                  {c.status === "active" ? <CircleDot size={9} /> : <CircleSlash size={9} />}{c.status}
                </span>
              </div>
              <div className="text-[11px] text-zinc-400">类型: {c.type}</div>
              <div className="text-[11px] text-zinc-500 dark:text-zinc-400 font-mono truncate">{c.command || c.url || "—"}</div>
              <div className="text-[10px] text-zinc-400 mt-1">最近活跃: {c.last_active || "—"}</div>
            </div>
          ))}
          {conns.length === 0 && <div className="col-span-2 text-center text-xs text-zinc-400 py-8">暂无连接器</div>}
        </div>
      )}
    </main>
  );
}
