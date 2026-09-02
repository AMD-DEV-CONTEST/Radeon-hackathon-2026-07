"use client";

// ============================================================================
// ModelConfigPanel — 模型工作台：模型配置管理（增删改查 / 启停 / 测试连接）
//
// 数据流（字段全部以 API 真实返回为准，不臆造）：
//   - 列表：GET  /api/qa/model-configs         → { configs: ModelConfig[] }
//   - 新增：POST /api/qa/model-configs          → { config }
//   - 编辑：PATCH /api/qa/model-configs/:id     → { config }
//   - 删除：DELETE /api/qa/model-configs/:id
//   - 启停 / 设默认：PATCH /api/qa/model-configs/:id（is_active / is_default）
//   - 测试连接：复用 GET 列表接口探测连通性
// ============================================================================

import { useState, useEffect, useCallback } from "react";
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Cpu,
  KeyRound,
  Link2,
  MoreHorizontal,
  Pencil,
  Plus,
  Save,
  Server,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

// 模型配置实体：与后端 model_configs 表字段一一对应
interface ModelConfig {
  id: number | string;
  name: string;
  provider: string;
  model_name: string;
  api_key?: string | null;
  api_url?: string | null;
  temperature: number;
  max_tokens: number;
  top_p: number | null;
  is_default: boolean;
  is_active: boolean;
  priority: number;
}

// 新增 / 编辑弹窗的表单字段
interface FormFields {
  name: string;
  provider: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  top_p: number;
  api_key: string;
  api_url: string;
  is_default: boolean;
  priority: number;
}

const EMPTY_FORM: FormFields = {
  name: "",
  provider: "deepseek",
  model_name: "",
  temperature: 0.7,
  max_tokens: 4096,
  top_p: 1,
  api_key: "",
  api_url: "",
  is_default: false,
  priority: 99,
};

// 提供商展示信息（label 用于界面展示，key 与 API provider 字段一致）
const PROVIDERS: Record<string, { label: string }> = {
  dify:     { label: "Dify" },
  deepseek: { label: "DeepSeek" },
  kimi:     { label: "Kimi" },
  moonshot: { label: "Moonshot" },
  openai:   { label: "OpenAI" },
  zhipu:    { label: "智谱" },
  qwen:     { label: "通义千问" },
};

// ── Provider brand SVG icons ──

function ProviderIcon({ provider, className = "h-6 w-6" }: { provider: string; className?: string }) {
  switch (provider) {
    case "openai":
      return (
        <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
          <path d="M22.28 9.82a5.98 5.98 0 0 0-.52-4.89 6.05 6.05 0 0 0-6.5-2.9A5.98 5.98 0 0 0 11.01.92a6.05 6.05 0 0 0-5.76 4.18 5.98 5.98 0 0 0-4 2.9 6.05 6.05 0 0 0 .74 7.1 5.98 5.98 0 0 0 .52 4.89 6.05 6.05 0 0 0 6.5 2.9 5.98 5.98 0 0 0 4.25 1.5 6.05 6.05 0 0 0 5.76-4.18 5.98 5.98 0 0 0 4-2.9 6.05 6.05 0 0 0-.74-7.1zM12.93 4.26l3.72 6.44-3.72 6.44-3.72-6.44 3.72-6.44z" opacity=".9"/>
        </svg>
      );
    case "deepseek":
      return (
        <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
          <path d="M4 12c0-1 .3-2 .8-2.8C5.3 8 6 7.3 7 6.8c.4-1.2 1.2-2.2 2.3-2.8 1-.6 2.2-.9 3.4-.7 1.2.2 2.3.8 3.1 1.7.9.2 1.7.7 2.3 1.4.6.7 1 1.6 1 2.6.8.6 1.4 1.4 1.7 2.4.3 1 .3 2 0 3-.3 1-.9 1.8-1.7 2.4-.2 1-.6 1.9-1.3 2.6-.7.7-1.6 1.2-2.6 1.4-.8.6-1.7.5-2.6.3-.9-.4-1.7-.7-2.3-1.4-1-.2-1.9-.7-2.6-1.4-.7-.7-1.1-1.6-1.3-2.6-.8-.6-1.4-1.4-1.7-2.4-.3-1-.3-2 0-3z"/>
        </svg>
      );
    case "kimi":
      return (
        <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
          <path d="M17 3a9 9 0 1 0 4 16 9 9 0 0 1-4-16z"/>
        </svg>
      );
    case "moonshot":
      return (
        <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
          <path d="M12 2c1.6 0 3.1.5 4.2 1.5C17.3 4.5 18 6 18 8c0 1.5-.5 3-1.5 4.2L14 15v3c0 1.1-.9 2-2 2h-4c-1.1 0-2-.9-2-2v-3l-2.5-2.8C6.5 11 6 9.5 6 8c0-2 .7-3.5 1.8-4.5C8.9 2.5 10.4 2 12 2z M10 20h4v2h-4z"/>
        </svg>
      );
    case "dify":
      return (
        <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
          <path d="M12 2L2 8v8l10 6 10-6V8L12 2zm0 3.2L18.8 9 12 12.8 5.2 9 12 5.2z"/>
        </svg>
      );
    case "zhipu":
      return (
        <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
          <path d="M12 2c0 5.5 4.5 10 10 10-5.5 0-10 4.5-10 10 0-5.5-4.5-10-10-10 5.5 0 10-4.5 10-10z"/>
        </svg>
      );
    case "qwen":
      return (
        <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
          <path d="M3 4h18c.55 0 1 .45 1 1v10c0 .55-.45 1-1 1H9l-4 4v-4H3c-.55 0-1-.45-1-1V5c0-.55.45-1 1-1zm4 6h10v1.5H7zm0 3h7v1.5H7z"/>
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
          <circle cx="12" cy="12" r="7"/>
        </svg>
      );
  }
}

// 探测模型接口连通性：复用 GET 列表接口，返回是否可用及延迟（ms）
async function probeModelApi(): Promise<{ ok: boolean; latency: number }> {
  const start = performance.now();
  try {
    const res = await fetch("/api/qa/model-configs");
    const latency = Math.round(performance.now() - start);
    return { ok: res.ok, latency };
  } catch {
    const latency = Math.round(performance.now() - start);
    return { ok: false, latency };
  }
}

export default function ModelConfigPanel() {
  // 列表与加载状态
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // 新增 / 编辑弹窗状态
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | number | null>(null);
  const [form, setForm] = useState<FormFields>({ ...EMPTY_FORM });

  // 测试连接与全局提示状态
  const [testingId, setTestingId] = useState<string | number | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; latency: number }>>({});
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  // “更多”下拉菜单：当前展开的模型卡片 id
  const [menuId, setMenuId] = useState<string | number | null>(null);

  // 拉取模型配置列表
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/qa/model-configs");
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      setConfigs(json.configs || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  // 点击页面其他区域时收起“更多”菜单
  useEffect(() => {
    if (menuId === null) return;
    const close = () => setMenuId(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [menuId]);

  // ── Modal helpers ──

  const openAdd = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
    setModalOpen(true);
  };

  const openEdit = (c: ModelConfig) => {
    setEditingId(c.id);
    setForm({
      name: c.name,
      provider: c.provider,
      model_name: c.model_name,
      temperature: c.temperature ?? 0.7,
      max_tokens: c.max_tokens ?? 4096,
      top_p: c.top_p ?? 1,
      api_key: c.api_key || "",
      api_url: c.api_url || "",
      is_default: c.is_default ?? false,
      priority: c.priority ?? 99,
    });
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditingId(null);
  };

  // ── CRUD operations ──

  const handleSave = async () => {
    if (!form.name.trim() || !form.model_name.trim()) return;

    setSaving(true);
    try {
      const url = editingId
        ? `/api/qa/model-configs/${editingId}`
        : "/api/qa/model-configs";
      const method = editingId ? "PATCH" : "POST";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name.trim(),
          provider: form.provider,
          model_name: form.model_name.trim(),
          temperature: form.temperature,
          max_tokens: form.max_tokens,
          top_p: form.top_p,
          is_default: form.is_default,
          priority: form.priority,
          api_key: form.api_key || null,
          api_url: form.api_url || null,
        }),
      });

      if (!res.ok) {
        const j = await res.json();
        setToast({ message: `保存失败: ${j.error || res.status}`, type: "error" });
        return;
      }

      closeModal();
      fetchData();
      setToast({ message: editingId ? "模型已更新" : "模型已添加", type: "success" });
    } catch {
      setToast({ message: "保存失败: 网络错误", type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (c: ModelConfig) => {
    if (!confirm(`确定删除模型 "${c.name}" 吗？`)) return;

    try {
      const res = await fetch(`/api/qa/model-configs/${c.id}`, { method: "DELETE" });
      if (!res.ok) {
        const j = await res.json();
        setToast({ message: `删除失败: ${j.error || res.status}`, type: "error" });
        return;
      }
      fetchData();
      setToast({ message: `模型 "${c.name}" 已删除`, type: "success" });
    } catch {
      setToast({ message: "删除失败: 网络错误", type: "error" });
    }
  };

  const handleToggleActive = async (c: ModelConfig) => {
    try {
      const res = await fetch(`/api/qa/model-configs/${c.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !c.is_active }),
      });
      if (!res.ok) {
        const j = await res.json();
        setToast({ message: `操作失败: ${j.error || res.status}`, type: "error" });
        return;
      }
      fetchData();
      setToast({ message: c.is_active ? "模型已停用" : "模型已启用", type: "success" });
    } catch {
      setToast({ message: "网络错误", type: "error" });
    }
  };

  // 设为默认 / 取消默认（后端 PATCH 会自动清除其他默认）
  const handleToggleDefault = async (c: ModelConfig) => {
    try {
      const res = await fetch(`/api/qa/model-configs/${c.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_default: !c.is_default }),
      });
      if (!res.ok) {
        const j = await res.json();
        setToast({ message: `操作失败: ${j.error || res.status}`, type: "error" });
        return;
      }
      fetchData();
      setToast({ message: c.is_default ? "已取消默认模型" : "已设为默认模型", type: "success" });
    } catch {
      setToast({ message: "网络错误", type: "error" });
    }
  };

  const handleTestConnection = async (c: ModelConfig) => {
    setTestingId(c.id);
    // 探测连通性并记录延迟（probeModelApi 为组件外逻辑，保持事件处理函数纯净）
    const result = await probeModelApi();
    setTestResult((prev) => ({ ...prev, [String(c.id)]: result }));
    setTestingId(null);
  };

  const setFormField = <K extends keyof FormFields>(key: K, value: FormFields[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  // ── Render ──

  if (loading) {
    return (
      <div className="min-h-[420px] p-8">
        <div className="mb-8 h-8 w-56 animate-pulse rounded-lg bg-border/70" />
        <div className="grid gap-4 sm:grid-cols-3">
          {[1, 2, 3].map((item) => <div key={item} className="h-24 animate-pulse rounded-xl bg-muted" />)}
        </div>
        <div className="mt-6 h-28 animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="m-8 flex min-h-[320px] items-center justify-center rounded-xl border border-destructive/20 bg-destructive/5 p-8 text-center">
        <div>
          <CircleAlert className="mx-auto mb-3 h-8 w-8 text-destructive" />
          <p className="text-sm font-medium text-destructive">模型配置加载失败</p>
          <p className="mt-1 text-xs text-destructive/80">{error}</p>
          <button onClick={fetchData} className="mt-5 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90">重新加载</button>
        </div>
      </div>
    );
  }

  const activeCount = configs.filter((c) => c.is_active).length;
  const defaultModel = configs.find((c) => c.is_default);
  const providerCount = new Set(configs.map((c) => c.provider)).size;

  return (
    <div className="min-h-full bg-background px-4 py-6 sm:px-8 sm:py-8">
      {toast && (
        <div className={`fixed right-5 top-5 z-[60] flex items-center gap-2 rounded-xl border px-4 py-3 text-sm font-semibold shadow-xl ${toast.type === "success" ? "border-success/30 bg-success/10 text-success" : "border-destructive/30 bg-destructive/10 text-destructive"}`} role="status">
          {toast.type === "success" ? <CheckCircle2 className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />}
          {toast.message}
        </div>
      )}

      <div className="mx-auto max-w-6xl">
        {/* 标题区：面板标题 + 副标题 + 右侧主操作 */}
        <header className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-3 flex items-center gap-2 text-xs font-semibold tracking-[0.18em] text-brand-600">
              <span className="h-2 w-2 rounded-full bg-brand-500 shadow-[0_0_0_4px_rgba(20,184,166,0.12)]" /> 模型服务
            </div>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">模型工作台</h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground/70">统一管理推理模型、连接状态与运行优先级，让每一次回答都可控、可追踪。</p>
          </div>
          <button onClick={openAdd} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90">
            <Plus className="h-4 w-4" /> 添加模型
          </button>
        </header>

        {/* 概览摘要 */}
        <section className="mb-6 grid gap-3 sm:grid-cols-3">
          <SummaryCard icon={<Activity className="h-5 w-5" />} label="运行中的模型" value={`${activeCount} / ${configs.length}`} detail="当前可接受请求" tone="brand" />
          <SummaryCard icon={<Zap className="h-5 w-5" />} label="默认路由" value={defaultModel?.name || "未设置"} detail={defaultModel?.model_name || "添加模型后设置"} tone="warning" />
          <SummaryCard icon={<Server className="h-5 w-5" />} label="接入提供商" value={`${providerCount} 家`} detail="支持多供应商切换" tone="info" />
        </section>

        {/* 列表标题行 */}
        <div className="mb-4 flex items-center justify-between px-1">
          <div>
            <h3 className="text-base font-semibold text-foreground">已配置模型</h3>
            <p className="mt-1 text-xs text-muted-foreground/70">优先级数字越小，路由优先级越高</p>
          </div>
          <span className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground ring-1 ring-border/70">{configs.length} 个配置</span>
        </div>

        {configs.length === 0 ? (
          /* 空状态：带引导动作 */
          <div className="rounded-xl border border-dashed border-muted-foreground/20 bg-card px-6 py-20 text-center shadow-sm">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600"><Cpu className="h-7 w-7" /></div>
            <h3 className="text-base font-semibold text-foreground">还没有模型配置</h3>
            <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-muted-foreground/70">添加你的第一个模型，开始为 QA 工作流提供稳定的推理能力。</p>
            <button onClick={openAdd} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90"><Plus className="h-4 w-4" /> 添加第一个模型</button>
          </div>
        ) : (
          <div className="space-y-3">
            {configs.map((c) => {
              const p = PROVIDERS[c.provider] || { label: c.provider };
              const tr = testResult[String(c.id)];
              const menuOpen = menuId === c.id;
              return (
                /* 模型卡：固定三行紧凑结构 */
                <article key={c.id} className="rounded-xl border border-border bg-card p-4 shadow-sm transition-shadow hover:shadow-md">
                  {/* 行1：模型名称 / 提供商 / 模型 ID + 状态 */}
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                        <ProviderIcon provider={c.provider} className="h-4 w-4" />
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <h4 className="truncate text-sm font-semibold text-foreground">{c.name}</h4>
                          {c.is_default && (
                            <Badge variant="outline" className="border-warning/30 bg-warning/10 px-1.5 text-[10px] text-warning">
                              <Sparkles className="h-2.5 w-2.5" /> 默认
                            </Badge>
                          )}
                        </div>
                        <p className="mt-0.5 truncate text-xs text-muted-foreground/70">
                          <span className="font-medium text-muted-foreground">{p.label}</span>
                          <span className="mx-1 text-muted-foreground/30">/</span>
                          <span className="font-mono">{c.model_name}</span>
                        </p>
                      </div>
                    </div>
                    {c.is_active ? (
                      <Badge variant="outline" className="border-success/30 bg-success/10 text-success">运行中</Badge>
                    ) : (
                      <Badge variant="outline" className="border-border text-muted-foreground">已停用</Badge>
                    )}
                  </div>

                  {/* 行2：温度 · Token · 优先级（含测试连接结果） */}
                  <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground/70">
                    <span>温度 <b className="font-semibold text-foreground/80">{c.temperature.toFixed(1)}</b></span>
                    <span className="text-muted-foreground/30">·</span>
                    <span>Token <b className="font-semibold text-foreground/80">{c.max_tokens.toLocaleString()}</b></span>
                    <span className="text-muted-foreground/30">·</span>
                    <span>优先级 <b className="font-semibold text-foreground/80">P{c.priority}</b></span>
                    {tr && (
                      <span className={`ml-1 font-medium ${tr.ok ? "text-success" : "text-destructive"}`}>
                        {tr.ok ? `连接正常 ${tr.latency}ms` : "连接失败"}
                      </span>
                    )}
                  </div>

                  {/* 行3：操作入口（测试连接 / 编辑 / 更多） */}
                  <div className="mt-3 flex items-center gap-1.5 border-t border-border pt-3">
                    <button type="button" onClick={() => handleTestConnection(c)} disabled={testingId === c.id} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50">
                      <Activity className="h-3.5 w-3.5" />
                      {testingId === c.id ? "测试中" : "测试连接"}
                    </button>
                    <button type="button" onClick={() => openEdit(c)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
                      <Pencil className="h-3.5 w-3.5" /> 编辑
                    </button>
                    <div className="relative">
                      <button type="button" onClick={(e) => { e.stopPropagation(); setMenuId(menuOpen ? null : c.id); }} aria-expanded={menuOpen} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
                        <MoreHorizontal className="h-3.5 w-3.5" /> 更多
                      </button>
                      {menuOpen && (
                        /* “更多”菜单：设默认 / 启停 / 删除 */
                        <div className="absolute left-0 top-full z-20 mt-1.5 w-44 overflow-hidden rounded-xl border border-border bg-card p-1 shadow-lg">
                          <button type="button" onClick={(e) => { e.stopPropagation(); handleToggleDefault(c); setMenuId(null); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-medium text-foreground/80 hover:bg-muted">
                            <Sparkles className="h-3.5 w-3.5 text-muted-foreground/60" /> {c.is_default ? "取消默认" : "设为默认"}
                          </button>
                          <button type="button" onClick={(e) => { e.stopPropagation(); handleToggleActive(c); setMenuId(null); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-medium text-foreground/80 hover:bg-muted">
                            <Zap className="h-3.5 w-3.5 text-muted-foreground/60" /> {c.is_active ? "停用模型" : "启用模型"}
                          </button>
                          <div className="my-1 h-px bg-border" />
                          <button type="button" onClick={(e) => { e.stopPropagation(); handleDelete(c); setMenuId(null); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-medium text-destructive hover:bg-destructive/10">
                            <Trash2 className="h-3.5 w-3.5" /> 删除模型
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>

      {/* 新增 / 编辑弹窗 */}
      {modalOpen && (
        <Modal
          title={editingId ? "编辑模型" : "添加模型"}
          form={form}
          setFormField={setFormField}
          saving={saving}
          onSave={handleSave}
          onClose={closeModal}
        />
      )}
    </div>
  );
}

// ── 概览摘要卡片 ──

function SummaryCard({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: "brand" | "warning" | "info";
}) {
  const tones = {
    brand: "bg-brand-50 text-brand-700",
    warning: "bg-warning/10 text-warning",
    info: "bg-info/10 text-info",
  };
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between">
        <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${tones[tone]}`}>{icon}</span>
        <ChevronRight className="h-4 w-4 text-muted-foreground/20" />
      </div>
      <p className="mt-4 text-xs font-medium text-muted-foreground/70">{label}</p>
      <p className="mt-1 truncate text-lg font-semibold tracking-tight text-foreground">{value}</p>
      <p className="mt-1 truncate text-[11px] text-muted-foreground/50">{detail}</p>
    </div>
  );
}

// ── 新增 / 编辑弹窗 ──

const inputCls =
  "w-full rounded-xl border border-border bg-muted/50 px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/50 transition-colors focus:border-brand-400 focus:bg-card focus:ring-2 focus:ring-brand-500/15 focus:outline-none";

const selectCls =
  "w-full appearance-none rounded-xl border border-border bg-muted/50 px-3 py-2.5 text-sm text-foreground transition-colors focus:border-brand-400 focus:bg-card focus:ring-2 focus:ring-brand-500/15 focus:outline-none cursor-pointer";

function Modal({
  title,
  form,
  setFormField,
  saving,
  onSave,
  onClose,
}: {
  title: string;
  form: FormFields;
  setFormField: <K extends keyof FormFields>(key: K, value: FormFields[K]) => void;
  saving: boolean;
  onSave: () => void;
  onClose: () => void;
}) {
  const providerOptions = Object.entries(PROVIDERS).map(([value, p]) => ({
    value,
    label: p.label,
  }));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-3xl bg-card shadow-2xl ring-1 ring-foreground/5 mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal header */}
        <div className="flex items-center justify-between border-b border-muted px-6 py-4">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
              <SlidersHorizontal className="h-4 w-4" />
            </span>
            <h3 className="text-base font-semibold tracking-tight text-foreground">{title}</h3>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground/50 hover:bg-muted hover:text-muted-foreground"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Modal body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {/* Section 1: 基础信息 */}
          <FormSection title="基础信息">
            <Field label="名称" required hint="便于识别的标签">
              <input
                type="text"
                value={form.name}
                onChange={(e) => setFormField("name", e.target.value)}
                placeholder="例如: 生产环境 DeepSeek"
                className={inputCls}
              />
            </Field>
            <Field label="提供商" required>
              <select
                value={form.provider}
                onChange={(e) => setFormField("provider", e.target.value)}
                className={selectCls}
              >
                {providerOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="模型名称" required hint="API 文档中的模型标识">
              <input
                type="text"
                value={form.model_name}
                onChange={(e) => setFormField("model_name", e.target.value)}
                placeholder="例如: deepseek-chat"
                className={inputCls}
              />
            </Field>
          </FormSection>

          {/* Section 2: 参数调优 */}
          <FormSection title="参数调优">
            <Field label="Temperature" hint={form.temperature.toFixed(1)}>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={form.temperature}
                  onChange={(e) => setFormField("temperature", parseFloat(e.target.value))}
                  className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-border accent-brand-500"
                />
                <span className="w-12 shrink-0 text-right text-xs font-semibold text-muted-foreground">
                  {form.temperature.toFixed(1)}
                </span>
              </div>
              <div className="flex justify-between text-[10px] text-muted-foreground/50">
                <span>保守 0.0</span>
                <span>创意 2.0</span>
              </div>
            </Field>
            <Field label="Max Tokens" hint="最大输出长度">
              <input
                type="number"
                min={1}
                max={131072}
                value={form.max_tokens}
                onChange={(e) => setFormField("max_tokens", parseInt(e.target.value) || 4096)}
                className={inputCls}
              />
            </Field>
            <Field label="Top P" hint={form.top_p.toFixed(2)}>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={form.top_p}
                  onChange={(e) => setFormField("top_p", parseFloat(e.target.value))}
                  className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-border accent-brand-500"
                />
                <span className="w-12 shrink-0 text-right text-xs font-semibold text-muted-foreground">
                  {form.top_p.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between text-[10px] text-muted-foreground/50">
                <span>0</span>
                <span>0.5</span>
                <span>1</span>
              </div>
            </Field>
          </FormSection>

          {/* Section 3: 连接配置 */}
          <FormSection title="连接配置">
            <Field label="API Key" hint="选填">
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/50" />
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setFormField("api_key", e.target.value)}
                  placeholder="自定义 API Key"
                  className={`${inputCls} pl-9`}
                />
              </div>
            </Field>
            <Field label="API URL" hint="选填，自定义端点">
              <div className="relative">
                <Link2 className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/50" />
                <input
                  type="text"
                  value={form.api_url}
                  onChange={(e) => setFormField("api_url", e.target.value)}
                  placeholder="https://api.deepseek.com/v1"
                  className={`${inputCls} pl-9`}
                />
              </div>
            </Field>
          </FormSection>

          {/* Section 4: 路由设置 */}
          <FormSection title="路由设置">
            <div className="flex items-center justify-between rounded-xl border border-border bg-muted/50 px-3.5 py-2.5">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-warning" />
                <div>
                  <p className="text-xs font-semibold text-foreground/70">设为默认模型</p>
                  <p className="text-[11px] text-muted-foreground/50">未指定路由时使用此模型</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setFormField("is_default", !form.is_default)}
                className={`relative h-6 w-10 shrink-0 rounded-full transition-colors ${form.is_default ? "bg-brand-600" : "bg-muted-foreground/20"}`}
                aria-label="设为默认模型"
              >
                <span
                  className={`absolute top-1 h-4 w-4 rounded-full bg-card shadow-sm transition-transform ${form.is_default ? "translate-x-5" : "translate-x-1"}`}
                />
              </button>
            </div>
            <Field label="优先级" hint="数字越小越优先">
              <input
                type="number"
                min={0}
                value={form.priority}
                onChange={(e) => setFormField("priority", parseInt(e.target.value) || 99)}
                className={`${inputCls} w-24`}
              />
            </Field>
          </FormSection>
        </div>

        {/* Modal footer */}
        <div className="flex items-center justify-end gap-2.5 border-t border-muted bg-muted/50 px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-xl border border-border bg-card px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/50"
          >
            取消
          </button>
          <button
            onClick={onSave}
            disabled={saving || !form.name.trim() || !form.model_name.trim()}
            className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Save className="h-4 w-4" />
            {saving ? "保存中" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 弹窗分组标题 ──

function FormSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-5 last:mb-0">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/50">{title}</p>
      <div className="space-y-3.5">{children}</div>
    </div>
  );
}

// ── 表单项外壳 ──

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-xs font-semibold text-foreground/70">
          {label}
          {required && <span className="ml-0.5 text-destructive">*</span>}
        </label>
        {hint && (
          <span className="text-[11px] font-medium text-muted-foreground/50">{hint}</span>
        )}
      </div>
      {children}
    </div>
  );
}
