"use client";

// ============================================================================
// QualityMonitorPanel — AI 回复质量监控（Phase 3b）。
// 展示综合质量 / 风险 / 样本量等状态指标，以及影子流量比例的灰度控制。
// 数据源：GET /api/qa/quality-dashboard?action=snapshot | alerts | override
// ============================================================================

import { useState, useEffect, useCallback } from "react";
import { BarChart3 } from "lucide-react";
import { formatCompactPercent } from "@/lib/utils";

interface IntentScore {
  intent: string;
  qualityScore: number;
  riskScore: number;
  sampleCount: number;
  llmRate: number;
  avgLatencyMs: number;
  approvalRate: number | null;
  complianceBlockRate: number;
  fallbackRate: number;
  cacheHitRate: number;
}

interface ThrottleDecision {
  action: string;
  reason: string;
  suggestedRatio: number;
  currentQuality: number;
  currentRisk: number;
  confidenceLevel: string;
}

interface SloStatus {
  name: string;
  current: number;
  target: number;
  met: boolean;
  errorBudgetRemaining: number;
  unit: string;
}

interface DashboardData {
  snapshot: {
    overallQuality: number;
    overallRisk: number;
    totalReplies24h: number;
    totalShadow24h: number;
    totalActual24h: number;
    pendingApproval: number;
    complianceBlocked24h: number;
    intents: IntentScore[];
    sloStatuses?: SloStatus[];
  };
  throttle: ThrottleDecision;
  intentThrottles: Record<string, ThrottleDecision>;
  autoThrottleEnabled: boolean;
  currentRatio: number;
  windowHours: number;
  generatedAt: string;
}

interface AlertResult {
  triggered: boolean;
  level: string;
  rule: string;
  message: string;
  autoAction: string;
}

// 风险阈值与 auto-throttle 引擎保持一致（riskDecreaseThreshold=25 / riskEmergencyThreshold=40）
const RISK_WARN_THRESHOLD = 25;
const RISK_EMERGENCY_THRESHOLD = 40;

export default function QualityMonitorPanel() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [alerts, setAlerts] = useState<AlertResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [windowHours, setWindowHours] = useState(24);
  const [overrideRatio, setOverrideRatio] = useState("");
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  // 决策卡筛选：点击质量/风险/样本卡后，按对应维度排序下方意图明细
  const [activeFilter, setActiveFilter] = useState<null | "quality" | "risk" | "sample">(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [snapRes, alertRes] = await Promise.all([
        fetch(`/api/qa/quality-dashboard?action=snapshot&hours=${windowHours}`),
        fetch(`/api/qa/quality-dashboard?action=alerts&hours=${windowHours}`),
      ]);

      if (!snapRes.ok) throw new Error(`Snapshot: ${snapRes.status}`);
      setData(await snapRes.json());

      if (alertRes.ok) {
        const alertJson = await alertRes.json();
        setAlerts(alertJson.alerts || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [windowHours]);

  useEffect(() => {
    queueMicrotask(() => void fetchData());
  }, [fetchData]);

  const applyOverride = async () => {
    const ratio = parseFloat(overrideRatio);
    if (isNaN(ratio) || ratio < 0 || ratio > 1) {
      setActionFeedback("比例必须在 0-1 之间");
      return;
    }
    try {
      const res = await fetch(`/api/qa/quality-dashboard?action=override&ratio=${ratio}`);
      if (res.ok) {
        setActionFeedback(`已手动设置流量比例: ${ratio}`);
        fetchData();
      } else {
        const json = await res.json();
        setActionFeedback(`设置失败: ${json.error}`);
      }
    } catch {
      setActionFeedback("网络错误");
    }
  };

  const toggleFilter = (key: "quality" | "risk" | "sample") =>
    setActiveFilter((prev) => (prev === key ? null : key));

  // ── 色板：全部走主题 token，禁止硬编码 slate/gray/emerald 等 ──

  // 质量分档位：0 值一律中性，避免"0 分"被红/绿误导
  const qualityText = (score: number) => {
    if (score <= 0) return "text-foreground";
    if (score >= 85) return "text-success";
    if (score >= 60) return "text-warning";
    return "text-destructive";
  };
  const qualityBar = (score: number) => {
    if (score <= 0) return "bg-muted";
    if (score >= 85) return "bg-success";
    if (score >= 60) return "bg-warning";
    return "bg-destructive";
  };

  // 风险分档位：绿色不用于风险等级，低风险用中性，仅超阈值才上风险色
  const riskText = (risk: number) => {
    if (risk <= 0) return "text-foreground";
    if (risk > RISK_EMERGENCY_THRESHOLD) return "text-destructive";
    if (risk > RISK_WARN_THRESHOLD) return "text-warning";
    return "text-foreground";
  };
  const riskBar = (risk: number) => {
    if (risk <= 0) return "bg-muted";
    if (risk > RISK_EMERGENCY_THRESHOLD) return "bg-destructive";
    if (risk > RISK_WARN_THRESHOLD) return "bg-warning";
    return "bg-border";
  };

  const throttleActionLabel: Record<string, string> = {
    INCREASE: "建议提高比例",
    HOLD: "保持当前比例",
    DECREASE: "建议降低比例",
    EMERGENCY_DOWNGRADE: "紧急降级",
  };

  // HOLD 用 info 蓝表达"维持现状"，不再用灰扑扑的类禁用样式
  const throttleActionBadge: Record<string, string> = {
    INCREASE: "bg-success/10 text-success",
    HOLD: "bg-info/10 text-info-foreground",
    DECREASE: "bg-warning/10 text-warning-foreground",
    EMERGENCY_DOWNGRADE: "bg-destructive text-white",
  };

  const confidenceLabel: Record<string, string> = {
    high: "高",
    medium: "中",
    low: "低",
  };

  const alertLevelColor: Record<string, string> = {
    L1: "border-info/30 bg-info/10",
    L2: "border-warning/30 bg-warning/10",
    L3: "border-destructive/40 bg-destructive/10",
  };

  const alertLevelBadge: Record<string, string> = {
    L3: "bg-destructive text-white",
    L2: "bg-warning text-warning-foreground",
    L1: "bg-info text-info-foreground",
  };

  if (loading) {
    return <div className="flex min-h-72 items-center justify-center bg-background p-6 text-sm text-muted-foreground" aria-live="polite">加载质量数据中...</div>;
  }

  if (error) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center bg-background p-6 text-center">
        <p className="text-sm text-destructive">加载失败: {error}</p>
        <button type="button" onClick={fetchData} className="mt-3 rounded-lg border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted">重试</button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center bg-background py-16 text-center">
        <BarChart3 className="w-12 h-12 text-muted-foreground/20 mb-4" />
        <p className="text-muted-foreground/70 text-sm font-medium mb-1">暂无回复数据</p>
        <p className="text-muted-foreground/50 text-xs">开始使用AI客服后将自动统计回复质量数据</p>
        <button type="button" onClick={fetchData} className="mt-4 rounded-lg border border-border px-3 py-2 text-xs font-medium text-foreground hover:bg-muted">重新加载</button>
      </div>
    );
  }

  const { snapshot, throttle, intentThrottles, autoThrottleEnabled, currentRatio } = data;

  // 全局 throttle 中 confidenceLevel === "low" 即代表全局样本量不足（见 auto-throttle 引擎），
  // 此时禁止调整流量比例
  const insufficientData = throttle.confidenceLevel === "low";

  // 完全没有样本时展示空态引导，避免出现一整排 0
  const hasNoData = snapshot.totalReplies24h === 0 && snapshot.intents.length === 0;

  // 按决策卡所选维度排序意图明细（展示层排序，不改写数据）
  let displayedIntents = snapshot.intents;
  if (activeFilter === "quality") {
    displayedIntents = [...snapshot.intents].sort((a, b) => b.qualityScore - a.qualityScore);
  } else if (activeFilter === "risk") {
    displayedIntents = [...snapshot.intents].sort((a, b) => b.riskScore - a.riskScore);
  } else if (activeFilter === "sample") {
    displayedIntents = [...snapshot.intents].sort((a, b) => b.sampleCount - a.sampleCount);
  }

  // 手动设置按钮的 disabled 语义
  const overrideDisabled = insufficientData;

  const header = (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold text-foreground">回复质量监控</h2>
        <p className="text-xs text-muted-foreground/60">
          跟踪回复质量与风险指标，依据样本量给出流量灰度建议 · {windowHours}h 窗口 · 更新于 {new Date(data.generatedAt).toLocaleTimeString("zh-CN")}
        </p>
      </div>
      <div className="flex flex-wrap gap-2" aria-label="时间窗口">
        {[6, 24, 72, 168].map((h) => (
          <button
            key={h}
            type="button"
            onClick={() => setWindowHours(h)}
            className={`px-2 py-1 text-xs rounded ${
              windowHours === h
                ? "bg-primary text-primary-foreground"
                : "bg-card border border-border text-muted-foreground hover:bg-muted/50"
            }`}
          >
            {h >= 24 ? `${h / 24}d` : `${h}h`}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="min-h-0 space-y-5 overflow-auto bg-background p-4 sm:p-6">
      {header}

      {hasNoData ? (
        // 空态：给出明确引导动作，不展示一排 0
        <div className="rounded-lg border border-border bg-card px-6 py-14 text-center">
          <BarChart3 className="mx-auto w-12 h-12 text-muted-foreground/20 mb-4" />
          <p className="text-sm font-medium text-foreground mb-1">当前窗口内暂无回复样本</p>
          <p className="text-xs text-muted-foreground/60 mb-4">接入 AI 客服流量后将自动统计回复质量，可切换上方时间窗口或手动刷新</p>
          <button
            type="button"
            onClick={fetchData}
            className="rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            重新加载
          </button>
        </div>
      ) : (
        <>
          {/* ── 区域一：当前质量状态 ── */}
          <section>
            <div className="mb-3">
              <h3 className="text-sm font-semibold text-foreground">当前质量状态</h3>
              <p className="text-xs text-muted-foreground/60">点击「综合质量 / 综合风险 / 样本量」卡片可按维度排序下方意图明细，再点一次恢复默认</p>
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <DecisionCard
                label="综合质量分"
                value={`${snapshot.overallQuality}`}
                suffix="/100"
                textClass={qualityText(snapshot.overallQuality)}
                barClass={qualityBar(snapshot.overallQuality)}
                active={activeFilter === "quality"}
                onClick={() => toggleFilter("quality")}
              />
              <DecisionCard
                label="综合风险分"
                value={`${snapshot.overallRisk}`}
                suffix="/100"
                textClass={riskText(snapshot.overallRisk)}
                barClass={riskBar(snapshot.overallRisk)}
                active={activeFilter === "risk"}
                onClick={() => toggleFilter("risk")}
              />
              <DecisionCard
                label="样本量（24h）"
                value={`${snapshot.totalReplies24h}`}
                suffix="条"
                textClass="text-foreground"
                barClass="bg-info"
                active={activeFilter === "sample"}
                onClick={() => toggleFilter("sample")}
                sub={`影子 ${snapshot.totalShadow24h} · 真实 ${snapshot.totalActual24h}`}
              />
              <StatCard
                label="待审/拦截"
                value={`${snapshot.pendingApproval}`}
                suffix={`+${snapshot.complianceBlocked24h}`}
                sub={snapshot.pendingApproval > 20 ? "待审较多，建议优先处理" : undefined}
              />
            </div>
          </section>

          {/* ── 区域二：影子流量控制 ── */}
          <section>
            <div className="mb-3">
              <h3 className="text-sm font-semibold text-foreground">影子流量控制</h3>
              <p className="text-xs text-muted-foreground/60">调整影子回复占真实流量的比例，建议值由质量引擎按当前指标生成</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      insufficientData && throttle.action === "HOLD"
                        ? "bg-muted text-muted-foreground"
                        : throttleActionBadge[throttle.action] || "bg-muted text-muted-foreground"
                    }`}
                  >
                    {throttleActionLabel[throttle.action] || throttle.action}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      autoThrottleEnabled ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {autoThrottleEnabled ? "自动灰度" : "手动控制"}
                  </span>
                </div>
                <div className="text-right">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">当前流量比例</div>
                  <div className="text-xl font-bold text-foreground tabular-nums">{formatCompactPercent(currentRatio)}</div>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">建议比例</div>
                  <div className="mt-1 text-base font-semibold text-foreground tabular-nums">
                    {formatCompactPercent(throttle.suggestedRatio)}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">置信度</div>
                  <div className="mt-1 text-base font-semibold text-foreground">
                    {confidenceLabel[throttle.confidenceLevel] ?? throttle.confidenceLevel}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">调整说明</div>
                  <div className="mt-1 text-xs text-muted-foreground">{throttle.reason}</div>
                </div>
              </div>

              {insufficientData ? (
                // 样本量不足：明确提示并禁用控制项
                <div className="mt-4 rounded-md border border-warning/30 bg-warning/10 px-3 py-2.5" role="alert">
                  <p className="text-xs font-medium text-warning-foreground">样本不足，暂不建议调整流量比例。</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{throttle.reason}</p>
                </div>
              ) : null}

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  aria-label="流量比例滑块"
                  disabled={overrideDisabled}
                  value={overrideRatio !== "" ? parseFloat(overrideRatio) : currentRatio}
                  onChange={(e) => setOverrideRatio(e.target.value)}
                  className="flex-1 accent-primary disabled:cursor-not-allowed disabled:opacity-50"
                />
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  aria-label="流量比例数值"
                  value={overrideRatio}
                  onChange={(e) => setOverrideRatio(e.target.value)}
                  placeholder={String(currentRatio)}
                  disabled={overrideDisabled}
                  className="w-24 rounded-md border border-input bg-card px-2 py-1.5 text-center text-sm text-foreground placeholder:text-muted-foreground/60 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
                />
                <button
                  type="button"
                  onClick={applyOverride}
                  disabled={overrideDisabled}
                  className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  手动设置
                </button>
              </div>
            </div>
          </section>

          {/* 活跃告警 */}
          {alerts.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-foreground/70">活跃告警 ({alerts.length})</h3>
              {alerts.map((a, i) => (
                <div key={i} className={`p-3 rounded-lg border ${alertLevelColor[a.level]}`}>
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${alertLevelBadge[a.level]}`}>{a.level}</span>
                    <span className="text-sm font-medium text-foreground">{a.rule}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{a.message}</p>
                  <p className="text-xs text-muted-foreground/50 mt-0.5">自动操作: {a.autoAction}</p>
                </div>
              ))}
            </section>
          )}

          {/* 按意图分类质量 */}
          <section>
            <h3 className="text-sm font-semibold text-foreground/70 mb-3">
              按意图分类质量
              {activeFilter && (
                <span className="ml-2 text-xs font-normal text-muted-foreground/60">
                  按{activeFilter === "quality" ? "质量分" : activeFilter === "risk" ? "风险分" : "样本量"}排序中 · 再次点击对应卡片恢复默认
                </span>
              )}
            </h3>
            {displayedIntents.length === 0 ? (
              <p className="text-xs text-muted-foreground/50">暂无足够数据（需要更多回复样本）</p>
            ) : (
              <div className="rounded-lg border border-border bg-card overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="min-w-[640px] w-full text-xs">
                    <thead>
                      <tr className="bg-muted text-left text-muted-foreground/60">
                        <th className="p-2 font-medium">意图</th>
                        <th className="p-2 font-medium text-center">质量</th>
                        <th className="p-2 font-medium text-center">风险</th>
                        <th className="p-2 font-medium text-center">样本</th>
                        <th className="p-2 font-medium text-center">LLM率</th>
                        <th className="p-2 font-medium text-center">延迟</th>
                        <th className="p-2 font-medium text-center">兜底率</th>
                        <th className="p-2 font-medium text-center">合规拦截</th>
                        <th className="p-2 font-medium">自动建议</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayedIntents.map((intent) => {
                        const dec = intentThrottles[intent.intent];
                        return (
                          <tr key={intent.intent} className="border-b border-border last:border-b-0 hover:bg-muted/40">
                            <td className="p-2 font-medium text-foreground/70">{intent.intent}</td>
                            <td className="p-2 text-center">
                              <span className={`font-semibold ${qualityText(intent.qualityScore)}`}>
                                {intent.qualityScore}
                              </span>
                            </td>
                            <td className="p-2 text-center">
                              <span className={riskText(intent.riskScore)}>{intent.riskScore}</span>
                            </td>
                            <td className="p-2 text-center text-muted-foreground/60">{intent.sampleCount}</td>
                            <td className="p-2 text-center text-foreground">{intent.llmRate}%</td>
                            <td className="p-2 text-center text-muted-foreground/70">{intent.avgLatencyMs}ms</td>
                            <td className="p-2 text-center">
                              <span className={intent.fallbackRate > 30 ? "text-warning" : "text-muted-foreground/70"}>
                                {intent.fallbackRate}%
                              </span>
                            </td>
                            <td className="p-2 text-center">
                              <span className={intent.complianceBlockRate > 0 ? "text-destructive" : "text-muted-foreground/60"}>
                                {intent.complianceBlockRate}%
                              </span>
                            </td>
                            <td className="p-2">
                              {dec ? (
                                <span
                                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                                    dec.confidenceLevel === "low"
                                      ? "bg-muted text-muted-foreground"
                                      : throttleActionBadge[dec.action] || "bg-muted text-muted-foreground"
                                  }`}
                                >
                                  {throttleActionLabel[dec.action]}
                                </span>
                              ) : (
                                <span className="text-muted-foreground/50">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>

          {/* 质量/风险对比条 */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold text-foreground/70">质量/风险对比</h3>
            {displayedIntents.map((intent) => (
              <div key={intent.intent} className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground w-16 shrink-0">{intent.intent}</span>
                <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden flex">
                  <div
                    className={`h-full ${qualityBar(intent.qualityScore)} transition-all`}
                    style={{ width: `${intent.qualityScore}%` }}
                  />
                  <div
                    className="h-full bg-destructive/40 transition-all"
                    style={{ width: `${intent.riskScore}%`, marginLeft: `-${intent.riskScore}%` }}
                  />
                </div>
                <span className={`text-xs w-8 text-right font-mono ${qualityText(intent.qualityScore)}`}>
                  {intent.qualityScore}
                </span>
              </div>
            ))}
          </section>

          {actionFeedback && (
            <div className="p-3 rounded-lg bg-info/10 text-info-foreground text-sm">{actionFeedback}</div>
          )}
        </>
      )}
    </div>
  );
}

// ── 决策卡：白底 + 左侧 3px 色条 + 大数字，可点击切换筛选 ──
function DecisionCard({
  label,
  value,
  suffix,
  textClass,
  barClass,
  active,
  onClick,
  sub,
}: {
  label: string;
  value: string;
  suffix: string;
  textClass: string;
  barClass: string;
  active: boolean;
  onClick: () => void;
  sub?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`relative rounded-lg border p-4 text-left transition-colors ${
        active ? "border-primary/40 bg-muted/40" : "border-border bg-card hover:bg-muted/30"
      }`}
    >
      <span className={`absolute left-0 top-3 bottom-3 w-[3px] rounded-l-lg ${barClass}`} />
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">{label}</div>
      <div className={`text-2xl font-bold mt-1 tabular-nums ${textClass}`}>
        {value}
        <span className="text-sm font-normal text-muted-foreground/60 ml-0.5">{suffix}</span>
      </div>
      {sub && <div className="text-xs text-muted-foreground/60 mt-1">{sub}</div>}
    </button>
  );
}

// ── 统计卡：中性白底紧凑 ──
function StatCard({
  label,
  value,
  suffix,
  sub,
}: {
  label: string;
  value: string;
  suffix: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">{label}</div>
      <div className="text-2xl font-bold mt-1 text-foreground tabular-nums">
        {value}
        <span className="text-sm font-normal text-muted-foreground/60 ml-0.5">{suffix}</span>
      </div>
      {sub && <div className="text-xs text-muted-foreground/60 mt-1">{sub}</div>}
    </div>
  );
}
