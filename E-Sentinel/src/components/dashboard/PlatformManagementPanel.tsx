"use client";

// ============================================================================
// PlatformManagementPanel — per-platform integration detail & credential management.
// For Feishu: shows complete closed-loop (inbound webhook → process → outbound reply).
// For Tmall: shows OAuth + store switches + webhook.
// Other platforms: status summary.
//
// 视觉规范：全部使用主题 token（bg-card / bg-muted / text-foreground / text-muted-foreground /
// bg-success / bg-warning / bg-destructive / bg-info），禁止硬编码 slate/gray/emerald/amber/red/blue。
// 图标统一使用 lucide-react 线性图标，不使用 Emoji。
// ============================================================================

import { useState, useEffect, useCallback, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  Database,
  Eye,
  EyeOff,
  Gem,
  Globe,
  Heart,
  History,
  KeyRound,
  Link,
  Loader2,
  MessageCircle,
  MessageSquare,
  Music,
  Pencil,
  Plus,
  QrCode,
  RadioTower,
  RefreshCw,
  Settings2,
  Shield,
  ShoppingBag,
  Store,
  Tag,
  Video,
  Workflow,
  X,
  XCircle,
} from "lucide-react";
import { formatPercent, formatRating, formatDateTime } from "@/lib/utils";

// ── 类型定义（字段与 API 真实返回一致） ──────────────────────────────

interface PlatformRow {
  id: number | string;
  name: string;
  code: string;
  is_active?: boolean;
  bot_type: string;
  api_endpoint: string | null;
  config: Record<string, unknown> | null;
  created_at: string;
}

interface PlatformHealth {
  code: string;
  circuitOpen: boolean;
  errorRate: number;
  avgLatencyMs: number;
  shadowCount24h: number;
  actualCount24h: number;
  pendingApproval: number;
  // chat-stats 真实返回字段
  totalSessions: number;
  botHandledRate: number;
  transferRate: number;
  independentReceptionRate: number;
  avgSentiment: number;
}

interface CredentialStatus {
  key: string;
  label: string;
  description: string;
  configured: boolean;
}

interface CredentialInfo {
  platform: string;
  authMethod: string;
  authDescription: string;
  credentials: CredentialStatus[];
}

// ── 值 → 中文标签映射表（基于 API 真实字段值） ───────────────────────

/** bot_type 字段取值 → 人类可读标签 */
const BOT_TYPE_LABELS: Record<string, string> = {
  third_party: "第三方接入",
  native: "原生机器人",
  hybrid: "混合模式",
};

/** 平台名称 → 中文展示名（与平台表 name 字段语义一致） */
const PLATFORM_LABELS: Record<string, string> = {
  feishu: "飞书", tmall: "天猫", jd: "京东", douyin: "抖音",
  pdd: "拼多多", kuaishou: "快手", weixin: "微信", xiaohongshu: "小红书", vip: "唯品会",
};

/** 平台 code → lucide 线性图标（替代原 Emoji） */
const PLATFORM_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  feishu: MessageSquare, tmall: Store, jd: ShoppingBag, douyin: Music,
  pdd: Tag, kuaishou: Video, weixin: MessageCircle, xiaohongshu: Heart, vip: Gem,
};

/** 平台 code → 回调 Webhook 端点（既有链路，保持原值） */
const PLATFORM_ENDPOINTS: Record<string, string> = {
  feishu: "/api/feishu/event",
  tmall: "/api/platforms/tmall/event",
};

/** 基于机器人处理率判定回调健康度（接收 0-1 原始比率） */
function healthTone(rate: number, total: number): { label: string; bar: string } {
  if (total === 0) return { label: "暂无数据", bar: "bg-muted" };
  if (rate >= 0.7) return { label: "健康", bar: "bg-success" };
  if (rate >= 0.4) return { label: "需关注", bar: "bg-warning" };
  return { label: "异常", bar: "bg-destructive" };
}


// ── 顶部标题区：Panel title + subtitle，右侧操作 ─────────────────────

function PlatformHeader({ onRefresh }: { onRefresh: () => void }) {
  return (
    <header className="border-b border-border bg-background px-4 py-3 sm:px-6">
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-3">
        <div>
          <p className="section-label">SYSTEM / PLATFORMS</p>
          <h1 className="mt-0.5 text-base font-semibold text-foreground">平台管理</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">管理渠道接入、凭证状态与回调链路。</p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          刷新
        </button>
      </div>
    </header>
  );
}

// ── 白底紧凑统计卡（替代原灰色指标块） ───────────────────────────────

function StatCard({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-1.5 text-muted-foreground">
        {icon}
        <span className="text-[10px] font-medium uppercase tracking-wider">{label}</span>
      </div>
      <div className="mt-1 text-xl font-bold tabular-nums text-foreground">{value}</div>
    </div>
  );
}

// ── 决策卡：白底 + 左侧 3px 色条 + 大数字 + 可点击 ─────────────────────

function DecisionCard({ bar, label, value, sub, onClick }: {
  bar: string; label: string; value: string; sub?: string; onClick?: () => void;
}) {
  const Comp: "button" | "div" = onClick ? "button" : "div";
  return (
    <Comp
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className="relative overflow-hidden rounded-lg border border-border bg-card p-3 text-left"
    >
      <span className={`absolute left-0 top-0 bottom-0 w-[3px] ${bar}`} aria-hidden="true" />
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-bold tabular-nums text-foreground">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>}
    </Comp>
  );
}

// ── 主组件 ─────────────────────────────────────────────────────────────

export default function PlatformManagementPanel() {
  const [platforms, setPlatforms] = useState<PlatformRow[]>([]);
  const [health, setHealth] = useState<Map<string, PlatformHealth>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activePlatform, setActivePlatform] = useState<string | null>(null);

  // Edit mode
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // Store switches
  const [storeSwitches, setStoreSwitches] = useState<Record<string, boolean>>({});
  const [newStoreNick, setNewStoreNick] = useState("");

  // Credential status (from API)
  const [credentialInfo, setCredentialInfo] = useState<CredentialInfo[]>([]);

  // OAuth login toast
  const [loginToast, setLoginToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // 既有数据流：并行拉取平台列表 + 凭证状态，再逐个拉取健康统计
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [platRes, credRes] = await Promise.all([
        fetch("/api/qa/platforms"),
        fetch("/api/admin/platform-credentials"),
      ]);

      if (!platRes.ok) throw new Error(`${platRes.status}`);
      const json = await platRes.json();
      const list: PlatformRow[] = json.platforms || [];
      setPlatforms(list);
      if (list.length > 0 && !activePlatform) {
        setActivePlatform(list[0].code);
      }

      if (credRes.ok) {
        const credJson = await credRes.json();
        setCredentialInfo(credJson.platforms || []);
      }

      // 逐个平台拉取 chat-stats，映射真实返回字段到健康指标
      const healthMap = new Map<string, PlatformHealth>();
      for (const p of list) {
        try {
          const hRes = await fetch(`/api/qa/chat-stats?platform=${p.code}`);
          const hJson = await hRes.json();
          healthMap.set(p.code, {
            code: p.code,
            circuitOpen: false,
            errorRate: 0,
            avgLatencyMs: 0,
            shadowCount24h: hJson.shadow_count_24h || 0,
            actualCount24h: hJson.actual_count_24h || 0,
            pendingApproval: hJson.pending_approval || 0,
            totalSessions: hJson.total_sessions || 0,
            botHandledRate: hJson.bot_handled_rate || 0,
            transferRate: hJson.transfer_rate || 0,
            independentReceptionRate: hJson.independent_reception_rate || 0,
            avgSentiment: hJson.avg_sentiment || 0,
          });
        } catch {
          healthMap.set(p.code, {
            code: p.code,
            circuitOpen: false,
            errorRate: 0,
            avgLatencyMs: 0,
            shadowCount24h: 0,
            actualCount24h: 0,
            pendingApproval: 0,
            totalSessions: 0,
            botHandledRate: 0,
            transferRate: 0,
            independentReceptionRate: 0,
            avgSentiment: 0,
          });
        }
      }
      setHealth(healthMap);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [activePlatform]);

  useEffect(() => {
    queueMicrotask(() => void fetchData());
  }, [fetchData]);

  // Load store switches
  const fetchStoreSwitches = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/store-switches");
      if (res.ok) {
        const json = await res.json();
        setStoreSwitches(json.stores || {});
      }
    } catch { /* API may not be available */ }
  }, []);

  useEffect(() => {
    if (activePlatform) queueMicrotask(() => void fetchStoreSwitches());
  }, [activePlatform, fetchStoreSwitches]);

  // Handle OAuth login callback params in URL
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const loginStatus = params.get("login");
      if (loginStatus === "success") {
        queueMicrotask(() => {
          setLoginToast({ type: "success", message: "飞书账号授权成功！凭证已自动保存。" });
          void fetchData();
        });
        const url = new URL(window.location.href);
        url.searchParams.delete("login");
        window.history.replaceState({}, "", url.toString());
      } else if (loginStatus === "error") {
        const reason = params.get("reason") || "未知错误";
        queueMicrotask(() => setLoginToast({ type: "error", message: `飞书授权失败: ${decodeURIComponent(reason)}` }));
        const url = new URL(window.location.href);
        url.searchParams.delete("login");
        url.searchParams.delete("reason");
        window.history.replaceState({}, "", url.toString());
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const active = platforms.find((p) => p.code === activePlatform);
  const activeHealth = activePlatform ? health.get(activePlatform) : undefined;
  const activeCreds = credentialInfo.find((c) => c.platform === activePlatform);

  // Edit helpers
  const startEdit = () => {
    if (!active) return;
    const creds = activeCreds?.credentials.reduce((acc, c) => ({ ...acc, [c.key]: "" }), {}) || {};
    setEditForm({
      name: active.name, code: active.code, bot_type: active.bot_type,
      api_endpoint: active.api_endpoint || "",
      ...creds,
    });
    setEditMode(true);
  };
  const cancelEdit = () => { setEditMode(false); setEditForm({}); };
  const saveEdit = async () => {
    if (!active) return;
    setSaving(true);
    try {
      const { name, code, bot_type, api_endpoint, ...credentials } = editForm;
      const res = await fetch("/api/qa/platforms", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: active.id, name, code, bot_type, api_endpoint: api_endpoint || null,
          credentials: Object.keys(credentials).length > 0 ? credentials : undefined,
        }),
      });
      if (!res.ok) { const j = await res.json(); alert(`保存失败: ${j.error}`); }
      else { setEditMode(false); fetchData(); }
    } catch { alert("保存失败: 网络错误"); }
    finally { setSaving(false); }
  };

  const toggleStore = async (nick: string, enabled: boolean) => {
    try {
      const res = await fetch("/api/admin/store-switches", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ store_nick: nick, enabled }) });
      if (res.ok) { const j = await res.json(); setStoreSwitches(j.stores || {}); }
    } catch { /* ignore */ }
  };
  const addStore = () => { const n = newStoreNick.trim(); if (!n) return; toggleStore(n, false); setNewStoreNick(""); };

  // ── 加载 / 错误 / 空状态 ──
  if (loading) return <div className="min-h-full bg-background"><PlatformHeader onRefresh={() => void fetchData()} /><div className="flex min-h-72 items-center justify-center gap-2 p-6 text-sm text-muted-foreground" aria-live="polite"><Loader2 className="h-4 w-4 animate-spin" />加载平台数据中...</div></div>;
  if (error) return <div className="min-h-full bg-background"><PlatformHeader onRefresh={() => void fetchData()} /><div className="flex min-h-72 flex-col items-center justify-center p-6 text-center"><p className="text-sm text-destructive">加载失败: {error}</p><button type="button" onClick={() => void fetchData()} className="mt-3 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium text-foreground hover:bg-muted">重试</button></div></div>;
  if (platforms.length === 0) return (
    <div className="min-h-full bg-background">
      <PlatformHeader onRefresh={() => void fetchData()} />
      <div className="flex min-h-72 flex-col items-center justify-center p-6 text-center">
        <RadioTower className="mb-3 h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <h3 className="mb-1 text-base font-semibold text-foreground">暂无平台</h3>
        <p className="text-xs text-muted-foreground">数据库中没有平台记录，请先执行迁移脚本</p>
        <button type="button" onClick={() => void fetchData()} className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium text-foreground hover:bg-muted">
          <RefreshCw className="h-3.5 w-3.5" />重新加载
        </button>
      </div>
    </div>
  );

  const activeTone = active ? healthTone(activeHealth?.botHandledRate ?? 0, activeHealth?.totalSessions ?? 0) : { label: "—", bar: "bg-muted" };

  return (
    <div className="platform-management flex min-h-0 h-full flex-col bg-background relative">
      <PlatformHeader onRefresh={() => void fetchData()} />
      <div className="platform-management-body flex min-h-0 flex-1">
        {/* OAuth 登录结果 toast */}
        {loginToast && (
          <div className={`animate-toast-in absolute top-3 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-lg border px-3 py-2 text-xs shadow-lg ${
            loginToast.type === "success"
              ? "border-success/30 bg-success/10 text-success"
              : "border-destructive/30 bg-destructive/10 text-destructive"
          }`}>
            {loginToast.type === "success"
              ? <CheckCircle2 className="h-4 w-4 shrink-0" />
              : <XCircle className="h-4 w-4 shrink-0" />}
            <span>{loginToast.message}</span>
            <button type="button" onClick={() => setLoginToast(null)}
              className="ml-1 opacity-60 hover:opacity-100"><X className="h-3.5 w-3.5" /></button>
          </div>
        )}

        {/* 左侧平台列表：名称 + 连接状态 + 待处理数量 */}
        <div className="platform-sidebar w-56 shrink-0 space-y-1 border-r border-border bg-card p-3">
          <h3 className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">接入平台</h3>
          {platforms.map((p) => {
            const h = health.get(p.code);
            const credMatch = credentialInfo.find((c) => c.platform === p.code);
            const credTotal = credMatch?.credentials.length ?? 0;
            const configuredCount = credMatch?.credentials.filter((c) => c.configured).length ?? 0;
            const Icon = PLATFORM_ICONS[p.code] || Globe;
            const isActive = p.is_active !== false;
            return (
              <button key={p.code} type="button" onClick={() => setActivePlatform(p.code)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-left transition-colors ${
                  activePlatform === p.code ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted/40"
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium text-foreground">{PLATFORM_LABELS[p.code] || p.name}</span>
                  <span className={`block text-[10px] ${activePlatform === p.code ? "text-background/70" : "text-muted-foreground/70"}`}>
                    待处理 {h?.pendingApproval ?? 0} · 凭证 {configuredCount}/{credTotal || 0}
                  </span>
                </span>
                {/* 连接状态点：is_active 决定启用/停用 */}
                <span className={`h-2 w-2 shrink-0 rounded-full ${isActive ? "bg-success" : "bg-muted-foreground/30"}`} title={isActive ? "已启用" : "已停用"} />
              </button>
            );
          })}
        </div>

        {/* 右侧平台详情 */}
        <div className="min-w-0 flex-1 overflow-auto p-4">
          {active && (
            <div className="space-y-3">
              {/* 标题区 */}
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2.5">
                  {(() => { const Icon = PLATFORM_ICONS[active.code] || Globe; return <Icon className="h-5 w-5 shrink-0 text-muted-foreground" />; })()}
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold text-foreground">{PLATFORM_LABELS[active.code] || active.name}</h2>
                    <p className="truncate text-[11px] text-muted-foreground">
                      code: {active.code} · 类型: {BOT_TYPE_LABELS[active.bot_type] || active.bot_type}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${active.is_active === false ? "bg-destructive/10 text-destructive" : "bg-success/10 text-success"}`}>
                    <BadgeCheck className="h-3 w-3" />
                    {active.is_active === false ? "已停用" : "已启用"}
                  </span>
                  <button type="button" onClick={editMode ? cancelEdit : startEdit}
                    className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs transition-colors ${editMode ? "border-border text-muted-foreground hover:bg-muted/50" : "border-border bg-card text-muted-foreground hover:bg-muted/50"}`}
                  >
                    <Pencil className="h-3 w-3" />
                    {editMode ? "取消" : "编辑"}
                  </button>
                </div>
              </div>

              {editMode ? (
                <EditForm form={editForm} setForm={setEditForm} saving={saving} onSave={saveEdit} activeCode={active.code} />
              ) : (
                <>
                  {/* 决策卡三连：连接状态 / 回调健康度 / 待人工审核 */}
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <DecisionCard
                      bar={active.is_active === false ? "bg-destructive" : "bg-success"}
                      label="连接状态"
                      value={active.is_active === false ? "已停用" : "已启用"}
                      sub={activeCreds ? `凭证已配置 ${activeCreds.credentials.filter((c) => c.configured).length}/${activeCreds.credentials.length}` : "无凭证配置"}
                      onClick={startEdit}
                    />
                    <DecisionCard
                      bar={activeTone.bar}
                      label="回调健康度"
                      value={formatPercent(activeHealth?.botHandledRate ?? 0)}
                      sub={`${activeTone.label} · 24h 会话 ${activeHealth?.totalSessions ?? 0} 条`}
                      onClick={() => void fetchData()}
                    />
                    <DecisionCard
                      bar={activeHealth && activeHealth.pendingApproval > 0 ? "bg-warning" : "bg-muted"}
                      label="待人工审核"
                      value={`${activeHealth?.pendingApproval ?? 0} 条`}
                      sub={activeHealth && activeHealth.pendingApproval > 0 ? "需尽快处理" : "无积压"}
                    />
                  </div>

                  {/* 回调链路统计（chat-stats 真实指标，白底紧凑卡片） */}
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                    <StatCard icon={<Database className="h-3.5 w-3.5" />} label="24h 会话量" value={`${activeHealth?.totalSessions ?? 0}`} />
                    <StatCard icon={<Activity className="h-3.5 w-3.5" />} label="机器人处理率" value={formatPercent(activeHealth?.botHandledRate ?? 0)} />
                    <StatCard icon={<Workflow className="h-3.5 w-3.5" />} label="转人工率" value={formatPercent(activeHealth?.transferRate ?? 0)} />
                    <StatCard icon={<Shield className="h-3.5 w-3.5" />} label="独立接待率" value={formatPercent(activeHealth?.independentReceptionRate ?? 0)} />
                    <StatCard icon={<Heart className="h-3.5 w-3.5" />} label="平均情绪" value={formatRating(activeHealth?.avgSentiment ?? undefined, 5)} />
                  </div>

                  {/* 配置摘要（技术字段 → 人类可读） + 最近事件 */}
                  <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                    <div className="rounded-lg border border-border bg-card lg:col-span-2">
                      <div className="flex items-center justify-between border-b border-border px-3 py-2">
                        <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                          <Settings2 className="h-3.5 w-3.5 text-muted-foreground" />配置摘要
                        </h3>
                        <span className="text-[10px] text-muted-foreground">字段缺失显示 —</span>
                      </div>
                      {/* 技术字段 → 中文标签 */}
                      <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 px-3 py-2.5 text-xs sm:grid-cols-2">
                        <ConfigRow label="认证方式" value={activeCreds?.authMethod || "—"} />
                        <ConfigRow label="机器人类型" value={BOT_TYPE_LABELS[active.bot_type] || active.bot_type || "—"} />
                        <ConfigRow label="启用状态" value={active.is_active === false ? "已停用" : "已启用"} />
                        <ConfigRow label="回调地址" value={active.api_endpoint || "—"} />
                        <ConfigRow label="签名校验" value="—" />
                        <ConfigRow label="回调超时" value="—" />
                        <ConfigRow label="创建时间" value={formatDateTime(active.created_at)} />
                      </dl>
                      {activeCreds && (
                        <div className="border-t border-border px-3 py-2">
                          <div className="flex items-center justify-between">
                            <h4 className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground">
                              <KeyRound className="h-3 w-3" />凭证配置
                            </h4>
                            <span className={`text-[10px] font-medium ${activeCreds.credentials.filter((c) => c.configured).length === activeCreds.credentials.length ? "text-success" : "text-warning"}`}>
                              已配置 {activeCreds.credentials.filter((c) => c.configured).length}/{activeCreds.credentials.length} 项
                            </span>
                          </div>
                          <table className="mt-1.5 w-full text-xs">
                            <thead>
                              <tr className="border-b border-border text-left text-[10px] text-muted-foreground">
                                <th className="w-40 py-1.5 pr-2 font-medium">环境变量</th>
                                <th className="py-1.5 pr-2 font-medium">说明</th>
                                <th className="w-16 py-1.5 text-center font-medium">状态</th>
                              </tr>
                            </thead>
                            <tbody>
                              {activeCreds.credentials.map((c) => (
                                <tr key={c.key} className="border-b border-border/60 last:border-0">
                                  <td className="py-1.5 pr-2 font-mono text-[11px] text-muted-foreground">{c.key}</td>
                                  <td className="py-1.5 pr-2 text-muted-foreground/80">{c.description}</td>
                                  <td className="py-1.5 text-center">
                                    {c.configured
                                      ? <span className="font-medium text-success">已配置</span>
                                      : <span className="text-destructive">未配置</span>}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {activeCreds.credentials.filter((c) => c.configured).length < 2 && (
                            <p className="mt-2 flex items-center gap-1 text-[10px] text-warning">
                              <AlertTriangle className="h-3 w-3 shrink-0" />
                              至少需要 App ID + App Secret + Encrypt Key 才能运行
                            </p>
                          )}
                        </div>
                      )}
                    </div>

                    {/* 最近事件：暂无独立事件查询 API，缺省展示平台接入时间 */}
                    <div className="flex flex-col rounded-lg border border-border bg-card p-3">
                      <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                        <History className="h-3.5 w-3.5 text-muted-foreground" />最近事件
                      </h3>
                      <div className="mt-2.5 space-y-2 text-xs">
                        <div className="flex items-start gap-2">
                          <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-info" />
                          <div>
                            <div className="text-foreground">平台接入</div>
                            <div className="text-[10px] text-muted-foreground">{formatDateTime(active.created_at)}</div>
                          </div>
                        </div>
                        <p className="text-[11px] text-muted-foreground/70">暂无更多事件记录，可刷新查看最新状态。</p>
                      </div>
                      <button type="button" onClick={() => void fetchData()}
                        className="mt-auto inline-flex w-full items-center justify-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground hover:bg-muted/50">
                        <RefreshCw className="h-3 w-3" />刷新
                      </button>
                    </div>
                  </div>

                  {/* Webhook 端点 */}
                  {PLATFORM_ENDPOINTS[active.code] && (
                    <div className="rounded-lg border border-border bg-card p-3">
                      <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                        <Link className="h-3.5 w-3.5 text-muted-foreground" />Webhook 端点
                      </h3>
                      <code className="mt-1.5 block break-all rounded bg-muted px-2.5 py-1.5 text-[11px] text-muted-foreground">POST {PLATFORM_ENDPOINTS[active.code]}</code>
                      <p className="mt-1.5 text-[11px] text-muted-foreground">
                        {active.code === "feishu" ? "飞书开放平台 → 事件订阅 → 请求网址" :
                         active.code === "tmall" ? "天猫开放平台 → 消息推送 → 回调地址" : "平台回调地址"}
                      </p>
                    </div>
                  )}

                  {/* ── Feishu 专属：OAuth 扫码授权 ── */}
                  {active.code === "feishu" && (
                    <div className="rounded-lg border border-border bg-card p-3">
                      <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                        <QrCode className="h-3.5 w-3.5 text-muted-foreground" />飞书 OAuth 扫码授权
                      </h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        跳转飞书授权页面，扫码后系统自动获取并保存 user_access_token、refresh_token 等凭证到数据库。
                      </p>
                      <button type="button"
                        onClick={() => { window.open("/api/auth/feishu/login", "_blank", "width=600,height=700"); }}
                        className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90">
                        <QrCode className="h-3.5 w-3.5" />飞书扫码登录
                      </button>
                      <p className="mt-1.5 text-[10px] text-muted-foreground/60">
                        授权完成后自动返回本页面，凭证将存入 platform_credentials 表。
                      </p>
                    </div>
                  )}

                  {/* ── Feishu 专属：完整闭环链路 ── */}
                  {active.code === "feishu" && <FeishuClosedLoop />}

                  {/* ── Tmall 专属：店铺真实回复开关 ── */}
                  {active.code === "tmall" && (
                    <div className="rounded-lg border border-border bg-card p-3">
                      <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                        <Store className="h-3.5 w-3.5 text-muted-foreground" />店铺真实回复开关
                      </h3>
                      <p className="mt-1 text-xs text-muted-foreground">仅启用白名单中的店铺才会发送 AI 真实回复，其他店铺仅走影子回复。</p>
                      {Object.keys(storeSwitches).length === 0 ? (
                        <p className="mt-2 text-xs text-muted-foreground/60">暂无店铺配置。</p>
                      ) : (
                        <div className="mt-2 max-h-40 space-y-0.5 overflow-auto">
                          {Object.entries(storeSwitches).map(([nick, enabled]) => (
                            <div key={nick} className="flex items-center justify-between border-b border-border/60 py-1.5 last:border-0">
                              <span className="truncate text-xs text-foreground/80">{nick}</span>
                              <button type="button" onClick={() => toggleStore(nick, !enabled)}
                                className={`relative h-5 w-9 rounded-full transition-colors ${enabled ? "bg-success" : "bg-muted-foreground/20"}`}
                                aria-pressed={enabled}
                              >
                                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-card shadow transition-transform ${enabled ? "translate-x-4" : "translate-x-0.5"}`} />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="mt-2 flex gap-2 border-t border-border pt-2">
                        <input type="text" value={newStoreNick} onChange={(e) => setNewStoreNick(e.target.value)} placeholder="店铺昵称"
                          className="min-w-0 flex-1 rounded border border-border bg-card px-2 py-1.5 text-xs" onKeyDown={(e) => e.key === "Enter" && addStore()} />
                        <button onClick={addStore} className="inline-flex items-center gap-1 rounded bg-muted px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-border">
                          <Plus className="h-3 w-3" />添加
                        </button>
                      </div>
                    </div>
                  )}

                  {/* ── 平台配置（config 为 JSONB，缺省不展示） ── */}
                  {active.config && Object.keys(active.config).length > 1 && (
                    <div className="rounded-lg border border-border bg-card p-3">
                      <h3 className="text-xs font-semibold text-foreground">平台配置</h3>
                      <div className="mt-1.5 space-y-1">
                        {Object.entries(active.config).map(([k, v]) => (
                          <div key={k} className="flex gap-2 text-xs">
                            <span className="w-44 shrink-0 text-muted-foreground">{k}:</span>
                            <span className="truncate text-muted-foreground">{String(v)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 配置摘要单行：label + value，缺失显示 "—" ──────────────────────────

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="shrink-0 text-muted-foreground/70">{label}</dt>
      <dd className="truncate font-medium text-foreground" title={value}>{value}</dd>
    </div>
  );
}

// ── Feishu Closed-Loop Flow ──────────────────────────────────────────────

function FeishuClosedLoop() {
  const flowSteps = [
    { step: 1, title: "接入", desc: "用户发送消息", detail: "飞书开放平台 POST 消息到 Webhook 端点", tech: "HTTPS POST", endpoint: "POST /api/feishu/event", bar: "bg-info" },
    { step: 2, title: "验签", desc: "防假冒推送", detail: "X-Lark-Signature 头 + SHA256(FEISHU_EVENT_ENCRYPT_KEY + timestamp + nonce + body)", tech: "SHA256 + AES-256-CBC", bar: "bg-info" },
    { step: 3, title: "解密", desc: "AES 解密事件体", detail: "密文 base64 解码 → AES-256-CBC 解密 → JSON 解析 → 提取消息类型和内容", tech: "AES-256-CBC", bar: "bg-info" },
    { step: 4, title: "存储", desc: "写入 bot_chat_sessions", detail: "按 chat_id 去重，追加对话记录。同时写 feishu_raw_events 幂等存储", tech: "Supabase UPSERT", bar: "bg-muted" },
    { step: 5, title: "LLM", desc: "AI 生成回复", detail: "2s 超时，缓存命中直接返回。超时/失败降级为关键词匹配回复", tech: "Moonshot/Kimi API", bar: "bg-warning" },
    { step: 6, title: "质检", desc: "触发 auto-evaluation", detail: "fire-and-forget 调用 /api/qa/evaluate，生成 quality_report。不影响回复速度", tech: "async POST", bar: "bg-muted" },
    { step: 7, title: "返回", desc: "发送回复到用户", detail: "获取 tenant_access_token → POST 飞书消息 API → 用户收到回复", tech: "OAuth 2.0 → IM API", endpoint: "POST open.feishu.cn/open-apis/im/v1/messages", bar: "bg-success" },
    { step: 8, title: "降级", desc: "消息发送失败时", detail: "API 失败 → Webhook 兜底。通知类: 私信 → 个人 Webhook → 群聊 → 全局 Webhook", tech: "4-level fallback", bar: "bg-destructive" },
  ];

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-3">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
        <Workflow className="h-3.5 w-3.5 text-muted-foreground" />飞书完整闭环: 接入 → 处理 → 返回
      </h3>

      {/* ASCII flow summary */}
      <div className="overflow-x-auto whitespace-pre rounded border border-border bg-card p-3 font-mono text-[10px] text-muted-foreground">
{`飞书用户发消息 ──HTTPS POST──▶ /api/feishu/event
       │                                      │
       │  X-Lark-Signature                    │  SHA256 验签
       │  X-Lark-Request-Timestamp            │  AES-256-CBC 解密
       │  X-Lark-Request-Nonce                │  Token 校验
       │                                      │
       ▼                                      ▼
  飞书开放平台                           E-Sentinel
  (事件订阅)                            (本系统)
                                               │
                                          ┌────┴────┐
                                          │ LLM 回复 │ (2s 超时)
                                          │ 质检评估 │ (fire-and-forget)
                                          └────┬────┘
                                               │
       ▲                                      │
       │  OAuth 2.0 Bearer Token              │  sendFeishuMessage()
       │  POST im/v1/messages                 │
       │                                      ▼
  飞书用户收到回复 ◀──HTTP 200──────── 飞书 IM API`}
      </div>

      {/* Step 卡片：白底 + 左侧 3px 色条 */}
      <div className="space-y-1.5">
        {flowSteps.map((s) => (
          <div key={s.step} className="relative overflow-hidden rounded-lg border border-border bg-card p-2.5 pl-4">
            <span className={`absolute left-0 top-0 bottom-0 w-[3px] ${s.bar}`} aria-hidden="true" />
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-bold text-muted-foreground">{s.step}</span>
              <span className="text-xs font-semibold text-foreground">{s.title}</span>
              <span className="text-[10px] text-muted-foreground">{s.desc}</span>
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">{s.detail}</p>
            <div className="mt-0.5 flex items-center gap-2">
              {s.endpoint && <code className="inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{s.endpoint}</code>}
              <span className="text-[10px] text-muted-foreground/70">{s.tech}</span>
            </div>
          </div>
        ))}
      </div>

      <FeishuAuthDetail />
      <FeishuOutboundDetail />
    </div>
  );
}

function FeishuAuthDetail() {
  return (
    <div className="border-t border-border pt-2.5">
      <h4 className="mb-2 text-[11px] font-semibold text-muted-foreground">认证机制: OAuth 2.0 (client_credentials)</h4>
      <div className="space-y-1.5 rounded border border-border bg-card p-2.5 text-xs">
        <div className="flex items-start gap-2">
          <span className="shrink-0 font-mono text-muted-foreground/60">Step 1</span>
          <span className="text-muted-foreground">
            <code className="rounded bg-muted px-1">POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal</code>
          </span>
        </div>
        <div className="flex items-start gap-2">
          <span className="shrink-0 font-mono text-muted-foreground/60">Step 2</span>
          <span className="text-muted-foreground">
            Body: <code className="rounded bg-muted px-1">{`{ "app_id": "$FEISHU_APP_ID", "app_secret": "$FEISHU_APP_SECRET" }`}</code>
          </span>
        </div>
        <div className="flex items-start gap-2">
          <span className="shrink-0 font-mono text-muted-foreground/60">Step 3</span>
          <span className="text-muted-foreground">
            获取 <code className="rounded bg-muted px-1">tenant_access_token</code>（有效期 2 小时），每次调用消息 API 时通过 <code className="rounded bg-muted px-1">Authorization: Bearer {"<token>"}</code> 头传递
          </span>
        </div>
        <div className="flex items-start gap-2">
          <span className="shrink-0 font-mono text-muted-foreground/60">Step 4</span>
          <span className="text-muted-foreground">到期自动续期，无需手动刷新</span>
        </div>
      </div>
    </div>
  );
}

function FeishuOutboundDetail() {
  return (
    <div className="border-t border-border pt-2.5">
      <h4 className="mb-2 text-[11px] font-semibold text-muted-foreground">返回方式: 飞书消息 API + 四级降级</h4>
      <div className="space-y-1.5 text-xs">
        <OutboundRow level="主通道" method="Feishu IM API" endpoint="POST open.feishu.cn/open-apis/im/v1/messages" auth="Bearer {tenant_access_token}" tone="success" />
        <OutboundRow level="降级 1" method="全局 Webhook" endpoint="POST {FEISHU_WEBHOOK_URL}" auth="无 (webhook URL 自带鉴权)" tone="warning" />
        <OutboundRow level="通知路由" method="四级降级派发" detail="私信 → 个人 Webhook → 全局群聊 → 全局 Webhook" auth="dispatchAlert()" tone="neutral" />
      </div>
    </div>
  );
}

function OutboundRow({ level, method, endpoint, auth, detail, tone }: {
  level: string; method: string; endpoint?: string; auth: string; detail?: string; tone: string;
}) {
  const borderClass = tone === "success" ? "border-success/40" : tone === "warning" ? "border-warning/40" : "border-border";
  return (
    <div className={`flex items-start gap-2.5 rounded border ${borderClass} bg-card p-2`}>
      <span className="w-14 shrink-0 text-[10px] font-medium text-muted-foreground/60">{level}</span>
      <div className="min-w-0 flex-1">
        <span className="font-medium text-foreground/80">{method}</span>
        {endpoint && <code className="mt-0.5 block text-[10px] text-muted-foreground/80">{endpoint}</code>}
        {detail && <span className="mt-0.5 block text-muted-foreground/80">{detail}</span>}
        <span className="mt-0.5 block text-[10px] text-muted-foreground/60">鉴权: {auth}</span>
      </div>
    </div>
  );
}

// ── 编辑表单 ─────────────────────────────────────────────────────────────

function EditForm({ form, setForm, saving, onSave, activeCode }: {
  form: Record<string, string>;
  setForm: (f: Record<string, string>) => void;
  saving: boolean;
  onSave: () => void;
  activeCode: string;
}) {
  const [showSecrets, setShowSecrets] = useState(false);
  const isFeishu = activeCode === "feishu";

  return (
    <div className="space-y-4 rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">编辑平台信息</h3>
        {isFeishu && (
          <a href={`https://open.feishu.cn/app/${form.app_id || ''}`} target="_blank" rel="noopener noreferrer"
            className="text-xs text-brand-500 hover:underline">在飞书后台查看凭证 →</a>
        )}
      </div>

      {/* 基础字段 */}
      {[{ k: "name", l: "平台名称" }, { k: "code", l: "平台代码" }].map(({ k, l }) => (
        <div key={k} className="space-y-1">
          <label className="text-[10px] uppercase text-muted-foreground">{l}</label>
          <input type="text" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
            className="w-full rounded border border-border bg-card px-2 py-1.5 text-sm" />
        </div>
      ))}

      {/* 凭证字段 — 可折叠 */}
      <button type="button" onClick={() => setShowSecrets(!showSecrets)}
        className="flex items-center gap-1 text-xs text-brand-500 hover:underline">
        {showSecrets ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        {showSecrets ? "隐藏" : "展开"} 凭证配置 ({isFeishu ? "App ID / Secret / Encrypt Key" : "API Key / Secret"})
      </button>

      {showSecrets && (
        <div className="space-y-3 border-l-2 border-warning/40 pl-3">
          {isFeishu ? (
            <>
              {[
                { k: "app_id", l: "App ID", hint: "飞书开放平台 → 凭证与基础信息" },
                { k: "app_secret", l: "App Secret", hint: "与 App ID 在同一页面" },
                { k: "encrypt_key", l: "Encrypt Key", hint: "事件订阅 → 加密策略" },
                { k: "verify_token", l: "Verify Token", hint: "事件订阅 → 验证 Token" },
                { k: "group_chat_id", l: "群聊 ID", hint: "飞书群 → 设置 → 群 ID（oc_ 开头）" },
              ].map(({ k, l, hint }) => (
                <div key={k} className="space-y-1">
                  <label className="text-[10px] uppercase text-muted-foreground">{l}</label>
                  <input type="password" value={form[k] || ""}
                    onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                    placeholder={hint}
                    className="w-full rounded border border-border bg-card px-2 py-1.5 font-mono text-xs" />
                  <p className="text-[10px] text-muted-foreground/50">{hint}</p>
                </div>
              ))}
              {/* Feishu OAuth 扫码登录 */}
              <div className="pt-1">
                <p className="mb-2 text-xs text-muted-foreground">或者使用飞书 OAuth 扫码登录自动获取凭证：</p>
                <button type="button"
                  onClick={() => { window.open("/api/auth/feishu/login", "_blank", "width=600,height=700"); }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-info/10 px-3 py-1.5 text-xs text-info hover:bg-info/20">
                  <QrCode className="h-3.5 w-3.5" />飞书扫码登录
                </button>
                <p className="mt-1 text-[10px] text-muted-foreground/50">授权后凭证将自动保存到平台凭据表</p>
              </div>
            </>
          ) : (
            <>
              {[
                { k: "api_key", l: "API Key / App Key", hint: "平台开放平台获取" },
                { k: "api_secret", l: "API Secret / App Secret", hint: "与 Key 配套使用" },
                { k: "api_endpoint", l: "API 端点 URL", hint: "平台提供的回调地址" },
              ].map(({ k, l, hint }) => (
                <div key={k} className="space-y-1">
                  <label className="text-[10px] uppercase text-muted-foreground">{l}</label>
                  <input type="password" value={form[k] || ""}
                    onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                    placeholder={hint}
                    className="w-full rounded border border-border bg-card px-2 py-1.5 font-mono text-xs" />
                  <p className="text-[10px] text-muted-foreground/50">{hint}</p>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 pt-1">
        <button onClick={onSave} disabled={saving}
          className="rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600 disabled:opacity-50">
          {saving ? <span className="inline-flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" />保存中...</span> : "保存配置"}
        </button>
        <span className="text-xs text-muted-foreground/60">凭证通过 Supabase 加密存储</span>
      </div>
    </div>
  );
}
