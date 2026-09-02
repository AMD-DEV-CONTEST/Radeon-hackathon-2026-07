// XAI 验收调试台（界面驱动黑盒调试员模式）
// 只读测量面板：调用 GET /api/acceptance（实时六维）、GET /api/acceptance/history（账本）、
// POST /api/acceptance/run（触发只读探针跑批）。本面板绝不修改内核 / 记忆 / Guardian。
import { useEffect, useState, useCallback } from "react";
import type { ReactNode } from "react";
import {
  ClipboardCheck, RefreshCw, Loader2, AlertTriangle, Gauge, Shield,
  Database, Activity, Scale, CheckCircle2, TrendingUp, TrendingDown, Minus,
} from "lucide-react";
import {
  fetchAcceptance, fetchAcceptanceHistory, runAcceptance,
  type AcceptanceSnapshot, type AcceptanceRecord, type AcceptanceDim, type AcceptanceStatus,
} from "./lib/api";

const DIM_ICON: Record<string, ReactNode> = {
  functional: <CheckCircle2 size={18} />,
  performance: <Gauge size={18} />,
  security: <Shield size={18} />,
  data: <Database size={18} />,
  ops: <Activity size={18} />,
  honesty: <Scale size={18} />,
};

const STATUS_STYLE: Record<AcceptanceStatus, { label: string; color: string; bg: string }> = {
  pass:    { label: "通过", color: "#10b981", bg: "rgba(16,185,129,0.12)" },
  warn:    { label: "警告", color: "#f59e0b", bg: "rgba(245,158,11,0.12)" },
  fail:    { label: "失败", color: "#ef4444", bg: "rgba(239,68,68,0.12)" },
  partial: { label: "部分", color: "#818cf8", bg: "rgba(129,140,248,0.12)" },
  unknown: { label: "未知", color: "#94a3b8", bg: "rgba(148,163,184,0.12)" },
};

const SRC_LABEL: Record<string, string> = { probe: "探针", live: "实时", ledger: "账本" };

function StatusPill({ status }: { status: AcceptanceStatus }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.unknown;
  return (
    <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: s.bg, color: s.color }}>
      {s.label}
    </span>
  );
}

function DimCard({ dim }: { dim: AcceptanceDim }) {
  const s = STATUS_STYLE[dim.status] || STATUS_STYLE.unknown;
  return (
    <div className="rounded-xl p-3 border" style={{ borderColor: "rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)" }}>
      <div className="flex items-center gap-2">
        <span style={{ color: s.color }} className="opacity-80">{DIM_ICON[dim.key] || <CheckCircle2 size={18} />}</span>
        <span className="text-[13px] font-medium flex-1">{dim.cn}</span>
        <StatusPill status={dim.status} />
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.08)" }}>
          <div className="h-full rounded-full" style={{ width: `${dim.status === "unknown" ? 0 : dim.score}%`, background: s.color }} />
        </div>
        <span className="text-[12px] font-mono tabular-nums" style={{ color: s.color }}>{dim.status === "unknown" ? "—" : dim.score}</span>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <span className="text-[10px] text-zinc-500 shrink-0">{SRC_LABEL[dim.source] || dim.source}</span>
        <span className="text-[10px] text-zinc-500 truncate text-right" title={dim.detail}>{dim.detail}</span>
      </div>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const w = 240, h = 44, pad = 6;
  const min = Math.min(...values, 0), max = Math.max(...values, 100);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = pad + (i * (w - pad * 2)) / (values.length - 1);
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const last = values[values.length - 1];
  const lastX = pad + (values.length - 1) * (w - pad * 2) / (values.length - 1);
  const lastY = h - pad - ((last - min) / span) * (h - pad * 2);
  return (
    <svg width={w} height={h} className="block">
      <polyline points={pts} fill="none" stroke="#a78bfa" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r={3} fill="#a78bfa" />
    </svg>
  );
}

export default function AcceptancePanel() {
  const [snap, setSnap] = useState<AcceptanceSnapshot | null>(null);
  const [history, setHistory] = useState<AcceptanceRecord[]>([]); // 新→旧
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compare, setCompare] = useState<{ prev: AcceptanceRecord | null; curr: AcceptanceRecord } | null>(null);

  const loadSnapshot = useCallback(() => {
    return fetchAcceptance().then(setSnap).catch((e) => setError(String(e?.message || e)));
  }, []);

  const loadHistory = useCallback(() => {
    return fetchAcceptanceHistory(30)
      .then((h) => setHistory([...(h.runs || [])].reverse()))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadSnapshot(), loadHistory()]).finally(() => setLoading(false));
  }, [loadSnapshot, loadHistory]);

  const handleRun = async () => {
    setError(null);
    setRunning(true);
    const prev = history[0] || null;
    try {
      const rec = await runAcceptance();
      setCompare({ prev, curr: rec });
      await Promise.all([loadSnapshot(), loadHistory()]);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setRunning(false);
    }
  };

  const overall = snap?.overall;
  const overallStyle = overall ? (STATUS_STYLE[overall.status] || STATUS_STYLE.unknown) : STATUS_STYLE.unknown;

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">
        {/* 头部 */}
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0" style={{ background: "linear-gradient(135deg,#7c3aed,#6366f1)" }}>
            <ClipboardCheck size={20} className="text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-semibold">验收调试台</h1>
            <p className="text-[12px] text-zinc-500">界面驱动黑盒调试员模式 · 只读测量，不修改系统（修复须经 Guardian 闸门）</p>
          </div>
          {overall && (
            <div className="text-right shrink-0">
              <div className="text-3xl font-bold font-mono" style={{ color: overallStyle.color }}>{overall.score}</div>
              <StatusPill status={overall.status} />
              <div className="text-[10px] text-zinc-500 mt-1">上次跑批：{snap?.last_run || "—"}</div>
            </div>
          )}
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl px-3 py-2 text-[12px]" style={{ background: "rgba(239,68,68,0.1)", color: "#ef4444" }}>
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* 六维全景 */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-[13px] font-semibold text-zinc-400 uppercase tracking-wider">六维实时全景</h2>
            {snap && <span className="text-[10px] text-zinc-500">快照 {snap.ts_human} · {snap.mode}</span>}
          </div>
          {loading && !snap ? (
            <div className="flex items-center gap-2 text-zinc-500 text-[12px]"><Loader2 size={14} className="animate-spin" /> 加载中…</div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {(snap?.dims || []).map((d) => <DimCard key={d.key} dim={d} />)}
            </div>
          )}
          {snap && <p className="text-[10px] text-zinc-500 mt-2">{snap.note}</p>}
        </section>

        {/* 操作 */}
        <section className="flex items-center gap-3 rounded-xl p-4" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
          <button
            onClick={handleRun}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-[13px] font-medium text-white transition-all disabled:opacity-60"
            style={{ background: "linear-gradient(135deg,#7c3aed,#6366f1)", boxShadow: "0 2px 8px rgba(124,58,237,0.25)" }}>
            {running ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            {running ? "跑批中…(约 30s)" : "运行验收跑批"}
          </button>
          <span className="text-[11px] text-zinc-500">触发 honesty / smoke / security 三套只读黑盒探针，计算六维评分并写入验收账本。限频 60s。</span>
        </section>

        {/* 本次 vs 上次对比 */}
        {compare && (
          <section className="rounded-xl p-4 space-y-2" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <h2 className="text-[13px] font-semibold text-zinc-400 uppercase tracking-wider">本次 vs 上次</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {compare.curr.dims.map((d) => {
                const p = compare.prev?.dims.find((x) => x.key === d.key);
                const delta = p ? d.score - p.score : 0;
                const dc = delta > 0 ? "#10b981" : delta < 0 ? "#ef4444" : "#94a3b8";
                const Arrow = delta > 0 ? TrendingUp : delta < 0 ? TrendingDown : Minus;
                return (
                  <div key={d.key} className="flex items-center justify-between rounded-lg px-3 py-2" style={{ background: "rgba(255,255,255,0.03)" }}>
                    <span className="text-[12px]">{d.cn}</span>
                    <span className="flex items-center gap-1.5 text-[12px] font-mono">
                      <span className="text-zinc-500">{p ? p.score : "—"}</span>
                      <Arrow size={12} style={{ color: dc }} />
                      <span style={{ color: (STATUS_STYLE[d.status] || STATUS_STYLE.unknown).color }}>{d.score}</span>
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="text-[10px] text-zinc-500">
              本次总分 {compare.curr.overall.score}（{(STATUS_STYLE[compare.curr.overall.status] || STATUS_STYLE.unknown).label}） · {compare.curr.ts_human}
            </div>
          </section>
        )}

        {/* 账本趋势 */}
        <section>
          <h2 className="text-[13px] font-semibold text-zinc-400 uppercase tracking-wider mb-3">验收账本趋势</h2>
          {history.length === 0 ? (
            <div className="text-[12px] text-zinc-500">暂无跑批记录，点击上方「运行验收跑批」生成首条。</div>
          ) : (
            <>
              <div className="rounded-xl p-4 mb-3" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div className="text-[10px] text-zinc-500 mb-2">总分走势（旧 → 新，共 {history.length} 条）</div>
                <Sparkline values={[...history].reverse().map((r) => r.overall.score)} />
              </div>
              <div className="space-y-1.5">
                {history.map((r, i) => (
                  <div key={r.ts + "-" + i} className="flex items-center gap-3 rounded-lg px-3 py-2" style={{ background: "rgba(255,255,255,0.03)" }}>
                    <span className="text-[12px] font-mono text-zinc-400 w-36 shrink-0">{r.ts_human}</span>
                    <StatusPill status={r.overall.status} />
                    <span className="text-[12px] font-mono" style={{ color: (STATUS_STYLE[r.overall.status] || STATUS_STYLE.unknown).color }}>{r.overall.score}</span>
                    <span className="ml-auto text-[10px] text-zinc-500">
                      {r.dims.filter((d) => d.status === "fail").length} 失败 · {r.dims.filter((d) => d.status === "warn").length} 警告 · {r.dims.filter((d) => d.status === "unknown").length} 未知
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
