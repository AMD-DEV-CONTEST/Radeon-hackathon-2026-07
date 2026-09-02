"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import Panel from "@/components/dashboard/Panel";
import { diffJson, hasChanges, type JsonDiff } from "@/lib/json-diff";
import type { Bot, BotConfig, BotPlatform, Platform } from "@/lib/types/bot";

const PLATFORM_LABELS: Record<string, string> = {
  tmall: "天猫", jd: "京东", vip: "唯品会", douyin: "抖音",
  pdd: "拼多多", kuaishou: "快手", xiaohongshu: "小红书", wechat: "微信小店",
};

const CONFIG_KEY_LABELS: Record<string, string> = {
  greeting_template: "欢迎语模板",
  product_recommend: "产品推荐策略",
  return_policy: "退换货政策",
  compensation_tiers: "补偿等级",
  live_stream_script: "直播话术脚本",
  douyin_after_sales: "抖音售后SLA",
  jd_price_match: "京东比价策略",
  pdd_low_price_strategy: "拼多多低价策略",
  objection_handling: "异议处理话术",
  complaint_escalation: "投诉升级机制",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-yellow-100 text-yellow-700 border-yellow-200",
  active: "bg-emerald-100 text-emerald-700 border-emerald-200",
  archived: "bg-muted text-muted-foreground/70 border-border",
};

const STATUS_OPTIONS = [
  { value: "active", label: "生效中" },
  { value: "draft", label: "待审核" },
  { value: "archived", label: "已归档" },
] as const;

// ── Bot Management constants ────────────────────────────────────────────────
const BOT_PLATFORM_LABELS: Record<BotPlatform, string> = {
  feishu: "飞书", taobao: "淘宝", tmall: "天猫", jd: "京东", pdd: "拼多多", web: "网页",
};
const BOT_PLATFORM_OPTIONS: { value: BotPlatform; label: string }[] = [
  { value: "feishu", label: "飞书" },
  { value: "taobao", label: "淘宝" },
  { value: "tmall", label: "天猫" },
  { value: "jd", label: "京东" },
  { value: "pdd", label: "拼多多" },
  { value: "web", label: "网页" },
];
const BOT_PLATFORM_COLORS: Record<string, string> = {
  feishu: "bg-blue-100 text-blue-700 border-blue-200",
  taobao: "bg-orange-100 text-orange-700 border-orange-200",
  tmall: "bg-red-100 text-red-700 border-red-200",
  jd: "bg-red-100 text-red-700 border-red-200",
  pdd: "bg-rose-100 text-rose-700 border-rose-200",
  web: "bg-muted text-muted-foreground border-border",
};
const DEFAULT_AVATAR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>`;

// 表单控件统一样式：白底 + 圆角细边框，遵循全站表单规范（宽度由使用处决定）
const FORM_INPUT_CLASS =
  "rounded-lg border border-border bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent";

/** 表单分组标题：小号加粗次级色文字，用于划分字段分区 */
function FormSectionTitle({ children }: { children: ReactNode }) {
  return <h4 className="text-xs font-semibold text-muted-foreground mb-2.5">{children}</h4>;
}

function formatSuggestion(raw: string): string {
  return raw.replace(/\\n/g, "\n");
}

function ConfigViewer({ raw }: { raw: unknown }) {
  // 先解析再渲染：try/catch 内不返回 JSX（React 渲染错误不会被 try 捕获）
  let obj: Record<string, unknown> | null = null;
  let isPlain = false;
  try {
    const candidate = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (typeof candidate === "object" && candidate !== null && !Array.isArray(candidate)) {
      obj = candidate as Record<string, unknown>;
    } else {
      isPlain = true;
    }
  } catch {
    isPlain = true;
  }

  if (isPlain || !obj) {
    return <span className="text-sm text-muted-foreground/70">{String(raw)}</span>;
  }

  const entries = Object.entries(obj);
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-4 bg-muted/40 rounded-lg border border-border/60">
      {entries.map(([key, value]) => {
        const label = CONFIG_FIELD_LABELS[key] || key;
        return (
          <div key={key} className={`flex flex-col ${key === "enable" || key === "is_active" ? "" : entries.length === 1 ? "col-span-2" : ""}`}>
            <span className="text-[10px] font-medium text-muted-foreground/50 uppercase tracking-wide mb-1">{label}</span>
            {typeof value === "boolean" ? (
              <span className={`text-sm font-medium ${value ? "text-success" : "text-muted-foreground"}`}>
                {value ? "已启用" : "已禁用"}
              </span>
            ) : typeof value === "string" && value.length > 80 ? (
              <div className="p-2.5 bg-white border border-border rounded text-sm text-foreground/80 leading-relaxed">
                &ldquo;{value}&rdquo;
              </div>
            ) : typeof value === "string" ? (
              <span className="text-sm text-foreground/70">{value}</span>
            ) : typeof value === "number" ? (
              <span className="text-sm font-mono text-foreground/70">{value}</span>
            ) : (
              <pre className="text-xs text-muted-foreground/70">{JSON.stringify(value, null, 2)}</pre>
            )}
          </div>
        );
      })}
    </div>
  );
}

const CONFIG_FIELD_LABELS: Record<string, string> = {
  enable: "策略状态",
  is_active: "启用状态",
  reason: "内部原因记录",
  redirect_msg: "客服兜底回复话术",
  response_template: "回复模板",
  greeting: "欢迎语",
  escalation_path: "升级路径",
  priority_level: "优先级",
  max_retries: "最大重试次数",
  timeout_sec: "超时时间(秒)",
  keywords: "触发关键词",
  exclude_categories: "排除类目",
  fallback_message: "兜底回复",
};

export default function BotConfigPanel() {
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [activePlatform, setActivePlatform] = useState<string>("");
  const [configs, setConfigs] = useState<BotConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("active");
  const [pendingCount, setPendingCount] = useState(0);
  const [rejectTarget, setRejectTarget] = useState<BotConfig | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [publishing, setPublishing] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchPublishing, setBatchPublishing] = useState(false);
  const [diffTarget, setDiffTarget] = useState<BotConfig | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  // ── Bot Management state ──────────────────────────────────────────────────
  const [viewMode, setViewMode] = useState<"templates" | "bots">("templates");
  const [bots, setBots] = useState<Bot[]>([]);
  const [botsLoading, setBotsLoading] = useState(false);
  const [botsError, setBotsError] = useState<string | null>(null);
  const [botModalOpen, setBotModalOpen] = useState(false);
  const [editingBot, setEditingBot] = useState<Bot | null>(null);
  const [botSaving, setBotSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Bot | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [prompts, setPrompts] = useState<{ id: string; name: string }[]>([]);
  const [modelConfigs, setModelConfigs] = useState<{ id: string; name: string }[]>([]);
  const [togglingBotId, setTogglingBotId] = useState<string | null>(null);

  // Bot form state
  const [botForm, setBotForm] = useState({
    name: "",
    avatar: "",
    welcome_message: "",
    platform: "feishu" as BotPlatform,
    working_hours_start: "09:00",
    working_hours_end: "22:00",
    // GoFly performs substring matching on these values. Keep the default
    // narrow so ordinary replies containing "人工" cannot trigger handoff.
    transfer_keywords: ["转人工"] as string[],
    prompt_id: "",
    model_config_id: "",
    is_active: true,
    keyword_input: "",
  });

  const fetchPlatforms = useCallback(async () => {
    setError(null);
    const res = await fetch("/api/qa/platforms");
    if (res.ok) {
      const data = await res.json();
      const list = data.platforms || [];
      setPlatforms(list);
      if (!activePlatform && list.length > 0) {
        setActivePlatform(String(list[0].id));
      }
    } else {
      setError("无法加载平台列表");
    }
  }, []);

  useEffect(() => {
    fetchPlatforms();
  }, [fetchPlatforms]);

  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  const fetchConfigs = useCallback(async () => {
    if (!activePlatform) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/qa/bot-configs?platform_id=${activePlatform}&limit=50&status=${statusFilter}`);
      if (res.ok) {
        const data = await res.json();
        setConfigs(data.configs || []);
      } else {
        const errData = await res.json().catch(() => ({ error: "request failed" }));
        setError(errData.error || "加载话术配置失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setLoading(false);
  }, [activePlatform, statusFilter]);

  useEffect(() => {
    if (activePlatform) fetchConfigs();
  }, [activePlatform, fetchConfigs]);

  // ── Bot Management functions ──────────────────────────────────────────────
  const fetchBots = useCallback(async () => {
    setBotsLoading(true);
    setBotsError(null);
    try {
      const res = await fetch("/api/qa/bots?limit=100");
      if (res.ok) {
        const data = await res.json();
        setBots(data.bots || []);
      } else {
        const errData = await res.json().catch(() => ({ error: "加载失败" }));
        setBotsError(errData.error || "加载机器人列表失败");
      }
    } catch {
      setBotsError("网络请求失败，请检查后端服务");
    }
    setBotsLoading(false);
  }, []);

  const fetchReferences = useCallback(async () => {
    // 拉取 Prompt 下拉选项
    try {
      const pRes = await fetch("/api/qa/prompts?limit=100&status=published");
      if (pRes.ok) {
        const data = await pRes.json();
        setPrompts((data.prompts || []).map((p: { id: string; name: string }) => ({ id: p.id, name: p.name })));
      }
    } catch { /* ignore */ }
  }, []);

  // Fetch model configs directly
  const fetchModelConfigs = useCallback(async () => {
    try {
      const res = await fetch("/api/qa/model-configs");
      if (res.ok) {
        const data = await res.json();
        setModelConfigs(data.configs || []);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (viewMode === "bots") {
      fetchBots();
      fetchReferences();
      fetchModelConfigs();
    }
  }, [viewMode, fetchBots, fetchReferences, fetchModelConfigs]);

  const resetBotForm = () => {
    setBotForm({
      name: "",
      avatar: "",
      welcome_message: "",
      platform: "feishu" as BotPlatform,
      working_hours_start: "09:00",
      working_hours_end: "22:00",
      transfer_keywords: ["转人工"],
      prompt_id: "",
      model_config_id: "",
      is_active: true,
      keyword_input: "",
    });
  };

  const openCreateBotModal = () => {
    setEditingBot(null);
    resetBotForm();
    setBotModalOpen(true);
  };

  const openEditBotModal = (bot: Bot) => {
    setEditingBot(bot);
    const wh = bot.working_hours || { start: "09:00", end: "22:00" };
    setBotForm({
      name: bot.name,
      avatar: bot.avatar || "",
      welcome_message: bot.welcome_message || "",
      platform: bot.platform,
      working_hours_start: wh.start || "09:00",
      working_hours_end: wh.end || "22:00",
      transfer_keywords: Array.isArray(bot.transfer_keywords) ? [...bot.transfer_keywords] : [],
      prompt_id: bot.prompt_id || "",
      model_config_id: bot.model_config_id || "",
      is_active: bot.is_active,
      keyword_input: "",
    });
    setBotModalOpen(true);
  };

  const handleSaveBot = async () => {
    if (!botForm.name.trim()) return;
    setBotSaving(true);
    try {
      const payload = {
        name: botForm.name.trim(),
        avatar: botForm.avatar.trim() || null,
        welcome_message: botForm.welcome_message.trim(),
        platform: botForm.platform,
        working_hours: {
          start: botForm.working_hours_start,
          end: botForm.working_hours_end,
          timezone: "Asia/Shanghai",
        },
        transfer_keywords: botForm.transfer_keywords,
        prompt_id: botForm.prompt_id || null,
        model_config_id: botForm.model_config_id || null,
        is_active: botForm.is_active,
      };

      if (editingBot) {
        const res = await fetch(`/api/qa/bots/${editingBot.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ error: "保存失败" }));
          throw new Error(err.error || "保存失败");
        }
      } else {
        const res = await fetch("/api/qa/bots", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ error: "创建失败" }));
          throw new Error(err.error || "创建失败");
        }
      }
      setBotModalOpen(false);
      fetchBots();
      setToast({ message: editingBot ? "机器人已更新" : "机器人已创建", type: "success" });
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "操作失败", type: "error" });
    }
    setBotSaving(false);
  };

  const handleToggleActive = async (bot: Bot) => {
    setTogglingBotId(bot.id);
    try {
      const res = await fetch(`/api/qa/bots/${bot.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !bot.is_active }),
      });
      if (!res.ok) throw new Error("操作失败");
      fetchBots();
      setToast({ message: bot.is_active ? "机器人已停用" : "机器人已启用", type: "success" });
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "操作失败", type: "error" });
    }
    setTogglingBotId(null);
  };

  const handleDeleteBot = async () => {
    if (!deleteTarget) return;
    setDeleteLoading(true);
    try {
      const res = await fetch(`/api/qa/bots/${deleteTarget.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("删除失败");
      setToast({ message: `机器人 "${deleteTarget.name}" 已删除`, type: "success" });
      setDeleteTarget(null);
      fetchBots();
    } catch (e) {
      setToast({ message: e instanceof Error ? e.message : "删除失败", type: "error" });
    }
    setDeleteLoading(false);
  };

  const addKeyword = () => {
    const kw = botForm.keyword_input.trim();
    if (kw && !botForm.transfer_keywords.includes(kw)) {
      setBotForm((prev) => ({
        ...prev,
        transfer_keywords: [...prev.transfer_keywords, kw],
        keyword_input: "",
      }));
    }
  };

  const removeKeyword = (kw: string) => {
    setBotForm((prev) => ({
      ...prev,
      transfer_keywords: prev.transfer_keywords.filter((k) => k !== kw),
    }));
  };

  // ── Existing: Fetch pending count for badge ───────────────────────────────
  useEffect(() => {
    fetch(`/api/qa/bot-configs/pending?limit=100`)
      .then((r) => r.json())
      .then((data) => setPendingCount((data.configs || []).length))
      .catch(() => {});
  }, [configs]);

  const handlePublish = async (id: string) => {
    setPublishing(id);
    await fetch(`/api/qa/bot-configs/${id}/publish`, { method: "POST" });
    setPublishing(null);
    fetchConfigs();
  };

  const handleReject = async () => {
    if (!rejectTarget) return;
    setRejecting(true);
    await fetch(`/api/qa/bot-configs/${rejectTarget.id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "人工审核驳回" }),
    });
    setRejecting(false);
    setRejectTarget(null);
    fetchConfigs();
  };

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  };

  const selectAll = () => {
    if (selectedIds.size === configs.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(configs.map((c) => c.id)));
    }
  };

  const handleBatchPublish = async () => {
    if (selectedIds.size === 0) return;
    setBatchPublishing(true);
    let published = 0;
    for (const id of selectedIds) {
      const res = await fetch(`/api/qa/bot-configs/${id}/publish`, { method: "POST" });
      if (res.ok) published++;
    }
    setBatchPublishing(false);
    setSelectedIds(new Set());
    fetchConfigs();
  };

  const handleDiff = async (config: BotConfig) => {
    if (diffTarget) { setDiffTarget(null); return; }
    setDiffLoading(true);
    try {
      const res = await fetch(`/api/qa/bot-configs?platform_id=${activePlatform}&config_type=${config.config_type}&status=active&limit=50`);
      if (res.ok) {
        const data = await res.json();
        const active = (data.configs || []).find(
          (c: BotConfig) => c.config_key === config.config_key
        );
        setDiffTarget(active || null);
      }
    } catch { /* skip */ }
    setDiffLoading(false);
  };

  const handleActivate = async (id: string) => {
    await fetch(`/api/qa/bot-configs/${id}/activate`, { method: "POST" });
    fetchConfigs();
  };

  const handleSuggest = async () => {
    setSuggesting(true);
    setSuggestion(null);
    setError(null);
    try {
      const res = await fetch("/api/qa/bot-configs/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform_id: activePlatform }),
      });
      if (res.ok) {
        const data = await res.json();
        const text = typeof data?.suggestion === "string" ? data.suggestion
          : typeof data?.recommendation === "string" ? data.recommendation
          : typeof data === "string" ? data
          : JSON.stringify(data, null, 2);
        setSuggestion(text);
      } else {
        setError("LLM 建议生成失败，请稍后重试");
      }
    } catch {
      setError("LLM 服务暂不可用");
    }
    setSuggesting(false);
  };

  const handleBootstrap = async () => {
    setBootstrapping(true);
    setError(null);
    try {
      const res = await fetch("/api/qa/bot-configs/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform_id: activePlatform }),
      });
      if (res.ok) {
        fetchConfigs();
      } else {
        const errData = await res.json().catch(() => ({ error: "生成失败" }));
        setError(errData.error || "初始配置生成失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setBootstrapping(false);
  };

  const activePlatformInfo = platforms.find((p) => String(p.id) === activePlatform);
  const activePlatformName = activePlatformInfo
    ? PLATFORM_LABELS[activePlatformInfo.code] || activePlatformInfo.name
    : "未知平台";

  const isEmpty = !loading && !error && configs.length === 0;

  function DiffViewer({ diff }: { diff: JsonDiff }) {
    if (!hasChanges(diff)) {
      return <p className="text-xs text-muted-foreground/50 py-2">与当前生效版本无差异</p>;
    }
    return (
      <div className="space-y-2 text-xs">
        {Object.entries(diff.added).map(([key, val]) => (
          <div key={key} className="flex items-start gap-2 p-1.5 rounded bg-emerald-50 border border-emerald-100">
            <span className="shrink-0 text-emerald-600 font-mono text-[10px]">+ {key}</span>
            <code className="text-emerald-800 break-all">{JSON.stringify(val)}</code>
          </div>
        ))}
        {Object.entries(diff.removed).map(([key, val]) => (
          <div key={key} className="flex items-start gap-2 p-1.5 rounded bg-red-50 border border-red-100">
            <span className="shrink-0 text-red-500 font-mono text-[10px]">- {key}</span>
            <code className="text-red-700 break-all">{JSON.stringify(val)}</code>
          </div>
        ))}
        {Object.entries(diff.changed).map(([key, { old: o, new: n }]) => (
          <div key={key} className="p-1.5 rounded bg-amber-50 border border-amber-100 space-y-1">
            <span className="text-amber-600 font-mono text-[10px]">~ {key}</span>
            <div className="flex items-start gap-2">
              <code className="text-red-600 line-through break-all text-[11px]">{JSON.stringify(o)}</code>
              <span className="text-muted-foreground/20">&rarr;</span>
              <code className="text-emerald-700 break-all text-[11px]">{JSON.stringify(n)}</code>
            </div>
          </div>
        ))}
      </div>
    );
  }

  function EffectMetrics({ config }: { config: BotConfig }) {
    const metrics = config.effect_metrics;
    if (!metrics || Object.keys(metrics).length === 0) return null;
    return (
      <div className="flex gap-3 flex-wrap mt-2">
        {metrics.pre_publish_satisfaction != null && (
          <div className="rounded-lg bg-white border border-border px-3 py-1.5">
            <span className="text-[10px] text-muted-foreground/50">发布前满意度</span>
            <span className="ml-1.5 text-xs font-semibold text-foreground/70">{Number(metrics.pre_publish_satisfaction).toFixed(1)}</span>
          </div>
        )}
        {metrics.problem_session_count != null && (
          <div className="rounded-lg bg-white border border-border px-3 py-1.5">
            <span className="text-[10px] text-muted-foreground/50">问题会话</span>
            <span className="ml-1.5 text-xs font-semibold text-foreground/70">{String(metrics.problem_session_count)}</span>
          </div>
        )}
        {metrics.llm_confidence != null && (
          <div className="rounded-lg bg-white border border-border px-3 py-1.5">
            <span className="text-[10px] text-muted-foreground/50">LLM 置信度</span>
            <span className="ml-1.5 text-xs font-semibold text-foreground/70">{(Number(metrics.llm_confidence) * 100).toFixed(0)}%</span>
          </div>
        )}
        {metrics.auto_published === true && (
          <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-1.5">
            <span className="text-[10px] text-emerald-600">自动发布</span>
            <span className="ml-1.5 text-xs font-semibold text-emerald-700">是</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <Panel
      title={viewMode === "templates" ? "话术配置" : "机器人管理"}
      subtitle={viewMode === "templates" ? "多平台客服机器人话术模板管理" : "客服机器人实例管理与配置"}
      loading={viewMode === "templates" ? loading : botsLoading}
      error={viewMode === "templates" ? error : botsError}
      onRetry={viewMode === "templates" ? fetchConfigs : fetchBots}
      empty={viewMode === "templates" ? isEmpty : !botsLoading && !botsError && bots.length === 0}
      emptyTitle={viewMode === "templates" ? "暂无话术配置" : "暂无机器人"}
      emptyDescription={viewMode === "templates" ? `${activePlatformName} 暂无话术配置，点击右上角按钮生成第一条配置` : "点击右上角按钮创建第一个客服机器人"}
      actions={
        <div className="flex items-center gap-2">
          {/* View mode toggle */}
          <div className="flex rounded-lg border border-border bg-muted/50 p-0.5 mr-1">
            <button
              type="button"
              onClick={() => setViewMode("templates")}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                viewMode === "templates"
                  ? "bg-white text-foreground shadow-sm"
                  : "text-muted-foreground/70 hover:text-foreground/70"
              }`}
            >
              话术模板
            </button>
            <button
              type="button"
              onClick={() => setViewMode("bots")}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                viewMode === "bots"
                  ? "bg-white text-foreground shadow-sm"
                  : "text-muted-foreground/70 hover:text-foreground/70"
              }`}
            >
              机器人
            </button>
          </div>
          {viewMode === "templates" ? (
            isEmpty ? (
              <Button size="sm" onClick={handleBootstrap} disabled={bootstrapping}>
                {bootstrapping ? "生成中..." : "生成第一条配置"}
              </Button>
            ) : (
              <Button size="sm" onClick={handleSuggest} disabled={suggesting}>
                {suggesting ? "生成建议中..." : "LLM 话术优化建议"}
              </Button>
            )
          ) : (
            <Button size="sm" onClick={openCreateBotModal}>
              创建机器人
            </Button>
          )}
        </div>
      }
    >
      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium animate-toast-in ${
            toast.type === "success" ? "bg-emerald-500 text-white" : "bg-red-500 text-white"
          }`}
        >
          {toast.message}
        </div>
      )}
      {viewMode === "templates" ? (
      <div className="space-y-4">

        {/* LLM suggestion card */}
        {suggestion && (
          <Card className="border-blue-200 bg-gradient-to-r from-blue-50 to-white">
            <CardHeader className="pb-2 flex flex-row items-center justify-between">
              <CardTitle className="text-sm text-blue-700">LLM 优化建议</CardTitle>
              <button className="text-xs text-blue-500 hover:text-blue-700" onClick={() => setSuggestion(null)}>收起</button>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-foreground/70 whitespace-pre-wrap leading-relaxed max-h-[300px] overflow-y-auto">
                {formatSuggestion(suggestion)}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Platform selector */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground/70 shrink-0">平台：</span>
          <div className="flex gap-1.5 flex-wrap">
            {platforms.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setActivePlatform(String(p.id))}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  String(p.id) === activePlatform
                    ? "bg-zinc-900 text-white shadow-sm"
                    : "bg-white border border-border text-muted-foreground hover:bg-muted hover:border-muted-foreground/20"
                }`}
              >
                {PLATFORM_LABELS[p.code] || p.name}
              </button>
            ))}
          </div>
        </div>

        {/* Status filter tabs */}
        <div className="flex items-center gap-1.5">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setStatusFilter(opt.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                statusFilter === opt.value
                  ? "bg-zinc-900 text-white shadow-sm"
                  : "bg-white border border-border text-muted-foreground hover:bg-muted hover:border-muted-foreground/20"
              }`}
            >
              {opt.label}
              {opt.value === "draft" && pendingCount > 0 && (
                <span className={`ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold ${
                  statusFilter === "draft" ? "bg-white text-zinc-900" : "bg-yellow-500 text-white"
                }`}>
                  {pendingCount}
                </span>
              )}
            </button>
          ))}
          <span className="text-xs text-muted-foreground/50 ml-2">{configs.length} 条配置</span>
        </div>

        {/* Config list */}
        <Card>
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <div className="flex items-center gap-3">
              <CardTitle className="text-sm">{activePlatformName} · 话术列表</CardTitle>
              <span className="text-xs text-muted-foreground/50">
                {statusFilter === "active" ? "生效中" : statusFilter === "draft" ? "待审核" : "已归档"}
              </span>
              {statusFilter === "draft" && selectedIds.size > 0 && (
                <Button
                  size="sm"
                  onClick={handleBatchPublish}
                  disabled={batchPublishing}
                  className="ml-auto"
                >
                  {batchPublishing ? "批量发布中..." : `批量发布 (${selectedIds.size})`}
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3 py-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-10 bg-muted rounded animate-pulse" />
                ))}
              </div>
            ) : error ? (
              <div className="text-center py-8">
                <p className="text-sm text-red-600 mb-1">数据加载失败</p>
                <p className="text-xs text-muted-foreground/50 mb-3">{error}</p>
                <Button size="sm" variant="outline" onClick={fetchConfigs}>重新加载</Button>
              </div>
            ) : configs.length === 0 ? (
              <div className="text-center py-8">
                <p className="text-sm text-muted-foreground/70 mb-1">{activePlatformName} 暂无话术配置</p>
                <p className="text-xs text-muted-foreground/50">点击上方「LLM 话术优化建议」按钮生成第一条配置</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    {statusFilter === "draft" && (
                      <TableHead className="w-[40px]">
                        <input
                          type="checkbox"
                          checked={selectedIds.size === configs.length && configs.length > 0}
                          onChange={selectAll}
                          className="w-4 h-4 rounded border-muted-foreground/20 accent-zinc-900"
                        />
                      </TableHead>
                    )}
                    <TableHead className="w-[160px]">配置项</TableHead>
                    <TableHead className="w-[72px]">类型</TableHead>
                    <TableHead className="w-[56px]">版本</TableHead>
                    <TableHead className="w-[80px]">状态</TableHead>
                    <TableHead className="w-[80px]">更新人</TableHead>
                    <TableHead>变更说明</TableHead>
                    <TableHead className="text-right w-[120px]">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {configs.map((c) => (
                    <TableRow key={c.id} className={`hover:bg-muted/50 ${expanded === c.id ? "bg-muted/50" : ""}`}>
                      {statusFilter === "draft" && (
                        <TableCell>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(c.id)}
                            onChange={() => toggleSelect(c.id)}
                            className="w-4 h-4 rounded border-muted-foreground/20 accent-zinc-900"
                          />
                        </TableCell>
                      )}
                      <TableCell className="font-medium text-xs">
                        {CONFIG_KEY_LABELS[c.config_key] || c.config_key}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px]">
                          {c.config_type === "pre_sale" ? "售前" : "售后"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground/70">v{c.version}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={`text-[10px] ${STATUS_COLORS[c.status] || ""}`}>
                          {c.status === "active" ? "生效中" : c.status === "draft" ? "草稿" : "已归档"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground/70">
                        运营·{(c.updated_by || "0000").slice(-4)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground/70 max-w-[200px] truncate">
                        {c.change_summary || "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            className="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors"
                            onClick={() => setExpanded(expanded === c.id ? null : c.id)}
                          >
                            {expanded === c.id ? "收起" : "详情"}
                          </button>
                          {c.status === "draft" && (
                            <>
                              <button
                                className="text-xs text-emerald-600 hover:text-emerald-800 hover:underline transition-colors"
                                onClick={() => handlePublish(c.id)}
                                disabled={publishing === c.id}
                              >
                                {publishing === c.id ? "发布中..." : "发布"}
                              </button>
                              <button
                                className="text-xs text-red-500 hover:text-red-700 hover:underline transition-colors"
                                onClick={() => setRejectTarget(c)}
                              >
                                驳回
                              </button>
                            </>
                          )}
                          {c.status === "archived" && (
                            <button
                              className="text-xs text-emerald-600 hover:text-emerald-800 hover:underline transition-colors"
                              onClick={() => handleActivate(c.id)}
                            >
                              启用
                            </button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Expanded config detail */}
        {expanded && (() => {
          const cfg = configs.find((c) => c.id === expanded);
          if (!cfg) return null;
          const cfgDiff = diffTarget
            ? diffJson(diffTarget.config_value as Record<string, unknown>, cfg.config_value as Record<string, unknown>)
            : null;
          return (
            <Card className="border-blue-100">
              <CardHeader className="pb-2 flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-sm">
                    {CONFIG_KEY_LABELS[cfg.config_key] || cfg.config_key}
                    <span className="ml-2 text-xs text-muted-foreground/50 font-normal">v{cfg.version}</span>
                    {cfgDiff && <span className="ml-2 text-[10px] text-blue-500">对比 v{diffTarget?.version}</span>}
                  </CardTitle>
                  <p className="text-xs text-muted-foreground/50 mt-0.5">{cfg.change_summary || "无变更说明"}</p>
                  <EffectMetrics config={cfg} />
                </div>
                <div className="flex items-center gap-2">
                  {cfg.status === "draft" && (
                    <button
                      className={`text-xs transition-colors ${diffTarget ? "text-amber-600 hover:text-amber-800" : "text-blue-600 hover:text-blue-800"}`}
                      onClick={() => handleDiff(cfg)}
                      disabled={diffLoading}
                    >
                      {diffLoading ? "加载中..." : diffTarget ? "隐藏对比" : "对比当前版本"}
                    </button>
                  )}
                  <button
                    className="text-xs text-muted-foreground/50 hover:text-muted-foreground"
                    onClick={() => { setExpanded(null); setDiffTarget(null); }}
                  >
                    关闭
                  </button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {cfgDiff ? (
                  <>
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground/70 mb-2">版本差异</h4>
                      <DiffViewer diff={cfgDiff} />
                    </div>
                    <div className="border-t border-muted pt-3">
                      <h4 className="text-xs font-medium text-muted-foreground/70 mb-2">新版本内容</h4>
                      <ConfigViewer raw={cfg.config_value} />
                    </div>
                  </>
                ) : (
                  <ConfigViewer raw={cfg.config_value} />
                )}
              </CardContent>
            </Card>
          );
        })()}
      </div>
      ) : (
      /* ======================================================================
         Bot Management View
         ====================================================================== */
      <div className="space-y-4">
        {/* Bot cards grid */}
        {bots.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {bots.map((bot) => (
              <Card key={bot.id} className={`overflow-hidden transition-shadow hover:shadow-md ${!bot.is_active ? "opacity-60" : ""}`}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      {/* Avatar */}
                      {bot.avatar ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={bot.avatar}
                          alt={bot.name}
                          className="w-10 h-10 rounded-full object-cover border border-border"
                          onError={(e) => {
                            (e.target as HTMLImageElement).style.display = "none";
                            (e.target as HTMLImageElement).nextElementSibling?.classList.remove("hidden");
                          }}
                        />
                      ) : null}
                      <div
                        className={`w-10 h-10 rounded-full border border-border flex items-center justify-center text-muted-foreground/50 bg-muted/50 ${bot.avatar ? "hidden" : ""}`}
                        dangerouslySetInnerHTML={{ __html: DEFAULT_AVATAR_SVG }}
                      />
                      <div>
                        <CardTitle className="text-sm flex items-center gap-2">
                          {bot.name}
                          {!bot.is_active && (
                            <Badge variant="outline" className="text-[10px] bg-muted text-muted-foreground/70 border-border">
                              已停用
                            </Badge>
                          )}
                        </CardTitle>
                        <div className="flex items-center gap-2 mt-0.5">
                          <Badge
                            variant="outline"
                            className={`text-[10px] ${BOT_PLATFORM_COLORS[bot.platform] || "bg-muted text-muted-foreground border-border"}`}
                          >
                            {BOT_PLATFORM_LABELS[bot.platform] || bot.platform}
                          </Badge>
                        </div>
                      </div>
                    </div>
                    {/* Toggle active switch */}
                    <button
                      type="button"
                      onClick={() => handleToggleActive(bot)}
                      disabled={togglingBotId === bot.id}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                        bot.is_active ? "bg-emerald-500" : "bg-muted-foreground/20"
                      } ${togglingBotId === bot.id ? "opacity-50" : ""}`}
                      title={bot.is_active ? "点击停用" : "点击启用"}
                    >
                      <span
                        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                          bot.is_active ? "translate-x-4" : "translate-x-0"
                        }`}
                      />
                    </button>
                  </div>
                </CardHeader>
                <CardContent className="pt-0 space-y-2">
                  {/* Welcome message preview */}
                  <p className="text-xs text-muted-foreground/70 line-clamp-2 leading-relaxed">
                    {bot.welcome_message || "未设置欢迎语"}
                  </p>

                  {/* Prompt & Model info */}
                  <div className="flex flex-wrap gap-1.5 text-[10px] text-muted-foreground/50">
                    {bot.prompt_name ? (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-purple-50 border border-purple-100 text-purple-600">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                        </svg>
                        {bot.prompt_name}
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground/50">无提示词</span>
                    )}
                    {bot.model_name ? (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-50 border border-blue-100 text-blue-600">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714a2.25 2.25 0 01-.659 1.591L12 14.5M14.25 3.104c.251.023.501.05.75.082m-1.5 0c.262.027.524.054.75.082m0 0v5.714a2.25 2.25 0 01-.659 1.591L13.5 14.5" />
                        </svg>
                        {bot.model_name}
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground/50">无模型</span>
                    )}
                  </div>

                  {/* Working hours */}
                  {bot.working_hours && (
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground/50">
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      {bot.working_hours.start} - {bot.working_hours.end}
                    </div>
                  )}

                  {/* Transfer keywords */}
                  {bot.transfer_keywords && bot.transfer_keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {bot.transfer_keywords.slice(0, 3).map((kw, i) => (
                        <span key={i} className="px-1.5 py-0.5 rounded bg-amber-50 border border-amber-100 text-[10px] text-amber-700">
                          {kw}
                        </span>
                      ))}
                      {bot.transfer_keywords.length > 3 && (
                        <span className="text-[10px] text-muted-foreground/50">+{bot.transfer_keywords.length - 3}</span>
                      )}
                    </div>
                  )}

                  {/* Quick actions */}
                  <div className="flex items-center gap-1.5 pt-2 border-t border-muted">
                    <button
                      type="button"
                      onClick={() => openEditBotModal(bot)}
                      className="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors"
                    >
                      编辑
                    </button>
                    <span className="text-border">|</span>
                    <button
                      type="button"
                      onClick={() => handleToggleActive(bot)}
                      disabled={togglingBotId === bot.id}
                      className={`text-xs transition-colors hover:underline ${
                        bot.is_active
                          ? "text-amber-600 hover:text-amber-800"
                          : "text-emerald-600 hover:text-emerald-800"
                      }`}
                    >
                      {bot.is_active ? "停用" : "启用"}
                    </button>
                    <span className="text-border">|</span>
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(bot)}
                      className="text-xs text-red-500 hover:text-red-700 hover:underline transition-colors"
                    >
                      删除
                    </button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Bot Create/Edit Modal — 创建/编辑机器人弹窗 */}
        {botModalOpen && (
          <div className="fixed inset-0 z-50 overflow-y-auto">
            {/* Overlay */}
            <div className="fixed inset-0 bg-black/30 transition-opacity" onClick={() => setBotModalOpen(false)} />
            {/* Modal：flex 纵向三段式布局，头部/内容区/底部操作区分离 */}
            <div className="relative min-h-screen flex items-center justify-center p-4">
              <div
                className="relative bg-card rounded-xl shadow-xl max-w-lg w-full flex flex-col max-h-[calc(100vh-4rem)]"
                onClick={(e) => e.stopPropagation()}
              >
                {/* 头部（固定） */}
                <div className="flex items-center justify-between px-6 pt-5 pb-4 shrink-0">
                  <h3 className="text-base font-semibold text-foreground">
                    {editingBot ? "编辑机器人" : "创建机器人"}
                  </h3>
                  <button
                    type="button"
                    onClick={() => setBotModalOpen(false)}
                    className="text-muted-foreground/50 hover:text-muted-foreground transition-colors"
                  >
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {/* 内容区（独立滚动，不遮挡底部操作区） */}
                <div className="flex-1 overflow-y-auto px-6 pb-2 space-y-6">
                  {/* ── 基础信息：平台 / 名称 / 头像 / 欢迎语 ── */}
                  <section>
                    <FormSectionTitle>基础信息</FormSectionTitle>
                    <div className="space-y-3">
                      {/* 平台 + 名称并排 */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                          <label className="block text-xs font-medium text-muted-foreground mb-1">平台</label>
                          <select
                            value={botForm.platform}
                            onChange={(e) => setBotForm((prev) => ({ ...prev, platform: e.target.value as BotPlatform }))}
                            className={`${FORM_INPUT_CLASS} w-full`}
                          >
                            {BOT_PLATFORM_OPTIONS.map((opt) => (
                              <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-muted-foreground mb-1">机器人名称 *</label>
                          <input
                            type="text"
                            value={botForm.name}
                            onChange={(e) => setBotForm((prev) => ({ ...prev, name: e.target.value }))}
                            className={`${FORM_INPUT_CLASS} w-full`}
                            placeholder="例如：售后客服助手"
                          />
                        </div>
                      </div>
                      {/* 头像 URL */}
                      <div>
                        <label className="block text-xs font-medium text-muted-foreground mb-1">头像 URL</label>
                        <input
                          type="text"
                          value={botForm.avatar}
                          onChange={(e) => setBotForm((prev) => ({ ...prev, avatar: e.target.value }))}
                          className={`${FORM_INPUT_CLASS} w-full`}
                          placeholder="https://example.com/avatar.png"
                        />
                      </div>
                      {/* 欢迎语 */}
                      <div>
                        <label className="block text-xs font-medium text-muted-foreground mb-1">欢迎语</label>
                        <textarea
                          value={botForm.welcome_message}
                          onChange={(e) => setBotForm((prev) => ({ ...prev, welcome_message: e.target.value }))}
                          rows={3}
                          className={`${FORM_INPUT_CLASS} w-full resize-none`}
                          placeholder="您好，我是AI客服助手，请问有什么可以帮您？"
                        />
                      </div>
                    </div>
                  </section>

                  {/* ── 服务策略：工作时间 / 转人工关键词 ── */}
                  <section>
                    <FormSectionTitle>服务策略</FormSectionTitle>
                    <div className="space-y-3">
                      {/* 工作时间 */}
                      <div>
                        <label className="block text-xs font-medium text-muted-foreground mb-1">工作时间</label>
                        <div className="flex items-center gap-2">
                          <input
                            type="time"
                            value={botForm.working_hours_start}
                            onChange={(e) => setBotForm((prev) => ({ ...prev, working_hours_start: e.target.value }))}
                            className={`${FORM_INPUT_CLASS} flex-1`}
                          />
                          <span className="text-sm text-muted-foreground/50">至</span>
                          <input
                            type="time"
                            value={botForm.working_hours_end}
                            onChange={(e) => setBotForm((prev) => ({ ...prev, working_hours_end: e.target.value }))}
                            className={`${FORM_INPUT_CLASS} flex-1`}
                          />
                        </div>
                      </div>
                      {/* 转人工关键词 */}
                      <div>
                        <label className="block text-xs font-medium text-muted-foreground mb-1">转人工关键词</label>
                        <div className="flex items-center gap-2 mb-2">
                          <input
                            type="text"
                            value={botForm.keyword_input}
                            onChange={(e) => setBotForm((prev) => ({ ...prev, keyword_input: e.target.value }))}
                            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addKeyword(); } }}
                            className={`${FORM_INPUT_CLASS} flex-1`}
                            placeholder="输入关键词后回车添加"
                          />
                          <Button size="sm" variant="outline" onClick={addKeyword} type="button">添加</Button>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {botForm.transfer_keywords.map((kw, i) => (
                            <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-xs text-amber-700">
                              {kw}
                              <button
                                type="button"
                                onClick={() => removeKeyword(kw)}
                                className="text-amber-400 hover:text-amber-600"
                              >
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              </button>
                            </span>
                          ))}
                          {botForm.transfer_keywords.length === 0 && (
                            <span className="text-xs text-muted-foreground/50">暂未添加转人工关键词</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </section>

                  {/* ── AI 配置：提示词 / 模型 / 启用状态 ── */}
                  <section>
                    <FormSectionTitle>AI 配置</FormSectionTitle>
                    <div className="space-y-3">
                      {/* 提示词 + 模型配置并排 */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                          <label className="block text-xs font-medium text-muted-foreground mb-1">提示词</label>
                          <select
                            value={botForm.prompt_id}
                            onChange={(e) => setBotForm((prev) => ({ ...prev, prompt_id: e.target.value }))}
                            className={`${FORM_INPUT_CLASS} w-full`}
                          >
                            <option value="">不关联提示词</option>
                            {prompts.map((p) => (
                              <option key={p.id} value={p.id}>{p.name}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-muted-foreground mb-1">模型配置</label>
                          <select
                            value={botForm.model_config_id}
                            onChange={(e) => setBotForm((prev) => ({ ...prev, model_config_id: e.target.value }))}
                            className={`${FORM_INPUT_CLASS} w-full`}
                          >
                            <option value="">不关联模型</option>
                            {modelConfigs.map((m) => (
                              <option key={m.id} value={m.id}>{m.name}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                      {/* 启用状态 */}
                      <div className="flex items-center justify-between py-1">
                        <label className="text-xs font-medium text-muted-foreground">启用状态</label>
                        <button
                          type="button"
                          onClick={() => setBotForm((prev) => ({ ...prev, is_active: !prev.is_active }))}
                          className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                            botForm.is_active ? "bg-emerald-500" : "bg-muted-foreground/20"
                          }`}
                        >
                          <span
                            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                              botForm.is_active ? "translate-x-4" : "translate-x-0"
                            }`}
                          />
                        </button>
                      </div>
                    </div>
                  </section>
                </div>

                {/* 底部操作区（固定，内容滚动时始终可见） */}
                <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-border shrink-0">
                  <Button variant="outline" onClick={() => setBotModalOpen(false)} disabled={botSaving}>
                    取消
                  </Button>
                  <Button onClick={handleSaveBot} disabled={botSaving || !botForm.name.trim()}>
                    {botSaving ? "保存中..." : editingBot ? "保存修改" : "创建机器人"}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Delete confirmation dialog */}
        {deleteTarget && (
          <div className="fixed inset-0 z-50 overflow-y-auto">
            <div className="fixed inset-0 bg-black/30 transition-opacity" onClick={() => setDeleteTarget(null)} />
            <div className="relative min-h-screen flex items-center justify-center p-4">
              <div className="relative bg-white rounded-xl shadow-xl max-w-sm w-full p-6" onClick={(e) => e.stopPropagation()}>
                <h3 className="text-base font-semibold text-foreground mb-2">确认删除</h3>
                <p className="text-sm text-muted-foreground/70 mb-4">
                  确定要删除机器人 <strong className="text-foreground/70">{deleteTarget.name}</strong> 吗？删除后将置为停用状态。
                </p>
                <div className="flex items-center justify-end gap-2">
                  <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleteLoading}>
                    取消
                  </Button>
                  <Button variant="destructive" onClick={handleDeleteBot} disabled={deleteLoading}>
                    {deleteLoading ? "删除中..." : "确认删除"}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
      )}

      {/* Reject confirmation dialog (templates mode) */}
      <Dialog open={!!rejectTarget} onOpenChange={(open) => !open && setRejectTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>驳回话术配置草稿</DialogTitle>
            <DialogDescription>
              确认驳回 <strong>{rejectTarget ? CONFIG_KEY_LABELS[rejectTarget.config_key] || rejectTarget.config_key : ""}</strong> v{rejectTarget?.version} 吗？
              驳回后将归档该草稿。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectTarget(null)} disabled={rejecting}>取消</Button>
            <Button variant="destructive" onClick={handleReject} disabled={rejecting}>
              {rejecting ? "驳回中..." : "确认驳回"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}
