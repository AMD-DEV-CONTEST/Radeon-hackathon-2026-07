'use client';

import { useCallback, useEffect, useState } from 'react';

// ─── Types (mirror of API response shapes) ───────────────────────────────────

type RoutedBy = 'keyword' | 'llm' | 'default';
type EventType = 'route' | 'llm_call' | 'tool_call' | 'tool_result' | 'text_stream' | 'error';

interface TraceSummary {
  id: string;
  startTime: number;
  endTime?: number;
  durationMs?: number;
  subagent?: string;
  routedBy?: RoutedBy;
  confidence?: number;
  reason?: string;
  toolCallCount: number;
  eventCount: number;
  hasError: boolean;
  isSeedData?: boolean;
}

interface TraceEventRow {
  timestamp: number;
  type: EventType;
  subagent?: string;
  data: Record<string, unknown>;
}

interface TraceDetail {
  id: string;
  startTime: number;
  endTime?: number;
  tokenCount?: number;
  routeResult?: {
    subagent: string;
    confidence: number;
    routedBy: RoutedBy;
    reason: string;
  };
  events: TraceEventRow[];
}

// ─── Formatting helpers ──────────────────────────────────────────────────────

function formatClock(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatDuration(ms?: number): string {
  if (ms === undefined) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatOffset(base: number, ts: number): string {
  const diff = ts - base;
  if (diff < 0) return '+0ms';
  if (diff < 1000) return `+${diff}ms`;
  return `+${(diff / 1000).toFixed(2)}s`;
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 5000) return 'just now';
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return `${Math.floor(diff / 3600000)}h ago`;
}

// ─── Style maps ──────────────────────────────────────────────────────────────

const ROUTE_STYLES: Record<RoutedBy, { label: string; text: string; bg: string; border: string; dot: string }> = {
  keyword: { label: 'keyword', text: 'text-emerald-600 dark:text-emerald-300', bg: 'bg-emerald-400/10', border: 'border-emerald-400/20', dot: 'bg-emerald-400' },
  llm:      { label: 'llm',      text: 'text-sky-600 dark:text-sky-300',     bg: 'bg-sky-400/10',     border: 'border-sky-400/20',     dot: 'bg-sky-400' },
  default:  { label: 'default',  text: 'text-gray-600 dark:text-white/45',    bg: 'bg-gray-100 dark:bg-white/[0.04]',   border: 'border-gray-200 dark:border-white/10',       dot: 'bg-gray-300 dark:bg-white/30' },
};

const EVENT_STYLES: Record<EventType, { text: string; bg: string; border: string }> = {
  route:       { text: 'text-amber-600 dark:text-amber-300',  bg: 'bg-amber-400/10',  border: 'border-amber-400/20' },
  llm_call:    { text: 'text-sky-600 dark:text-sky-300',    bg: 'bg-sky-400/10',    border: 'border-sky-400/20' },
  tool_call:   { text: 'text-violet-600 dark:text-violet-300', bg: 'bg-violet-400/10', border: 'border-violet-400/20' },
  tool_result: { text: 'text-teal-600 dark:text-teal-300',   bg: 'bg-teal-400/10',   border: 'border-teal-400/20' },
  text_stream: { text: 'text-gray-600 dark:text-white/40',   bg: 'bg-gray-100 dark:bg-white/[0.04]',   border: 'border-gray-200 dark:border-white/10' },
  error:       { text: 'text-red-400',    bg: 'bg-red-400/10',     border: 'border-red-400/20' },
};

const SUBAGENT_LABEL: Record<string, string> = {
  general: 'General',
  knowledge_rag: 'Knowledge RAG',
  data_analysis: 'Data Analysis',
  writing_assistant: 'Writing',
  quick_chat: 'Quick Chat',
};

/** Build a short human-readable summary of an event's payload. */
function summarizeEvent(e: TraceEventRow): string {
  const d = e.data;
  switch (e.type) {
    case 'route': {
      const r = d.routedBy as RoutedBy | undefined;
      const sub = d.subagent as string | undefined;
      const conf = typeof d.confidence === 'number' ? `${Math.round(d.confidence * 100)}%` : '';
      const reason = typeof d.reason === 'string' ? d.reason : '';
      return `${sub ?? '?'} via ${r ?? '?'}${conf ? ` (${conf})` : ''}${reason ? ` — ${reason}` : ''}`;
    }
    case 'llm_call': {
      const dur = typeof d.durationMs === 'number' ? formatDuration(d.durationMs) : '';
      return `LLM stream completed${dur ? ` · ${dur}` : ''}`;
    }
    case 'tool_call': {
      const name = typeof d.name === 'string' ? d.name : '?';
      const input = d.input;
      if (input && typeof input === 'object') {
        const keys = Object.keys(input);
        if (keys.length > 0) return `${name}(${keys.join(', ')})`;
      }
      return `${name}()`;
    }
    case 'tool_result': {
      const name = typeof d.name === 'string' ? d.name : '?';
      const dur = typeof d.durationMs === 'number' ? ` · ${formatDuration(d.durationMs)}` : '';
      const result = typeof d.result === 'string' ? d.result : '';
      const preview = result.slice(0, 120);
      const ell = result.length > 120 ? '…' : '';
      return `${name} → ${preview}${ell}${dur}`;
    }
    case 'error': {
      const err = typeof d.error === 'string' ? d.error : 'Unknown error';
      return err;
    }
    case 'text_stream':
    default:
      return '';
  }
}

// ─── Tiny inline icons ───────────────────────────────────────────────────────

function IconActivity() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path strokeLinecap="round" strokeLinejoin="round" d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  );
}
function IconRefresh() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v6h6M20 20v-6h-6M4 10a8 8 0 0 1 14-3M20 14a8 8 0 0 1-14 3" />
    </svg>
  );
}
function IconChevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-4 w-4 transition-transform duration-300 ${open ? 'rotate-90' : ''}`}
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m9 5 7 7-7 7" />
    </svg>
  );
}
function IconWrench() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.7-.7-.7-2.7 2.9-1.9z" />
    </svg>
  );
}
function IconAlert() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.3 3.376c-.86 1.5.22 3.374 1.95 3.374h14.7c1.73 0 2.81-1.874 1.95-3.374L13.95 3.378c-.86-1.5-3.03-1.5-3.9 0L2.7 16.126ZM12 15.75h.008v.008H12v-.008Z" />
    </svg>
  );
}

// ─── Badge components ────────────────────────────────────────────────────────

function RouteBadge({ routedBy }: { routedBy: RoutedBy }) {
  const s = ROUTE_STYLES[routedBy] ?? ROUTE_STYLES.default;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${s.bg} ${s.border} ${s.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

function EventBadge({ type }: { type: EventType }) {
  const s = EVENT_STYLES[type] ?? EVENT_STYLES.text_stream;
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide ${s.bg} ${s.border} ${s.text}`}>
      {type}
    </span>
  );
}

// ─── Router learning stats types ──────────────────────────────────────────────

interface LearningStats {
  feedbackCount: number;
  correctionRate: { total: number; corrected: number; rate: number };
  adjustmentCount: number;
  adjustments: Array<{ subagentId: string; keyword: string; weight: number; adjustmentCount: number }>;
  recentFeedback: Array<{ message: string; correctSubagent: string; originalSubagent: string; timestamp: number }>;
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function TracePage() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [count, setCount] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<number>(0);
  const [listError, setListError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [learningStats, setLearningStats] = useState<LearningStats | null>(null);

  const fetchTraces = useCallback(async () => {
    try {
      const res = await fetch('/api/trace', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { traces: TraceSummary[]; count: number };
      setTraces(data.traces ?? []);
      setCount(data.count ?? 0);
      setLastRefresh(Date.now());
      setListError(null);
    } catch (e) {
      setListError(e instanceof Error ? e.message : 'Failed to load traces');
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  const fetchLearningStats = useCallback(async () => {
    try {
      const res = await fetch('/api/router-feedback?limit=20', { cache: 'no-store' });
      if (!res.ok) return;
      const data = (await res.json()) as LearningStats;
      setLearningStats(data);
    } catch {
      // Silent fail — learning stats are supplementary
    }
  }, []);

  const fetchDetail = useCallback(async (id: string) => {
    setLoadingDetail(true);
    try {
      const res = await fetch(`/api/trace?id=${encodeURIComponent(id)}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { trace?: TraceDetail };
      setDetail(data.trace ?? null);
    } catch {
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  // Initial load + 5s polling
  useEffect(() => {
    fetchTraces();
    fetchLearningStats();
    const interval = setInterval(() => {
      setIsRefreshing(true);
      fetchTraces();
      fetchLearningStats();
      // Keep the selected detail live as new events stream in
      setSelectedId((cur) => {
        if (cur) fetchDetail(cur);
        return cur;
      });
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchTraces, fetchDetail, fetchLearningStats]);

  const handleSelect = (id: string) => {
    if (selectedId === id) {
      setSelectedId(null);
      setDetail(null);
      return;
    }
    setSelectedId(id);
    fetchDetail(id);
  };

  const handleManualRefresh = () => {
    setIsRefreshing(true);
    fetchTraces();
    if (selectedId) fetchDetail(selectedId);
  };

  return (
    <div className="space-y-8 animate-fade-up">
      {/* ── Header ── */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[20px] font-bold tracking-tight text-gray-900 dark:text-white">
            执行追踪
          </h1>
          <p className="mt-1.5 text-[14px] text-gray-500 dark:text-white/40">
            FunctionRouter 决策、LLM 调用和工具结果的全链路追踪。
            <span className="ml-1 text-gray-400 dark:text-white/25">每 5 秒自动刷新。</span>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="font-mono text-[11px] text-gray-400 dark:text-white/30">
              {count} 条记录 · {lastRefresh ? timeAgo(lastRefresh) : '—'}
            </p>
            <p className="text-[11px] text-gray-400 dark:text-white/25">内存存储</p>
          </div>
          <button
            onClick={handleManualRefresh}
            disabled={isRefreshing}
            className="group inline-flex items-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] px-4 py-2.5 text-[13px] font-semibold text-gray-600 dark:text-white/60 transition-all duration-300 ease-expo hover:border-sky-400/20 hover:bg-sky-400/5 hover:text-sky-300 disabled:opacity-50"
          >
            <span className={isRefreshing ? 'animate-spin-slow' : ''}>
              <IconRefresh />
            </span>
            刷新
          </button>
        </div>
      </div>

      {listError && (
        <div className="glass rounded-2xl border-red-400/20 p-4">
          <p className="text-[13px] text-red-400">加载追踪记录失败：{listError}</p>
        </div>
      )}

      {/* ── Router Self-Learning Stats ── */}
      {learningStats && learningStats.correctionRate.total === 0 && (
        <div className="glass rounded-2xl overflow-hidden p-5">
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-violet-400/20 bg-violet-400/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-violet-600 dark:text-violet-300">
              Self-Learning
            </span>
            <h3 className="text-[14px] font-bold text-gray-800 dark:text-white/80">Router 路由自学习统计</h3>
          </div>
          <p className="text-[13px] text-gray-600 dark:text-white/40">尚无学习数据。在聊天中纠正路由决策后，学习统计将显示在这里。</p>
        </div>
      )}

      {learningStats && learningStats.correctionRate.total > 0 && (
        <div className="glass rounded-2xl overflow-hidden">
          <div className="border-b border-gray-200 dark:border-white/[0.04] px-5 py-3.5">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-md border border-violet-400/20 bg-violet-400/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-violet-600 dark:text-violet-300">
                Self-Learning
              </span>
              <h3 className="text-[14px] font-bold text-gray-800 dark:text-white/80">Router 路由自学习统计</h3>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 p-5 sm:grid-cols-4">
            <StatChip
              label="反馈总数"
              value={String(learningStats.correctionRate.total)}
              accent="text-amber-600 dark:text-amber-300"
            />
            <StatChip
              label="纠正次数"
              value={String(learningStats.correctionRate.corrected)}
              accent={learningStats.correctionRate.corrected > 0 ? 'text-red-600 dark:text-red-300' : 'text-gray-600 dark:text-white/60'}
            />
            <StatChip
              label="路由准确率"
              value={`${((1 - learningStats.correctionRate.rate) * 100).toFixed(0)}%`}
              accent={learningStats.correctionRate.rate === 0 ? 'text-emerald-600 dark:text-emerald-300' : 'text-sky-600 dark:text-sky-300'}
            />
            <StatChip
              label="权重调整数"
              value={String(learningStats.adjustmentCount)}
              accent="text-violet-600 dark:text-violet-300"
            />
          </div>

          {/* Accuracy bar */}
          <div className="px-5 pb-4">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold text-gray-600 dark:text-white/40">准确率</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-white/[0.04]">
                <div
                  className="h-full rounded-full bg-emerald-400 transition-all duration-500"
                  style={{ width: `${(1 - learningStats.correctionRate.rate) * 100}%` }}
                />
              </div>
              <span className="font-mono text-[11px] text-gray-500 dark:text-white/50">
                {((1 - learningStats.correctionRate.rate) * 100).toFixed(0)}%
              </span>
            </div>
          </div>

          {/* Learned weight adjustments */}
          {learningStats.adjustments.length > 0 && (
            <div className="border-t border-gray-200 dark:border-white/[0.04] px-5 py-3">
              <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">
                已学习权重调整 ({learningStats.adjustments.length})
              </p>
              <div className="flex flex-wrap gap-1.5">
                {learningStats.adjustments.slice(0, 12).map((adj, i) => {
                  const isIncreased = adj.weight > 1;
                  const isDecreased = adj.weight < 1;
                  return (
                    <span
                      key={i}
                      title={`${adj.subagentId} → ${adj.keyword} (adjusted ${adj.adjustmentCount}x)`}
                      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[10px] ${
                        isIncreased
                          ? 'border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-600/80 dark:text-emerald-300/80'
                          : isDecreased
                            ? 'border-red-400/20 bg-red-400/[0.06] text-red-600/80 dark:text-red-300/80'
                            : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.03] text-gray-500 dark:text-white/50'
                      }`}
                    >
                      {adj.keyword}
                      <span className="text-gray-400 dark:text-white/30">·</span>
                      {adj.weight.toFixed(2)}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {/* Recent feedback */}
          {learningStats.recentFeedback.length > 0 && (
            <div className="border-t border-gray-200 dark:border-white/[0.04] px-5 py-3">
              <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">
                最近反馈 ({learningStats.recentFeedback.length})
              </p>
              <div className="space-y-1">
                {learningStats.recentFeedback.slice(0, 5).map((fb, i) => (
                  <div key={i} className="flex items-center gap-2 text-[11px]">
                    <span className="font-mono text-gray-400 dark:text-white/30">{timeAgo(fb.timestamp)}</span>
                    <span className="text-red-600/60 dark:text-red-300/60 line-through">{SUBAGENT_LABEL[fb.originalSubagent] ?? fb.originalSubagent}</span>
                    <svg className="h-2.5 w-2.5 text-gray-300 dark:text-white/20" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M3 10a.75.75 0 0 1 .75-.75h10.638L10.23 5.29a.75.75 0 1 1 1.04-1.08l5.5 5.25a.75.75 0 0 1 0 1.08l-5.5 5.25a.75.75 0 1 1-1.04-1.08l4.158-3.96H3.75A.75.75 0 0 1 3 10Z" clipRule="evenodd" />
                    </svg>
                    <span className="font-semibold text-emerald-600/80 dark:text-emerald-300/80">{SUBAGENT_LABEL[fb.correctSubagent] ?? fb.correctSubagent}</span>
                    <span className="truncate text-gray-400 dark:text-white/30">← &ldquo;{fb.message.slice(0, 40)}&rdquo;</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Trace list ── */}
      {traces.length === 0 && !listError ? (
        <div className="glass rounded-2xl overflow-hidden">
          <div className="px-8 py-16 text-center">
            <div>
              <h3 className="text-[18px] font-bold tracking-tight text-gray-900 dark:text-white">暂无追踪记录</h3>
              <p className="mx-auto mt-2 max-w-sm text-[13px] text-gray-500 dark:text-white/40">
                在聊天中发送一条消息，路由和工具事件将实时显示在这里。
              </p>
              {/* Traces live in process memory, so on a multi-instance host the
                  page can legitimately look empty right after a chat. Saying so
                  is better than letting it read as a bug. */}
              <p className="mx-auto mt-3 max-w-sm text-[11px] text-gray-400 dark:text-white/25">
                追踪记录保存在服务进程内存中，不落库。多实例部署时可能看不到刚才那次对话的记录，重启后也会清空。
              </p>
              <a
                href="/chat"
                className="mt-5 inline-flex items-center gap-2 rounded-xl bg-sky-400 px-5 py-2.5 text-[14px] font-bold text-black transition-all duration-200 hover:bg-sky-300"
              >
                去聊天
              </a>
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {/* Column header */}
          <div className="hidden grid-cols-[auto_1fr_auto_auto_auto] gap-4 px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/25 sm:grid">
            <span className="w-20">时间</span>
            <span>子智能体 · 路由</span>
            <span className="w-16 text-right">耗时</span>
            <span className="w-20 text-right">工具</span>
            <span className="w-8 text-right"> </span>
          </div>

          {traces.map((t, i) => {
            const open = selectedId === t.id;
            const routedBy = (t.routedBy ?? 'default') as RoutedBy;
            return (
              <div key={t.id} className={`stagger-${Math.min(i + 1, 5)} animate-fade-up`}>
                <button
                  onClick={() => handleSelect(t.id)}
                  className={`glass glass-hover group w-full rounded-2xl px-4 py-3.5 text-left transition-all duration-200 ${
                    open ? 'border-sky-400/30 bg-sky-400/[0.04]' : ''
                  }`}
                >
                  <div className="grid grid-cols-[1fr_auto] items-center gap-3 sm:grid-cols-[auto_1fr_auto_auto_auto] sm:gap-4">
                    {/* time */}
                    <div className="hidden w-20 sm:block">
                      <p className="font-mono text-[12px] text-gray-500 dark:text-white/55">{formatClock(t.startTime)}</p>
                      <p className="font-mono text-[10px] text-gray-400 dark:text-white/25">{timeAgo(t.startTime)}</p>
                    </div>

                    {/* subagent + route */}
                    <div className="min-w-0 flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center rounded-md border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.03] px-2 py-0.5 text-[12px] font-semibold text-gray-700 dark:text-white/75">
                        {SUBAGENT_LABEL[t.subagent ?? ''] ?? t.subagent ?? '—'}
                      </span>
                      {t.isSeedData && (
                        <span className="inline-flex items-center rounded-md border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/[0.02] px-1.5 py-0.5 text-[10px] font-medium text-gray-400 dark:text-white/30">
                          示例
                        </span>
                      )}
                      <RouteBadge routedBy={routedBy} />
                      {t.hasError && (
                        <span className="inline-flex items-center gap-1 rounded-md border border-red-400/20 bg-red-400/10 px-1.5 py-0.5 text-[11px] font-semibold text-red-400">
                          <IconAlert /> 错误
                        </span>
                      )}
                      {t.reason && (
                        <span className="hidden truncate text-[11px] text-gray-400 dark:text-white/30 lg:inline">{t.reason}</span>
                      )}
                    </div>

                    {/* duration */}
                    <div className="hidden w-16 text-right sm:block">
                      <p className="font-mono text-[12px] text-gray-500 dark:text-white/55">{formatDuration(t.durationMs)}</p>
                    </div>

                    {/* tools */}
                    <div className="hidden w-20 items-center justify-end gap-1.5 text-right sm:flex">
                      <span className="text-violet-300/70"><IconWrench /></span>
                      <span className="font-mono text-[12px] text-gray-500 dark:text-white/55">{t.toolCallCount}</span>
                      <span className="font-mono text-[10px] text-gray-400 dark:text-white/25">/{t.eventCount}</span>
                    </div>

                    {/* chevron */}
                    <div className="flex w-8 items-center justify-end text-gray-400 dark:text-white/35 group-hover:text-white/60">
                      <IconChevron open={open} />
                    </div>
                  </div>

                  {/* mobile sub-line */}
                  <div className="mt-2 flex items-center gap-3 sm:hidden">
                    <span className="font-mono text-[11px] text-gray-600 dark:text-white/40">{formatClock(t.startTime)}</span>
                    <span className="font-mono text-[11px] text-gray-600 dark:text-white/40">{formatDuration(t.durationMs)}</span>
                    <span className="font-mono text-[11px] text-gray-600 dark:text-white/40">{t.toolCallCount} 个工具</span>
                  </div>
                </button>

                {/* ── Detail timeline ── */}
                {open && (
                  <div className="mt-1.5 animate-slide-down rounded-2xl border border-sky-400/10 bg-gray-50 dark:bg-black/40 p-4 sm:p-5">
                    {loadingDetail && !detail && (
                      <div className="space-y-2 py-4">
                        {[...Array(3)].map((_, k) => (
                          <div key={k} className="h-6 rounded bg-gray-200 dark:bg-white/[0.04] animate-pulse" />
                        ))}
                      </div>
                    )}

                    {detail && detail.id === t.id && (
                      <TraceTimeline detail={detail} />
                    )}

                    {!loadingDetail && (!detail || detail.id !== t.id) && (
                      <p className="py-4 text-center text-[13px] text-gray-400 dark:text-white/35">暂无详情</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="pt-2 text-center text-[11px] text-gray-400 dark:text-white/20">
        追踪数据存储在内存中，服务重启后会清空。
      </p>
    </div>
  );
}

// ─── Trace timeline (detail) ─────────────────────────────────────────────────

function TraceTimeline({ detail }: { detail: TraceDetail }) {
  const events = detail.events;
  const base = detail.startTime;
  const totalDur = detail.endTime ? detail.endTime - detail.startTime : undefined;

  const toolCalls = events.filter((e) => e.type === 'tool_call').length;
  const toolDuration = events
    .filter((e) => e.type === 'tool_result')
    .reduce((s, e) => s + (typeof e.data.durationMs === 'number' ? (e.data.durationMs as number) : 0), 0);
  const llmDuration = events
    .filter((e) => e.type === 'llm_call')
    .reduce((s, e) => s + (typeof e.data.durationMs === 'number' ? (e.data.durationMs as number) : 0), 0);
  const hasError = events.some((e) => e.type === 'error');

  return (
    <div className="space-y-4">
      {/* Stats strip */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatChip label="总耗时" value={formatDuration(totalDur)} accent="text-gray-800 dark:text-white/80" />
        <StatChip label="LLM 耗时" value={formatDuration(llmDuration || undefined)} accent="text-sky-600 dark:text-sky-300" />
        <StatChip label="工具耗时" value={formatDuration(toolDuration || undefined)} accent="text-teal-600 dark:text-teal-300" />
        <StatChip label="工具调用" value={String(toolCalls)} accent="text-violet-600 dark:text-violet-300" />
      </div>

      {/* Route summary */}
      {detail.routeResult && (
        <div className="rounded-xl border border-amber-400/15 bg-amber-400/[0.04] px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-bold uppercase tracking-widest text-amber-600/80 dark:text-amber-300/80">路由</span>
            <span className="text-[13px] font-semibold text-gray-800 dark:text-white/85">
              {SUBAGENT_LABEL[detail.routeResult.subagent] ?? detail.routeResult.subagent}
            </span>
            <RouteBadge routedBy={detail.routeResult.routedBy} />
            <span className="font-mono text-[11px] text-gray-600 dark:text-white/40">
              置信度 {Math.round(detail.routeResult.confidence * 100)}%
            </span>
          </div>
          {detail.routeResult.reason && (
            <p className="mt-1.5 text-[12px] text-gray-800 dark:text-white/45">{detail.routeResult.reason}</p>
          )}
        </div>
      )}

      {/* Event timeline */}
      <div>
        <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">
          事件时间线 · {events.length}
        </p>
        <ol className="relative space-y-0">
          {events.map((e, i) => {
            const s = EVENT_STYLES[e.type] ?? EVENT_STYLES.text_stream;
            const summary = summarizeEvent(e);
            return (
              <li
                key={i}
                className="group relative flex items-start gap-3 rounded-xl px-2 py-2 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.025]"
              >
                {/* connector */}
                {i < events.length - 1 && (
                  <span className="absolute left-[7px] top-[26px] h-[calc(100%-10px)] w-px bg-gray-200 dark:bg-white/[0.05]" />
                )}
                {/* dot */}
                <span
                  className={`relative z-10 mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full border ${s.border} ${s.bg}`}
                />
                {/* content */}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <EventBadge type={e.type} />
                    <span className="font-mono text-[11px] text-gray-400 dark:text-white/30">
                      {formatOffset(base, e.timestamp)}
                    </span>
                    <span className="font-mono text-[10px] text-gray-400 dark:text-white/20">{formatClock(e.timestamp)}</span>
                  </div>
                  {summary && (
                    <p className="mt-1 break-words font-mono text-[12px] leading-snug text-gray-600 dark:text-white/60">
                      {summary}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        {hasError && (
          <p className="mt-3 text-[11px] text-red-400/70">
            This trace ended with an error — see the error event above.
          </p>
        )}
      </div>
    </div>
  );
}

function StatChip({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-white/[0.02] px-3 py-2">
      <p className="text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-white/30">{label}</p>
      <p className={`mt-0.5 font-mono text-[14px] font-bold ${accent}`}>{value}</p>
    </div>
  );
}
