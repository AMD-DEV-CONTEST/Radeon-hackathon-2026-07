// Grok Build 代码引擎控制台（v0.2.111 完整嵌入）
// 数据源：
//   GET  /api/grok/health / models / capabilities / inspect
//   POST /api/grok/run  → headless 真实执行
// 风格严格遵循 XAI_DESIGN_STANDARD：main + 白/暗双主题卡片 + lucide 图标，不改全局风格。

import { useEffect, useState, useMemo } from "react";
import {
  Cpu, Loader2, AlertCircle, RefreshCw, CircleDot, Play, Terminal,
  CheckCircle2, Layers, ShieldCheck, Zap, Info, Network, ChevronDown, ChevronUp,
  History, Trash2,
} from "lucide-react";
import { MiniCanvas } from "./MiniCanvas";
import {
  fetchGrokHealth, fetchGrokModels, fetchGrokCapabilities, fetchGrokInspect, runGrok,
  fetchGrokModel, setGrokModel, requestGrokWrite,
  fetchGrokHistory, fetchGrokHistoryItem, deleteGrokHistory,
  type GrokHealth, type GrokModels, type GrokCapabilities, type GrokRunResult, type GrokModelPref,
  type CanvasData, type GrokHistoryItem,
} from "./lib/api";

export default function GrokConsole() {
  const [health, setHealth] = useState<GrokHealth | null>(null);
  const [models, setModels] = useState<GrokModels | null>(null);
  const [caps, setCaps] = useState<GrokCapabilities | null>(null);
  const [inspect, setInspect] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 执行区状态
  const [task, setTask] = useState("");
  const [model, setModel] = useState("");
  const [check, setCheck] = useState(false);
  const [bestOfN, setBestOfN] = useState(false);
  const [disableWeb, setDisableWeb] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<GrokRunResult | null>(null);
  const [runErr, setRunErr] = useState("");
  const [grokPref, setGrokPref] = useState<GrokModelPref | null>(null);

  // Grok 写操作 → Guardian 审批工单（提交后工单出现在 Guardian Center 待审批）
  const [grokWriteReq, setGrokWriteReq] = useState<{ ok: boolean; id: string; status: string } | null>(null);
  const [requestingWrite, setRequestingWrite] = useState(false);

  // 布局 v2（2026-07-27）：能力清单 / 配置发现默认收起为抽屉，主工作区全宽
  const [showCaps, setShowCaps] = useState(false);
  const [showInspect, setShowInspect] = useState(false);

  // 运行历史抽屉（XAI 自有，每次 run 后自动落盘；点击恢复 task+结果+画布）
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<GrokHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyErr, setHistoryErr] = useState("");
  const [restoring, setRestoring] = useState<string | null>(null);

  // 同步模型可能不在 grok 原生清单内（如 deepseek-pro 来自引擎推导），确保下拉可选项包含它
  const modelOptions = useMemo(() => {
    const base = models?.models || [];
    if (grokPref?.ok && grokPref.model && !base.includes(grokPref.model)) return [...base, grokPref.model];
    return base;
  }, [models, grokPref]);

  // 把 grok 产出解析成 MiniCanvas 节点图（复用会话画布同款渲染/动画）
  const grokCanvas = useMemo<CanvasData | null>(
    () => (result ? grokResultToCanvas(result, task) : null),
    [result, task]
  );

  const loadHistory = () => {
    setHistoryLoading(true);
    fetchGrokHistory().then((d) => setHistory(d.runs || [])).catch(() => {}).finally(() => setHistoryLoading(false));
  };

  const load = () => {
    setLoading(true);
    setError("");
    let defaultModel = "";
    Promise.all([
      fetchGrokHealth().then(setHealth).catch(() => setHealth(null)),
      fetchGrokModels().then((m) => { setModels(m); defaultModel = m.default || ""; }).catch(() => {}),
      fetchGrokCapabilities().then(setCaps).catch(() => {}),
      fetchGrokInspect().then((r) => setInspect(r.output || r.error || "")).catch(() => {}),
      fetchGrokModel().then((p) => {
        setGrokPref(p);
        // 预选：优先同步模型（engine 推导或用户偏好），空白时才退回 grok 默认
        if (p.ok && p.model) setModel(p.model);
        else if (defaultModel) setModel(defaultModel);
      }).catch(() => {}),
      // 运行历史随主加载一起拉取（失败静默，不阻断主区）
      fetchGrokHistory().then((d) => setHistory(d.runs || [])).catch(() => {}),
    ]).catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const online = health?.grok_build_bridge === "available";

  const doRun = async () => {
    if (!task.trim() || running) return;
    setRunning(true);
    setRunErr("");
    setResult(null);
    setGrokWriteReq(null);
    try {
      const r = await runGrok({
        task: task.trim(),
        model,
        check,
        best_of_n: bestOfN ? 3 : 0,
        disable_web: disableWeb,
        timeout: 300,
      });
      setResult(r);
      // 运行成功后自动刷新历史（后端已落盘，这里让列表立即出现新条目）
      fetchGrokHistory().then((d) => setHistory(d.runs || [])).catch(() => {});
    } catch (e: any) {
      setRunErr(e?.message || "执行失败");
    } finally {
      setRunning(false);
    }
  };

  // 从历史恢复：回填 task + 完整 result_json（画布由 grokResultToCanvas 自动重算）
  const restoreHistory = async (id: string) => {
    if (restoring) return;
    setRestoring(id);
    setHistoryErr("");
    try {
      const rec = await fetchGrokHistoryItem(id);
      setTask(rec.task || "");
      if (rec.model) setModel(rec.model);
      setResult(rec.result_json || {});
      setRunErr("");
      setGrokWriteReq(null);
      setShowHistory(false);
    } catch (e: any) {
      setHistoryErr(e?.message || "恢复失败");
    } finally {
      setRestoring(null);
    }
  };

  // 删除一条历史记录
  const removeHistory = async (id: string) => {
    try {
      await deleteGrokHistory(id);
      setHistory((h) => h.filter((x) => x.id !== id));
    } catch (e: any) {
      setHistoryErr(e?.message || "删除失败");
    }
  };

  // 把当前任务作为「Grok 写操作」提交 Guardian 审批（type=grok_write）
  const requestWrite = async () => {
    if (!task.trim() || requestingWrite) return;
    setRequestingWrite(true);
    setRunErr("");
    try {
      const r = await requestGrokWrite(task.trim());
      setGrokWriteReq(r);
    } catch (e: any) {
      setRunErr(e?.message || "提交审批失败");
    } finally {
      setRequestingWrite(false);
    }
  };

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      {/* 标题 + 健康状态 */}
      <div className="flex items-center gap-2 mb-1">
        <Cpu size={18} />
        <h2 className="text-lg font-semibold">Grok Build 代码引擎</h2>
        <span className={`ml-2 flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full ${
          online
            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
            : "bg-zinc-100 text-zinc-400 dark:bg-zinc-800"
        }`}>
          <CircleDot size={9} />{online ? "在线" : "离线"}
        </span>
        <button onClick={load} title="刷新" className="ml-auto p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      {/* 紧凑状态栏：状态灯 + 数字摘要 + 抽屉开关（替代原右侧大块状态卡片） */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-4 text-xs text-zinc-400">
        <span>{health?.version ? `${health.version} · ${health.binary}` : "本地 grok 二进制 headless 桥接"}</span>
        {models && <span>· {models.count ?? models.models.length} 个模型</span>}
        <button onClick={() => { setShowCaps(!showCaps); setShowInspect(false); }}
          title="查看已接通能力清单"
          className={`flex items-center gap-1 px-2 py-0.5 rounded-full border transition-colors ${
            showCaps
              ? "border-purple-300 text-purple-600 bg-purple-50 dark:bg-purple-900/20 dark:text-purple-300 dark:border-purple-800"
              : "border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          }`}>
          <Layers size={11} className="text-purple-500" /> 能力 {caps?.capabilities.length || 0} 项
          {showCaps ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
        {inspect && (
          <button onClick={() => { setShowInspect(!showInspect); setShowCaps(false); }}
            title="查看 grok inspect 配置发现"
            className={`flex items-center gap-1 px-2 py-0.5 rounded-full border transition-colors ${
              showInspect
                ? "border-sky-300 text-sky-600 bg-sky-50 dark:bg-sky-900/20 dark:text-sky-300 dark:border-sky-800"
                : "border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}>
            <Info size={11} className="text-sky-500" /> 配置发现
            {showInspect ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
        )}
        <button onClick={() => { setShowHistory(!showHistory); setShowCaps(false); setShowInspect(false); if (!showHistory) loadHistory(); }}
          title="查看 / 恢复运行历史"
          className={`flex items-center gap-1 px-2 py-0.5 rounded-full border transition-colors ${
            showHistory
              ? "border-amber-300 text-amber-600 bg-amber-50 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800"
              : "border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          }`}>
          <History size={11} className="text-amber-500" /> 历史 {history.length} 条
          {showHistory ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
      </div>

      {loading && <div className="flex items-center gap-2 justify-center py-10 text-zinc-400 text-xs"><Loader2 size={14} className="animate-spin" /> 加载 Grok Build 状态…</div>}
      {error && <div className="flex items-center gap-2 text-red-500 text-xs mb-4"><AlertCircle size={14} /> {error}</div>}

      {/* 能力清单抽屉（默认收起；横向卡片流，不再占常驻侧栏） */}
      {!loading && showCaps && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800 mb-4">
          <div className="flex items-center gap-2 mb-3">
            <Layers size={15} className="text-purple-500" />
            <span className="text-sm font-medium">已接通能力</span>
            <span className="ml-auto text-[10px] text-zinc-400">{caps?.capabilities.length || 0} 项</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-2 max-h-56 overflow-auto">
            {(caps?.capabilities || []).map((c) => (
              <div key={c.id} className="flex items-start gap-2 p-2 rounded-lg bg-zinc-50 dark:bg-zinc-950 border border-zinc-100 dark:border-zinc-800">
                <CheckCircle2 size={13} className="text-emerald-500 mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <div className="text-xs font-medium truncate">{c.name}</div>
                  <div className="text-[10px] text-zinc-400 font-mono truncate">{c.flag}</div>
                  <div className="text-[10px] text-zinc-400 dark:text-zinc-500 line-clamp-2">{c.desc}</div>
                </div>
              </div>
            ))}
            {!caps?.capabilities.length && <div className="text-[11px] text-zinc-400">暂无能力数据</div>}
          </div>
        </div>
      )}

      {/* 配置发现抽屉（默认收起） */}
      {!loading && showInspect && inspect && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800 mb-4">
          <div className="flex items-center gap-2 mb-2">
            <Info size={15} className="text-zinc-400" />
            <span className="text-sm font-medium">配置发现</span>
            <span className="text-[10px] text-zinc-400 font-mono ml-auto">grok inspect</span>
          </div>
          <pre className="text-[10px] whitespace-pre-wrap break-words text-zinc-500 dark:text-zinc-400 leading-relaxed max-h-56 overflow-auto">{inspect}</pre>
        </div>
      )}

      {/* 运行历史抽屉（默认收起；列出每次 run，点击恢复 task+结果+画布） */}
      {!loading && showHistory && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800 mb-4">
          <div className="flex items-center gap-2 mb-3">
            <History size={15} className="text-amber-500" />
            <span className="text-sm font-medium">运行历史</span>
            <span className="ml-auto text-[10px] text-zinc-400 font-mono">{history.length} 条 · 点击恢复</span>
          </div>
          {historyLoading && <div className="flex items-center gap-2 text-xs text-zinc-400 py-2"><Loader2 size={13} className="animate-spin" /> 加载历史…</div>}
          {historyErr && <div className="flex items-center gap-2 text-red-500 text-xs py-1"><AlertCircle size={13} /> {historyErr}</div>}
          {!historyLoading && !historyErr && history.length === 0 && (
            <div className="text-[11px] text-zinc-400 py-2">暂无运行历史（执行一次后会自动记录）</div>
          )}
          <div className="flex flex-col gap-1.5 max-h-72 overflow-auto">
            {history.map((it) => (
              <div key={it.id} className="group flex items-start gap-2 p-2 rounded-lg border border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-950">
                <button onClick={() => restoreHistory(it.id)} disabled={restoring === it.id}
                  title="恢复此运行：回填任务并还原结果与画布"
                  className="flex-1 min-w-0 text-left disabled:opacity-50">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                      it.ok
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
                        : "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300"
                    }`}>{it.ok ? "成功" : "失败"}</span>
                    <span className="text-[10px] text-zinc-400">{new Date(it.ts * 1000).toLocaleString()}</span>
                    {it.model && <span className="text-[10px] text-zinc-400 font-mono truncate">{it.model}</span>}
                  </div>
                  <div className="text-xs text-zinc-700 dark:text-zinc-200 truncate mt-0.5">{it.summary || it.task || "(无摘要)"}</div>
                </button>
                <button onClick={() => removeHistory(it.id)} title="删除该记录"
                  className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-50 dark:hover:bg-red-950/40 text-zinc-400 hover:text-red-500 transition-opacity shrink-0">
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {!loading && (
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-4">
          {/* 左：执行 + 结果（竖排，操作主轴） */}
          <div className="flex flex-col gap-4 min-w-0">
            <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-2 mb-3">
                <Terminal size={15} className="text-blue-500" />
                <span className="text-sm font-medium">Headless 代码执行</span>
                <span className="text-[10px] text-zinc-400 font-mono ml-auto">POST /api/grok/run</span>
              </div>

              <textarea
                value={task}
                onChange={(e) => { setTask(e.target.value); setGrokWriteReq(null); }}
                placeholder="描述一个代码任务，例如：为这个仓库的 memory_core.py 写一个单元测试"
                rows={4}
                className="w-full text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 p-3 outline-none focus:border-blue-400 resize-y"
              />

              {/* 选项行 */}
              <div className="flex flex-wrap items-center gap-3 mt-3">
                <label className="flex items-center gap-1.5 text-xs text-zinc-500">
                  <span className="text-zinc-400">模型</span>
                  <select value={model} onChange={(e) => { const v = e.target.value; setModel(v); setGrokModel(v).then(() => fetchGrokModel().then(setGrokPref).catch(() => {})).catch(() => {}) }}
                    className="text-xs rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1 outline-none">
                    {modelOptions.map((m) => (
                      <option key={m} value={m}>{m}{m === models?.default ? " (默认)" : ""}</option>
                    ))}
                  </select>
                  {grokPref && grokPref.ok && model && grokPref.engine_derived && model === grokPref.engine_derived && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300" title="该模型与 XAI 引擎激活模型一致（自动同步）">
                      🔗 已与引擎同步
                    </span>
                  )}
                  {grokPref && grokPref.ok && model && grokPref.engine_derived && model !== grokPref.engine_derived && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300" title="手动指定的 Grok 模型，与引擎激活模型不同">
                      手动指定
                    </span>
                  )}
                </label>
                <label className="flex items-center gap-1.5 text-xs text-zinc-500 cursor-pointer">
                  <input type="checkbox" checked={check} onChange={(e) => setCheck(e.target.checked)} className="accent-blue-500" />
                  <ShieldCheck size={13} className="text-emerald-500" /> 自验证 --check <span className="text-[10px] text-zinc-400">（当前版本不支持）</span>
                </label>
                <label className="flex items-center gap-1.5 text-xs text-zinc-500 cursor-pointer">
                  <input type="checkbox" checked={bestOfN} onChange={(e) => setBestOfN(e.target.checked)} className="accent-blue-500" />
                  <Zap size={13} className="text-amber-500" /> 并行 3 路 <span className="text-[10px] text-zinc-400">（当前版本不支持）</span>
                </label>
                <label className="flex items-center gap-1.5 text-xs text-zinc-500 cursor-pointer">
                  <input type="checkbox" checked={disableWeb} onChange={(e) => setDisableWeb(e.target.checked)} className="accent-blue-500" />
                  离线（禁联网）
                </label>
                <button onClick={requestWrite} disabled={requestingWrite || !task.trim() || !online}
                  title="把当前任务作为 Grok 写操作提交 Guardian 审批（工单将出现在 Guardian Center）"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-amber-300 text-amber-600 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-900/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                  {requestingWrite ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />}
                  提交写操作审批
                </button>
                <button onClick={doRun} disabled={running || !task.trim() || !online}
                  className="ml-auto flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                  {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                  {running ? "执行中…" : "执行"}
                </button>
                {grokWriteReq && (
                  <span className="text-[11px] text-amber-500">审批工单 {grokWriteReq.id} · {grokWriteReq.status}</span>
                )}
              </div>
            </div>

            {/* 结果区 */}
            {runErr && (
              <div className="flex items-center gap-2 text-red-500 text-xs bg-red-50 dark:bg-red-950/40 rounded-lg p-3 border border-red-200 dark:border-red-900">
                <AlertCircle size={14} /> {runErr}
              </div>
            )}
            {result && (
              <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
                <div className="flex items-center gap-2 mb-3">
                  <CheckCircle2 size={15} className="text-emerald-500" />
                  <span className="text-sm font-medium">执行结果</span>
                  <div className="ml-auto flex items-center gap-3 text-[10px] text-zinc-400 font-mono">
                    {result.num_turns != null && <span>{result.num_turns} turns</span>}
                    {result.usage?.total_tokens != null && <span>{result.usage.total_tokens} tokens</span>}
                    {result.truncated && <span className="text-amber-500">已截断</span>}
                  </div>
                </div>
                <pre className="text-xs whitespace-pre-wrap break-words text-zinc-700 dark:text-zinc-200 leading-relaxed max-h-[600px] overflow-auto">
                  {result.text || result.raw || result.partial_output || result.error || "（无输出）"}
                </pre>
                {result.thought && (
                  <details className="mt-3" open>
                    <summary className="text-[11px] text-zinc-400 cursor-pointer select-none">思考链</summary>
                    <pre className="text-[11px] whitespace-pre-wrap break-words text-zinc-400 mt-2 leading-relaxed max-h-64 overflow-auto">{result.thought}</pre>
                  </details>
                )}
              </div>
            )}
          </div>

          {/* 右：产出可视化（与执行/结果同窗口对照，方便盯产出结构） */}
          <div className="flex flex-col gap-4 min-w-0">
            {grokCanvas ? (
              <div className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800 xl:sticky xl:top-4">
                <div className="flex items-center gap-2 mb-3">
                  <Network size={15} className="text-sky-500" />
                  <span className="text-sm font-medium">产出可视化</span>
                  <span className="text-[10px] text-zinc-400 font-mono ml-auto">MiniCanvas · {grokCanvas.nodes.length} 节点</span>
                </div>
                <div className="rounded-lg overflow-hidden border border-zinc-200 dark:border-zinc-800" style={{ minHeight: 560 }}>
                  <MiniCanvas nodes={grokCanvas.nodes} edges={grokCanvas.edges} onPersist={() => {}} />
                </div>
                {!result && (
                  <div className="mt-3 text-[11px] text-zinc-400 text-center">执行后将自动生成产出节点图</div>
                )}
              </div>
            ) : (
              <div className="hidden xl:flex bg-white dark:bg-zinc-900 rounded-xl p-4 border border-dashed border-zinc-200 dark:border-zinc-800 h-full min-h-[280px] items-center justify-center text-xs text-zinc-400 text-center">
                <div>
                  <Network size={28} className="mx-auto mb-2 text-sky-400 opacity-60" />
                  执行任务后，产出可视化（节点图）将在此实时呈现
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

// ── Grok 产出 → MiniCanvas 节点图（复用会话画布同款渲染/动画）──
// 节点配色严格走 XAI 设计令牌（--color-node-*-*），不改全局风格。
const GROK_NODE_STYLE: Record<string, { bg: string; border: string; color: string }> = {
  system: { bg: "var(--color-node-system-bg)", border: "var(--color-node-system-border)", color: "var(--color-node-system)" },
  ai:     { bg: "var(--color-node-ai-bg)", border: "var(--color-node-ai-border)", color: "var(--color-node-ai)" },
  output: { bg: "var(--color-node-output-bg)", border: "var(--color-node-output-border)", color: "var(--color-node-output)" },
  logic:  { bg: "var(--color-node-logic-bg)", border: "var(--color-node-logic-border)", color: "var(--color-node-logic)" },
  data:   { bg: "var(--color-node-data-bg)", border: "var(--color-node-data-border)", color: "var(--color-node-data)" },
};

function grokMakeNode(id: string, label: string, kind: keyof typeof GROK_NODE_STYLE, x: number, y: number) {
  const s = GROK_NODE_STYLE[kind];
  return {
    id,
    position: { x, y },
    type: "default",
    data: { label },
    style: {
      background: s.bg,
      border: "1px solid " + s.border,
      color: s.color,
      borderRadius: 10,
      padding: 8,
      fontSize: 11.5,
      width: 240,
      whiteSpace: "pre-line",
    },
  };
}

// 把 grok 自由文本产出切成 60 字以内的语义块（长行再切分，避免单节点过长）
function grokParseBlocks(text: string, max = 24): string[] {
  const t = (text || "").trim();
  if (!t) return [];
  const out: string[] = [];
  for (const raw of t.split(/\n{1,}/)) {
    const s = raw.trim().replace(/\s+/g, " ");
    if (!s) continue;
    if (s.length <= 60) {
      out.push(s.slice(0, 60));
    } else {
      for (let i = 0; i < s.length; i += 60) {
        out.push(s.slice(i, i + 60) + (i + 60 < s.length ? "…" : ""));
      }
    }
  }
  return out.filter(Boolean).slice(0, max);
}

function grokResultToCanvas(result: GrokRunResult, task: string): CanvasData {
  const nodes: any[] = [];
  const edges: any[] = [];
  nodes.push(
    grokMakeNode("task", "📋 任务\n" + (task || "(未提供)").replace(/\s+/g, " ").trim().slice(0, 46), "system", 320, 20)
  );
  const thought = (result.thought || "").trim();
  if (thought) {
    nodes.push(
      grokMakeNode("thought", "🧠 思考链\n" + thought.replace(/\s+/g, " ").slice(0, 46) + (thought.length > 46 ? "…" : ""), "ai", 20, 20)
    );
    edges.push({ id: "e_task_thought", source: "task", target: "thought" });
  }
  const blocks = grokParseBlocks(result.text || result.raw || result.partial_output || result.error || "");
  blocks.forEach((b, i) => {
    const id = "out_" + i;
    nodes.push(grokMakeNode(id, b, "output", 600, 20 + i * 64));
    edges.push({ id: "e_prev_" + id, source: i === 0 ? "task" : "out_" + (i - 1), target: id });
  });
  const lastId = blocks.length ? "out_" + (blocks.length - 1) : "task";
  const meta = [
    result.num_turns != null ? `${result.num_turns} turns` : null,
    result.usage?.total_tokens != null ? `${result.usage.total_tokens} tokens` : null,
    result.truncated ? "已截断" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  nodes.push(
    grokMakeNode("summary", "📊 产出统计\n" + (meta || "（无结构化产出）"), "logic", 320, 20 + (blocks.length + 1) * 64)
  );
  edges.push({ id: "e_last_summary", source: lastId, target: "summary" });
  return { id: "grok_" + Date.now(), nodes, edges };
}
