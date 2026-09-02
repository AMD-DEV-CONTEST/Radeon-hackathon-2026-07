// Evolution Center（节点⑤真实数据接线）
// 数据源：/api/gepa/status（进化引擎状态：generation/pareto/触发原因）
//        + /api/memory/list（前端过滤 layer ∈ causal/failure_correction/reflection）
// 原版 4 条硬编码假 lessons 已删除

import { useEffect, useState } from "react";
import { Dna, Loader2, AlertCircle, RefreshCw, GitBranch, Zap, Inbox } from "lucide-react";
import { fetchGepaStatus, fetchMemoryList, type GepaStatus, type MemoryEntry } from "./lib/api";

const EVOLUTION_LAYERS = new Set(["causal", "failure_correction", "reflection"]);

const LAYER_LABEL: Record<string, string> = {
  causal: "因果链",
  failure_correction: "失败修正",
  reflection: "反思",
};

function fmtDate(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function EvolutionCenter() {
  const [gepa, setGepa] = useState<GepaStatus | null>(null);
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    Promise.allSettled([fetchGepaStatus(), fetchMemoryList()]).then(([g, m]) => {
      if (g.status === "fulfilled") setGepa(g.value);
      if (m.status === "fulfilled") setEntries(m.value.filter((e) => EVOLUTION_LAYERS.has(e.layer)));
      if (g.status === "rejected" && m.status === "rejected") setError("后端连接失败");
      setLoading(false);
    });
  };
  useEffect(load, []);

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-1">
        <Dna size={18} />
        <h2 className="text-lg font-semibold">Evolution Center</h2>
        <button onClick={load} title="刷新" className="ml-auto p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <p className="text-xs text-zinc-400 mb-6">AI 成长记录 · GEPA 进化引擎 + 反思/因果/修正记忆</p>

      {gepa && gepa.generation === 0 && (
        <div className="flex items-start gap-2 mb-4 rounded-lg border border-zinc-300 bg-zinc-50 dark:bg-zinc-900/40 dark:border-zinc-700 px-3 py-2 text-[11px] text-zinc-500 dark:text-zinc-400">
          <Inbox size={14} className="mt-0.5 shrink-0" />
          <span>进化引擎为实验性功能，当前<strong>尚未运行过任何一代</strong>（generation=0）。下方「进化记忆」来自反思/因果/失败修正层，并非 GEPA 自动进化产物；触发进化后这里才会填充真实结果。</span>
        </div>
      )}

      {loading && <div className="flex items-center gap-2 justify-center py-10 text-zinc-400 text-xs"><Loader2 size={14} className="animate-spin" /> 加载进化数据…</div>}
      {error && <div className="flex items-center gap-2 text-red-500 text-xs mb-3"><AlertCircle size={14} /> {error}</div>}

      {gepa && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-2 text-sm font-medium">
              <GitBranch size={15} className="text-purple-500" /> 第 {gepa.generation} 代
            </div>
            <div className="text-xs text-zinc-400 mt-1">Pareto 前沿 {gepa.pareto_frontier_size} 个候选</div>
          </div>
          <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Zap size={15} className={gepa.running ? "text-amber-500" : "text-zinc-400"} />
              {gepa.running ? "进化运行中" : "待机"}
            </div>
            <div className="text-xs text-zinc-400 mt-1">周期 {gepa.interval_hours}h · 上次 {gepa.last_run ? fmtDate(gepa.last_run) : "-"}</div>
          </div>
          <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
            <div className="text-sm font-medium">最近触发</div>
            <div className="text-[10px] text-zinc-400 mt-1 break-words">{gepa.last_trigger || "-"}</div>
          </div>
        </div>
      )}

      <div className="text-xs text-zinc-400 mb-2">进化记忆（{entries.length} 条 · 来自因果链 / 失败修正 / 反思层）</div>

      {!loading && entries.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-10 text-zinc-400">
          <Inbox size={24} strokeWidth={1.2} />
          <div className="text-xs">暂无进化层记忆记录</div>
        </div>
      )}

      <div className="space-y-3">
        {entries.map((e) => (
          <div key={e.id} className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-bold px-2 py-0.5 rounded bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
                {LAYER_LABEL[e.layer] || e.layer}
              </span>
              <span className="text-sm font-medium truncate">{e.key}</span>
              <span className="ml-auto text-[10px] text-zinc-400 shrink-0">{fmtDate(e.created_at)} · 权重 {e.importance}</span>
            </div>
            <div className="text-xs text-zinc-500 dark:text-zinc-400 whitespace-pre-wrap break-words">{e.value}</div>
            <div className="text-[10px] text-zinc-400 mt-1">engine: {e.engine} · #{e.id}</div>
          </div>
        ))}
      </div>
    </main>
  );
}
