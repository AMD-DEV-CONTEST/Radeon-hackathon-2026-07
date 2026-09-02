// Memory Center（近期升级：参考 5.3.3 "长期记忆展示与编辑"）
// 数据源：/api/memory/stats → 8层统计卡片（原有）
//         /api/memory/list → 记忆条目 CRUD（新增）
//         /api/memory/store/update/delete → 后端 CRUD（新增）

import { useEffect, useState, useCallback } from "react";
import { Brain, Loader2, RefreshCw, BookOpen, Dna, Search, Plus, Trash2, Check, X, PencilLine, ChevronDown, ChevronUp, Layers, Filter, Clock } from "lucide-react";
import { fetchMemoryStats, fetchMemoryList, storeMemory, updateMemory, deleteMemory, type MemoryStats, type MemoryEntry } from "./lib/api";
import KnowledgeBase from "./KnowledgeBase";
import EvolutionCenter from "./EvolutionCenter";
import { ErrorBanner, Skeleton } from "./_ui";

const LAYER_META: Record<string, { label: string; desc: string; color: string }> = {
  working: { label: "工作记忆", desc: "当前任务上下文", color: "emerald" },
  short_term: { label: "短期记忆", desc: "近期对话历史", color: "blue" },
  long_term: { label: "长期记忆", desc: "重要知识沉淀", color: "amber" },
  anchor: { label: "锚点记忆", desc: "关键决策与里程碑", color: "purple" },
  reflection: { label: "反思记忆", desc: "经验反思总结", color: "pink" },
  causal: { label: "因果链", desc: "错误 → 根因 → 修复", color: "red" },
  user_profile: { label: "用户画像", desc: "偏好 · 习惯 · 约束", color: "indigo" },
  failure_correction: { label: "失败修正", desc: "错误修正记录", color: "orange" },
};

const LAYER_OPTIONS = [
  { value: "", label: "全部层" },
  ...Object.entries(LAYER_META).map(([k, v]) => ({ value: k, label: v.label })),
];

function fmtTime(ts: number): string {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function MemoryCenter() {
  const [tab, setTab] = useState("memory");
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // ── 记忆浏览/管理状态 ──
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [entriesLoading, setEntriesLoading] = useState(false);
  const [searchKeyword, setSearchKeyword] = useState("");
  const [layerFilter, setLayerFilter] = useState("");

  // 编辑态
  const [editId, setEditId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmDelId, setConfirmDelId] = useState<number | null>(null);

  // 添加表单
  const [showAddForm, setShowAddForm] = useState(false);
  const [addLayer, setAddLayer] = useState("short_term");
  const [addKey, setAddKey] = useState("");
  const [addValue, setAddValue] = useState("");
  const [addImportance, setAddImportance] = useState(0.5);
  const [addError, setAddError] = useState("");

  if (tab === "knowledge") return <KnowledgeBase />;
  if (tab === "evolution") return <EvolutionCenter />;

  const loadStats = () => {
    setLoading(true);
    setError("");
    fetchMemoryStats().then(setStats).catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false));
  };

  const loadEntries = useCallback(() => {
    setEntriesLoading(true);
    fetchMemoryList(layerFilter || undefined, searchKeyword || undefined, 50)
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setEntriesLoading(false));
  }, [layerFilter, searchKeyword]);

  useEffect(loadStats, []);
  useEffect(() => { if (tab === "browse") loadEntries(); }, [tab, layerFilter, searchKeyword, loadEntries]);

  const layers = stats ? Object.entries(stats.layers || {}) : [];
  const total = layers.reduce((n, [, l]) => n + (l.count || 0), 0);

  // ── CRUD 操作 ──
  const doEdit = (entry: MemoryEntry) => { setEditId(entry.id); setEditValue(entry.value); };
  const saveEdit = async (id: number) => {
    if (!editValue.trim()) return;
    try {
      await updateMemory(id, editValue.trim());
      setEntries((prev) => prev.map((e) => e.id === id ? { ...e, value: editValue.trim() } : e));
      setEditId(null);
    } catch (e: any) { /* 静默 */ }
  };
  const cancelEdit = () => setEditId(null);

  const doDelete = async (id: number) => {
    try {
      await deleteMemory(id);
      setEntries((prev) => prev.filter((e) => e.id !== id));
    } catch (e: any) { /* 静默 */ }
    setConfirmDelId(null);
  };

  const doAdd = async () => {
    if (!addKey.trim() || !addValue.trim()) { setAddError("key 和 value 不能为空"); return; }
    setAddError("");
    try {
      const id = await storeMemory(addLayer, addKey.trim(), addValue.trim(), "xai", addImportance);
      const newEntry: MemoryEntry = {
        id, layer: addLayer, engine: "xai", key: addKey.trim(), value: addValue.trim(),
        importance: addImportance, meta: {}, created_at: Date.now() / 1000, accessed_at: Date.now() / 1000,
      };
      setEntries((prev) => [newEntry, ...prev]);
      setShowAddForm(false);
      setAddKey(""); setAddValue(""); setAddLayer("short_term"); setAddImportance(0.5);
    } catch (e: any) { setAddError(e?.message || "添加失败"); }
  };

  // ── 8层统计卡片（原有视图） ──
  const StatsView = () => (
    <div className="p-6">
      <div className="flex items-center gap-2 mb-1">
        <Brain size={18} />
        <h2 className="text-lg font-semibold">Memory Center</h2>
        <button onClick={loadStats} title="刷新" className="ml-auto p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <p className="text-xs text-zinc-400 mb-6">
        AI 的知识空间 · {layers.length} 层记忆 · 共 {total} 条
      </p>
      {loading && <Skeleton lines={4} />}
      {error && <ErrorBanner message={error} onRetry={loadStats} />}
      <div className="grid grid-cols-2 gap-3">
        {layers.map(([key, l]) => {
          const meta = LAYER_META[key] || { label: key, desc: "", color: "zinc" };
          const usage = l.capacity ? Math.min(100, Math.round((l.count / l.capacity) * 100)) : 0;
          return (
            <div key={key} className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-2 mb-2">
                <span className={`w-2 h-2 rounded-full bg-${meta.color}-400`} />
                <span className="text-sm font-medium">{meta.label}</span>
                <span className="ml-auto text-xs text-zinc-400">{l.count} / {l.capacity} 条</span>
              </div>
              <div className="text-[10px] text-zinc-400 mb-2">{meta.desc}</div>
              <div className="h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden mb-2">
                <div className={`h-full rounded-full bg-${meta.color}-400`} style={{ width: `${usage}%` }} />
              </div>
              <div className="flex gap-3 text-[10px] text-zinc-400">
                <span>命中率 {Math.round((l.hit_rate || 0) * 100)}%</span>
                <span>健康度 {Math.round((l.health || 0) * 100)}%</span>
                <span className="ml-auto">{usage}% 占用</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

  // ── 浏览/编辑记忆（新增视图） ──
  const BrowseView = () => (
    <div className="flex flex-col h-full">
      {/* 搜索/过滤栏 */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0">
        <Search size={13} className="text-zinc-400 shrink-0" />
        <input
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          placeholder="搜索 key 或 value…"
          className="flex-1 bg-transparent outline-none text-xs text-zinc-700 dark:text-zinc-200 placeholder:text-zinc-400 min-w-0"
        />
        <Filter size={13} className="text-zinc-400 shrink-0" />
        <select value={layerFilter} onChange={(e) => setLayerFilter(e.target.value)}
          className="text-xs bg-zinc-100 dark:bg-zinc-800 rounded px-2 py-1 outline-none border border-zinc-200 dark:border-zinc-700"
          style={{ color: "var(--color-text)" }}>
          {LAYER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <button onClick={() => setShowAddForm(!showAddForm)}
          className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium text-white bg-violet-500 hover:bg-violet-600 transition-colors shrink-0">
          <Plus size={13} /> 添加
        </button>
      </div>

      {/* 添加表单 */}
      {showAddForm && (
        <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 bg-violet-50 dark:bg-violet-950/30 shrink-0">
          <div className="flex items-center gap-2 mb-2" style={{ color: "var(--color-text)" }}>
            <Plus size={13} className="text-violet-500" />
            <span className="text-xs font-medium text-violet-700 dark:text-violet-300">添加新记忆</span>
            <button onClick={() => setShowAddForm(false)} className="ml-auto p-0.5 rounded text-zinc-400 hover:text-zinc-600"><X size={13} /></button>
          </div>
          <div className="grid grid-cols-4 gap-2 mb-2">
            <select value={addLayer} onChange={(e) => setAddLayer(e.target.value)}
              className="text-xs bg-white dark:bg-zinc-900 rounded px-2 py-1.5 outline-none border border-zinc-200 dark:border-zinc-700"
              style={{ color: "var(--color-text)" }}>
              {LAYER_OPTIONS.filter((o) => o.value).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <input value={addKey} onChange={(e) => setAddKey(e.target.value)} placeholder="key"
              className="col-span-1 text-xs bg-white dark:bg-zinc-900 rounded px-2 py-1.5 outline-none border border-zinc-200 dark:border-zinc-700" style={{ color: "var(--color-text)" }} />
            <input value={addImportance} onChange={(e) => setAddImportance(parseFloat(e.target.value) || 0)} type="number" step="0.1" min="0" max="1"
              className="text-xs bg-white dark:bg-zinc-900 rounded px-2 py-1.5 outline-none border border-zinc-200 dark:border-zinc-700 w-16"
              style={{ color: "var(--color-text)" }} title="重要性 0-1" />
          </div>
          <textarea value={addValue} onChange={(e) => setAddValue(e.target.value)} placeholder="value…"
            className="w-full text-xs bg-white dark:bg-zinc-900 rounded px-2 py-1.5 outline-none border border-zinc-200 dark:border-zinc-700 mb-2" rows={2}
            style={{ color: "var(--color-text)", resize: "vertical" }} />
          {addError && <div className="text-[10px] text-red-500 mb-2">{addError}</div>}
          <button onClick={doAdd}
            className="px-3 py-1 rounded text-xs font-medium text-white bg-violet-500 hover:bg-violet-600 transition-colors">
            确认添加
          </button>
        </div>
      )}

      {/* 记忆列表 */}
      <div className="flex-1 overflow-auto">
        {entriesLoading && <Skeleton lines={5} />}
        {!entriesLoading && entries.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-16 text-zinc-400 text-xs">
            <Layers size={24} strokeWidth={1.2} />
            <span>{searchKeyword ? "没有匹配结果" : "暂无记忆条目"}</span>
            {!searchKeyword && <span className="text-[10px]">点击「添加」创建第一条手动记忆</span>}
          </div>
        )}
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {entries.map((entry) => {
            const meta = LAYER_META[entry.layer] || { label: entry.layer, color: "zinc" };
            const isEditing = editId === entry.id;
            const isConfirming = confirmDelId === entry.id;
            return (
              <div key={entry.id} className="px-4 py-2.5 hover:bg-zinc-50 dark:hover:bg-zinc-900/50 transition-colors group">
                <div className="flex items-start gap-2">
                  {/* 层标签 */}
                  <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-${meta.color}-100 text-${meta.color}-700 dark:bg-${meta.color}-900/40 dark:text-${meta.color}-300`}>
                    {meta.label}
                  </span>
                  {/* key */}
                  <span className="text-xs font-mono font-medium shrink-0" style={{ color: "var(--color-text)" }}>
                    {entry.key}
                  </span>
                  {/* value — 可编辑 */}
                  <div className="flex-1 min-w-0">
                    {isEditing ? (
                      <textarea autoFocus value={editValue} onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Escape") cancelEdit(); if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveEdit(entry.id); } }}
                        className="w-full text-xs rounded px-1.5 py-0.5 outline-none border border-violet-400 bg-white dark:bg-zinc-900 resize-vertical"
                        style={{ color: "var(--color-text)" }} rows={2} />
                    ) : (
                      <span className="text-xs text-zinc-600 dark:text-zinc-300 line-clamp-2 break-all">{entry.value}</span>
                    )}
                  </div>
                  {/* 操作按钮 */}
                  <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                    {/* 重要性指示 */}
                    <span className="text-[10px] text-zinc-400 mr-1" title={`重要性 ${entry.importance}`}>
                      {entry.importance >= 0.8 ? "⭐⭐⭐" : entry.importance >= 0.5 ? "⭐⭐" : "⭐"}
                    </span>
                    {isEditing ? (
                      <>
                        <button onClick={() => saveEdit(entry.id)} title="保存" className="p-1 rounded text-emerald-500 hover:text-emerald-400 hover:bg-emerald-500/10 transition-colors"><Check size={13} /></button>
                        <button onClick={cancelEdit} title="取消" className="p-1 rounded text-zinc-400 hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"><X size={13} /></button>
                      </>
                    ) : isConfirming ? (
                      <>
                        <button onClick={() => doDelete(entry.id)} title="确认删除" className="p-1 rounded text-red-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"><Check size={13} /></button>
                        <button onClick={() => setConfirmDelId(null)} title="取消" className="p-1 rounded text-zinc-400 hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"><X size={13} /></button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => doEdit(entry)} title="编辑" className="p-1 rounded text-zinc-400 hover:text-violet-400 hover:bg-violet-500/10 transition-colors"><PencilLine size={13} /></button>
                        <button onClick={() => setConfirmDelId(entry.id)} title="删除" className="p-1 rounded text-zinc-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"><Trash2 size={13} /></button>
                      </>
                    )}
                  </div>
                </div>
                {/* 元信息 */}
                <div className="flex gap-3 mt-1 ml-20 text-[10px] text-zinc-400">
                  <span className="flex items-center gap-1"><Clock size={9} /> {fmtTime(entry.created_at)}</span>
                  <span>引擎: {entry.engine}</span>
                  <span>重要性: {entry.importance.toFixed(1)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {/* 底栏计数 */}
      <div className="px-4 py-1.5 border-t border-zinc-200 dark:border-zinc-800 text-[10px] text-zinc-400 bg-white dark:bg-zinc-900 shrink-0">
        {entries.length} 条
      </div>
    </div>
  );

  return (
    <main className="flex-1 flex flex-col overflow-hidden bg-zinc-50 dark:bg-zinc-950">
      {/* Tab 栏 */}
      <div className="flex items-center gap-0.5 px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0">
        {[
          { key: "memory", label: "8层记忆", icon: <Brain size={13} /> },
          { key: "browse", label: "浏览记忆", icon: <Search size={13} /> },
          { key: "knowledge", label: "知识检索", icon: <BookOpen size={13} /> },
          { key: "evolution", label: "进化追踪", icon: <Dna size={13} /> },
        ].map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-all ${
              tab === t.key ? "bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400" : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
            }`}>
            {t.icon}{t.label}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-zinc-400">认知中枢 · {stats ? `${total} 条` : ""}</span>
      </div>

      {tab === "memory" ? <div className="flex-1 overflow-auto"><StatsView /></div> : <BrowseView />}
    </main>
  );
}
