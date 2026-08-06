"use client";

import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import Panel from "@/components/dashboard/Panel";
import { Plus, X, Pencil, Archive, Sparkles, ChevronDown, ChevronRight, Loader2, FileText, Search, MoreHorizontal } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PromptVariable {
  key: string;
  value: string;
}

interface PromptVersion {
  id?: string;
  prompt_id?: string;
  version: number;
  system_prompt: string;
  variables: PromptVariable[] | null;
  temperature: number;
  max_tokens: number;
  created_at?: string;
}

// 状态枚举以 API 为准：draft / published / archived；停用由 is_active=false 表达
interface Prompt {
  id: string;
  name: string;
  scene: string;
  system_prompt: string;
  variables: PromptVariable[] | null;
  temperature: number;
  max_tokens: number;
  version: number;
  status: "draft" | "published" | "archived";
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SCENE_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "pre_sale", label: "售前" },
  { value: "after_sales", label: "售后" },
  { value: "logistics", label: "物流" },
  { value: "complaint", label: "投诉" },
  { value: "general", label: "通用" },
];

const SCENE_LABELS: Record<string, string> = {
  pre_sale: "售前",
  after_sales: "售后",
  logistics: "物流",
  complaint: "投诉",
  general: "通用",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
};

const STATUS_OPTIONS = [
  { value: "all", label: "全部状态" },
  { value: "draft", label: "草稿" },
  { value: "published", label: "已发布" },
  { value: "archived", label: "已归档" },
];

const SCENE_EDIT_OPTIONS = SCENE_OPTIONS.filter((s) => s.value !== "all");

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PromptManagerPanel() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sceneFilter, setSceneFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Edit / Create modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState<Prompt | null>(null);
  const [form, setForm] = useState({
    name: "",
    scene: "general",
    system_prompt: "",
    variables: [] as PromptVariable[],
    temperature: 0.7,
    max_tokens: 2048,
  });
  const [saving, setSaving] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // AI generation state
  const [activeTab, setActiveTab] = useState<"manual" | "ai">("manual");
  const [aiDescription, setAiDescription] = useState("");
  const [aiScene, setAiScene] = useState("general");
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  // Version history state
  const [versionModalOpen, setVersionModalOpen] = useState(false);
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<PromptVersion | null>(null);

  // Archive confirmation
  const [archiveTarget, setArchiveTarget] = useState<Prompt | null>(null);

  // "更多"菜单展开状态（记录当前展开的卡片 id）
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  // Toast notification
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  // -----------------------------------------------------------------------
  // Data fetching
  // -----------------------------------------------------------------------

  const fetchPrompts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (sceneFilter !== "all") params.set("scene", sceneFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      params.set("limit", "100");

      const res = await fetch(`/api/qa/prompts?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setPrompts(data.prompts || []);
      } else {
        const err = await res.json().catch(() => ({ error: "请求失败" }));
        setError(err.error || "加载 Prompt 列表失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setLoading(false);
  }, [sceneFilter, statusFilter]);

  useEffect(() => {
    fetchPrompts();
  }, [fetchPrompts]);

  // -----------------------------------------------------------------------
  // Form helpers
  // -----------------------------------------------------------------------

  function openCreateModal() {
    setEditingPrompt(null);
    setForm({
      name: "",
      scene: "general",
      system_prompt: "",
      variables: [],
      temperature: 0.7,
      max_tokens: 2048,
    });
    setShowAdvanced(false);
    setActiveTab("manual");
    setAiDescription("");
    setAiScene("general");
    setAiGenerating(false);
    setAiError(null);
    setModalOpen(true);
  }

  async function handleAiGenerate() {
    if (!aiDescription.trim()) return;
    setAiGenerating(true);
    setAiError(null);
    try {
      const res = await fetch("/api/qa/prompts/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description: aiDescription.trim(),
          scene: aiScene,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "生成失败" }));
        throw new Error(err.error || "生成失败");
      }
      const data = await res.json();
      // Auto-fill form fields
      setForm({
        name: data.suggested_name || "",
        scene: aiScene,
        system_prompt: data.system_prompt || "",
        variables: (data.suggested_variables || []).map((v: string) => ({
          key: v,
          value: "",
        })),
        temperature: 0.7,
        max_tokens: 2048,
      });
      // Switch to manual tab so user can review and edit
      setActiveTab("manual");
      setAiGenerating(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "AI 生成失败";
      setAiError(msg);
      setAiGenerating(false);
    }
  }

  function openEditModal(prompt: Prompt) {
    setEditingPrompt(prompt);
    setForm({
      name: prompt.name,
      scene: prompt.scene,
      system_prompt: prompt.system_prompt,
      variables: prompt.variables ? [...prompt.variables] : [],
      temperature: prompt.temperature,
      max_tokens: prompt.max_tokens,
    });
    setShowAdvanced(false);
    setModalOpen(true);
  }

  function addVariable() {
    setForm((prev) => ({
      ...prev,
      variables: [...prev.variables, { key: "", value: "" }],
    }));
  }

  function removeVariable(index: number) {
    setForm((prev) => ({
      ...prev,
      variables: prev.variables.filter((_, i) => i !== index),
    }));
  }

  function updateVariable(index: number, field: "key" | "value", val: string) {
    setForm((prev) => {
      const updated = [...prev.variables];
      updated[index] = { ...updated[index], [field]: val };
      return { ...prev, variables: updated };
    });
  }

  // -----------------------------------------------------------------------
  // Save / Archive
  // -----------------------------------------------------------------------

  async function handleSave() {
    if (!form.name.trim() || !form.scene) return;
    setSaving(true);

    try {
      const payload = {
        name: form.name.trim(),
        scene: form.scene,
        system_prompt: form.system_prompt,
        variables: form.variables.filter((v) => v.key.trim()),
        temperature: form.temperature,
        max_tokens: form.max_tokens,
      };

      if (editingPrompt) {
        const res = await fetch(`/api/qa/prompts/${editingPrompt.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ error: "更新失败" }));
          throw new Error(err.error || "更新失败");
        }
      } else {
        const res = await fetch("/api/qa/prompts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ error: "创建失败" }));
          throw new Error(err.error || "创建失败");
        }
      }

      setToast({ message: editingPrompt ? "Prompt 已更新" : "Prompt 已创建", type: "success" });
      setModalOpen(false);
      fetchPrompts();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "操作失败";
      setToast({ message: msg, type: "error" });
    }
    setSaving(false);
  }

  async function handleArchive(prompt: Prompt) {
    try {
      const res = await fetch(`/api/qa/prompts/${prompt.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("归档失败");
      setToast({ message: "Prompt 已归档", type: "success" });
      setArchiveTarget(null);
      fetchPrompts();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "操作失败";
      setToast({ message: msg, type: "error" });
    }
  }

  async function handleActivate(prompt: Prompt) {
    const sceneName = SCENE_LABELS[prompt.scene] || prompt.scene;
    try {
      // Also set status to published when activating
      const res = await fetch(`/api/qa/prompts/${prompt.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: true, status: prompt.status === "draft" ? "published" : undefined }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "激活失败" }));
        throw new Error(err.error || "激活失败");
      }
      setToast({ message: `已切换为 ${sceneName} 场景的默认提示词`, type: "success" });
      fetchPrompts();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "操作失败";
      setToast({ message: msg, type: "error" });
    }
  }

  async function handleDeactivate(prompt: Prompt) {
    try {
      const res = await fetch(`/api/qa/prompts/${prompt.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: false }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "停用失败" }));
        throw new Error(err.error || "停用失败");
      }
      setToast({ message: "提示词已停用", type: "success" });
      fetchPrompts();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "操作失败";
      setToast({ message: msg, type: "error" });
    }
  }

  // -----------------------------------------------------------------------
  // Version history
  // -----------------------------------------------------------------------

  async function openVersionHistory(promptId: string) {
    setVersionModalOpen(true);
    setVersionsLoading(true);
    setSelectedVersion(null);
    try {
      const res = await fetch(`/api/qa/prompts/${promptId}/versions`);
      if (res.ok) {
        const data = await res.json();
        const list: PromptVersion[] = (data.versions || []).map((v: PromptVersion) => ({
          ...v,
          variables: typeof v.variables === "string" ? JSON.parse(v.variables) : v.variables,
        }));
        setVersions(list);
        if (list.length > 0) {
          setSelectedVersion(list[0]);
        }
      }
    } catch {
      // skip
    }
    setVersionsLoading(false);
  }

  // -----------------------------------------------------------------------
  // Shared: advanced settings expandable section for the form
  // -----------------------------------------------------------------------

  function renderAdvancedSection() {
    return (
      <div className="border border-border rounded-lg">
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-medium text-muted-foreground hover:bg-muted/50 rounded-lg transition-colors"
        >
          <span>高级设置</span>
          {showAdvanced ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        {showAdvanced && (
          <div className="px-3 pb-3 space-y-4 border-t border-muted pt-3">
            {/* Variables editor */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-medium text-muted-foreground">变量</label>
                <button
                  type="button"
                  onClick={addVariable}
                  className="text-xs text-primary hover:text-primary/80 font-medium"
                >
                  + 添加变量
                </button>
              </div>
              {form.variables.length === 0 ? (
                <p className="text-xs text-muted-foreground/50 italic">暂未定义变量</p>
              ) : (
                <div className="space-y-2">
                  {form.variables.map((v, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Input
                        value={v.key}
                        onChange={(e) => updateVariable(i, "key", e.target.value)}
                        placeholder="变量名"
                        className="flex-1 text-xs"
                      />
                      <Input
                        value={v.value}
                        onChange={(e) => updateVariable(i, "value", e.target.value)}
                        placeholder="默认值"
                        className="flex-1 text-xs"
                      />
                      <button
                        type="button"
                        onClick={() => removeVariable(i)}
                        className="text-destructive hover:text-destructive/80 shrink-0"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Temperature renamed: 回复随机性 */}
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                回复随机性: {form.temperature.toFixed(1)}
              </label>
              <input
                type="range"
                min="0.1"
                max="1.5"
                step="0.1"
                value={form.temperature}
                onChange={(e) =>
                  setForm((p) => ({ ...p, temperature: parseFloat(e.target.value) }))
                }
                className="w-full h-2 bg-border rounded-lg appearance-none cursor-pointer accent-primary"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground/50 mt-0.5">
                <span>保守</span>
                <span>创意</span>
              </div>
            </div>

            {/* Max Tokens renamed: 回复长度限制 */}
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                回复长度限制
              </label>
              <Input
                type="number"
                value={form.max_tokens}
                onChange={(e) =>
                  setForm((p) => ({
                    ...p,
                    max_tokens: Math.max(1, parseInt(e.target.value) || 2048),
                  }))
                }
                min={1}
                max={128000}
                className="max-w-[200px]"
              />
            </div>
          </div>
        )}
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Derived
  // -----------------------------------------------------------------------

  // 本地搜索：匹配标题 / 场景标签 / 状态标签（API 返回字段均为真实字段）
  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredPrompts = prompts.filter((p) => {
    if (!normalizedQuery) return true;
    const haystack = [
      p.name,
      SCENE_LABELS[p.scene] || p.scene,
      p.scene,
      STATUS_LABELS[p.status] || p.status,
      p.is_active ? "使用中" : "已停用",
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(normalizedQuery);
  });

  const isEmpty = !loading && !error && filteredPrompts.length === 0;
  const hasActiveFilter =
    statusFilter !== "all" || sceneFilter !== "all" || searchQuery.trim() !== "";
  const isFilteredEmpty = isEmpty && hasActiveFilter;

  // 日期格式化：输出如 2026/07/30
  function formatDate(iso?: string) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("zh-CN");
  }

  // 状态徽章：以 API 真实状态枚举为基准；published 但未启用时呈现"已停用"
  function renderStatusBadge(prompt: Prompt) {
    if (prompt.status === "archived") {
      // 已归档：灰蓝
      return <Badge className="bg-muted text-muted-foreground">已归档</Badge>;
    }
    if (prompt.status === "draft") {
      // 草稿：琥珀黄
      return <Badge className="bg-warning text-warning-foreground">草稿</Badge>;
    }
    // published
    if (prompt.is_active) {
      // 已发布：青绿
      return (
        <Badge className="bg-success text-success-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-success-foreground animate-pulse" />
          已发布
        </Badge>
      );
    }
    // 已停用：灰
    return <Badge className="bg-muted/50 text-muted-foreground">已停用</Badge>;
  }

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <Panel
      title="Prompt 管理"
      subtitle="管理和版本化 AI 提示词模板"
      loading={loading}
      error={error}
      onRetry={fetchPrompts}
      empty={isEmpty}
      emptyIcon={<FileText className="h-10 w-10 text-muted-foreground/20" />}
      emptyTitle={isFilteredEmpty ? "没有匹配的 Prompt" : "暂无 Prompt 模板"}
      emptyDescription={isFilteredEmpty ? "当前筛选条件下没有结果，请调整筛选条件" : "点击右上角「新建 Prompt」创建第一个提示词模板"}
      emptyAction={
        isFilteredEmpty
          ? {
              label: "清除筛选",
              onClick: () => {
                setStatusFilter("all");
                setSceneFilter("all");
                setSearchQuery("");
              },
            }
          : undefined
      }
      actions={
        <Button size="sm" onClick={openCreateModal}>
          <Plus className="h-4 w-4 mr-1" />
          新建 Prompt
        </Button>
      }
    >
      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium animate-toast-in border ${
            toast.type === "success"
              ? "bg-success/10 text-success border-success/30"
              : "bg-destructive/10 text-destructive border-destructive/30"
          }`}
        >
          {toast.message}
        </div>
      )}
      <div className="space-y-4">
        {/* Filter bar */}
        <div className="space-y-3">
          {/* 搜索框 + 计数 */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60 pointer-events-none" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索标题 / 场景 / 状态"
                className="pl-8"
              />
            </div>
            <span className="text-xs text-muted-foreground/70 ml-auto">
              {filteredPrompts.length} 个 Prompt
            </span>
          </div>

          {/* 场景 / 状态筛选 */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground/70 shrink-0">场景：</span>
              <div className="flex gap-1">
                {SCENE_OPTIONS.map((opt) => (
                  <Button
                    key={opt.value}
                    type="button"
                    size="sm"
                    variant={sceneFilter === opt.value ? "default" : "outline"}
                    onClick={() => setSceneFilter(opt.value)}
                  >
                    {opt.label}
                  </Button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground/70 shrink-0">状态：</span>
              <div className="flex gap-1">
                {STATUS_OPTIONS.map((opt) => (
                  <Button
                    key={opt.value}
                    type="button"
                    size="sm"
                    variant={statusFilter === opt.value ? "default" : "outline"}
                    onClick={() => setStatusFilter(opt.value)}
                  >
                    {opt.label}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* 配置资产卡网格 */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filteredPrompts.map((prompt) => (
            <div
              key={prompt.id}
              className={`relative bg-card border rounded-lg p-3.5 cursor-pointer transition-shadow hover:shadow-md ${
                prompt.is_active
                  ? "border-success/40 border-l-2 border-l-success"
                  : "border-border"
              }`}
              onClick={() => openEditModal(prompt)}
            >
              {/* 第 1 行：标题 + 版本 · 状态 */}
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold text-foreground truncate min-w-0">
                  {prompt.name}
                </h3>
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="text-[11px] font-medium text-muted-foreground">
                    v{prompt.version}
                  </span>
                  {renderStatusBadge(prompt)}
                </div>
              </div>

              {/* 第 2 / 3 行：场景 · 最后更新（固定信息层级） */}
              <div className="mt-2 space-y-1">
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="text-muted-foreground/70">场景：</span>
                  <span className="text-foreground/85 font-medium">
                    {SCENE_LABELS[prompt.scene] || prompt.scene}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="text-muted-foreground/70">最后更新：</span>
                  <span className="text-foreground/85">{formatDate(prompt.updated_at)}</span>
                </div>
              </div>

              {/* 第 4 行：提示词摘要 */}
              <p className="mt-2 text-xs text-muted-foreground leading-relaxed line-clamp-2 min-h-[2.25rem]">
                {prompt.system_prompt ? prompt.system_prompt : "（无系统提示词）"}
              </p>

              {/* 底部操作区：查看 / 版本 / 更多，右下角保持克制 */}
              <div className="mt-2.5 pt-2 border-t border-border flex items-center justify-end gap-1">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    openEditModal(prompt);
                  }}
                  className="px-2 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-primary hover:bg-muted/50 transition-colors"
                >
                  查看
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    openVersionHistory(prompt.id);
                  }}
                  className="px-2 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-primary hover:bg-muted/50 transition-colors"
                >
                  版本
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpenMenuId(openMenuId === prompt.id ? null : prompt.id);
                  }}
                  className="px-2 py-1 rounded-md text-xs font-medium text-muted-foreground hover:text-primary hover:bg-muted/50 transition-colors flex items-center gap-1"
                >
                  <MoreHorizontal className="h-3.5 w-3.5" />
                  更多
                </button>

                {/* "更多"下拉菜单 */}
                {openMenuId === prompt.id && (
                  <>
                    {/* 点击外部关闭的透明遮罩 */}
                    <div className="fixed inset-0 z-40" onClick={() => setOpenMenuId(null)} />
                    <div className="absolute right-3 bottom-11 z-50 w-36 bg-popover text-popover-foreground border border-border rounded-lg shadow-lg p-1">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenMenuId(null);
                          openEditModal(prompt);
                        }}
                        className="w-full flex items-center gap-2 px-2 py-1.5 text-xs rounded-md hover:bg-muted"
                      >
                        <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                        编辑
                      </button>
                      {prompt.status !== "archived" && (
                        <>
                          {prompt.is_active ? (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setOpenMenuId(null);
                                handleDeactivate(prompt);
                              }}
                              className="w-full flex items-center gap-2 px-2 py-1.5 text-xs rounded-md hover:bg-muted text-warning"
                            >
                              停用
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setOpenMenuId(null);
                                handleActivate(prompt);
                              }}
                              className="w-full flex items-center gap-2 px-2 py-1.5 text-xs rounded-md hover:bg-muted text-success"
                            >
                              启用
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpenMenuId(null);
                              setArchiveTarget(prompt);
                            }}
                            className="w-full flex items-center gap-2 px-2 py-1.5 text-xs rounded-md hover:bg-muted text-muted-foreground"
                          >
                            <Archive className="h-3.5 w-3.5" />
                            归档
                          </button>
                        </>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ================================================================= */}
      {/* Edit / Create Modal */}
      {/* ================================================================= */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingPrompt ? "编辑 Prompt" : "新建 Prompt"}</DialogTitle>
            <DialogDescription>
              {editingPrompt
                ? `编辑 "${editingPrompt.name}" v${editingPrompt.version}`
                : "创建一个新的提示词模板"}
            </DialogDescription>
          </DialogHeader>

          {/* =============================================================== */}
          {/* Edit mode: simplified form */}
          {/* =============================================================== */}
          {editingPrompt ? (
            <div className="space-y-4 py-2">
              {/* Name */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">
                  名称 <span className="text-destructive">*</span>
                </label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                  placeholder="例如：售前客服标准话术"
                />
              </div>

              {/* Scene */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">
                  场景 <span className="text-destructive">*</span>
                </label>
                <div className="flex gap-1.5 flex-wrap">
                  {SCENE_EDIT_OPTIONS.map((opt) => (
                    <Button
                      key={opt.value}
                      type="button"
                      size="sm"
                      variant={form.scene === opt.value ? "default" : "outline"}
                      onClick={() => setForm((p) => ({ ...p, scene: opt.value }))}
                    >
                      {opt.label}
                    </Button>
                  ))}
                </div>
              </div>

              {/* System Prompt */}
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">
                  系统提示词
                </label>
                <Textarea
                  value={form.system_prompt}
                  onChange={(e) => setForm((p) => ({ ...p, system_prompt: e.target.value }))}
                  placeholder="输入系统提示词... 可以使用 {变量名} 语法插入变量"
                  className="min-h-[200px] font-mono text-sm"
                />
                <p className="text-[10px] text-muted-foreground/50 mt-1">
                  使用 {`{变量名}`} 语法插入动态变量
                </p>
              </div>

              {/* Advanced settings expandable */}
              {renderAdvancedSection()}
            </div>
          ) : (
            /* =============================================================== */
            /* Create mode: tabbed UI (manual / AI generate) */
            /* =============================================================== */
            <>
              {/* Tab switcher */}
              <div className="flex border-b border-border mb-4">
                <button
                  type="button"
                  onClick={() => { setActiveTab("manual"); setAiError(null); }}
                  className={`px-4 py-2.5 text-sm font-medium transition-all border-b-2 -mb-[1px] ${
                    activeTab === "manual"
                      ? "border-primary text-foreground"
                      : "border-transparent text-muted-foreground/50 hover:text-muted-foreground"
                  }`}
                >
                  手动输入
                </button>
                <button
                  type="button"
                  onClick={() => { setActiveTab("ai"); setAiError(null); }}
                  className={`px-4 py-2.5 text-sm font-medium transition-all border-b-2 -mb-[1px] flex items-center gap-1.5 ${
                    activeTab === "ai"
                      ? "border-primary text-foreground"
                      : "border-transparent text-muted-foreground/50 hover:text-muted-foreground"
                  }`}
                >
                  <Sparkles className="h-4 w-4" />
                  AI 生成
                </button>
              </div>

              {activeTab === "manual" ? (
                /* --- Manual entry form (simplified) --- */
                <div className="space-y-4 py-2">
                  {/* Name */}
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1 block">
                      名称 <span className="text-destructive">*</span>
                    </label>
                    <Input
                      value={form.name}
                      onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                      placeholder="例如：售前客服标准话术"
                    />
                  </div>

                  {/* Scene */}
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1 block">
                      场景 <span className="text-destructive">*</span>
                    </label>
                    <div className="flex gap-1.5 flex-wrap">
                      {SCENE_EDIT_OPTIONS.map((opt) => (
                        <Button
                          key={opt.value}
                          type="button"
                          size="sm"
                          variant={form.scene === opt.value ? "default" : "outline"}
                          onClick={() => setForm((p) => ({ ...p, scene: opt.value }))}
                        >
                          {opt.label}
                        </Button>
                      ))}
                    </div>
                  </div>

                  {/* System Prompt */}
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1 block">
                      系统提示词
                    </label>
                    <Textarea
                      value={form.system_prompt}
                      onChange={(e) => setForm((p) => ({ ...p, system_prompt: e.target.value }))}
                      placeholder="输入系统提示词... 可以使用 {变量名} 语法插入变量"
                      className="min-h-[200px] font-mono text-sm"
                    />
                    <p className="text-[10px] text-muted-foreground/50 mt-1">
                      使用 {`{变量名}`} 语法插入动态变量
                    </p>
                  </div>

                  {/* Advanced settings expandable */}
                  {renderAdvancedSection()}
                </div>
              ) : (
                /* --- AI Generation UI (unchanged) --- */
                <div className="space-y-4 py-2">
                  {/* Description textarea */}
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1 block">
                      描述你需要的客服场景，AI 将自动生成提示词
                    </label>
                    <Textarea
                      value={aiDescription}
                      onChange={(e) => {
                        setAiDescription(e.target.value);
                        setAiError(null);
                      }}
                      placeholder="例如：我是卖3C产品的，需要售前咨询话术，语气专业但不生硬"
                      className="min-h-[120px] text-sm"
                      disabled={aiGenerating}
                    />
                  </div>

                  {/* Scene selector for AI */}
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1 block">
                      选择场景
                    </label>
                    <div className="flex gap-1.5 flex-wrap">
                      {SCENE_EDIT_OPTIONS.map((opt) => (
                        <Button
                          key={opt.value}
                          type="button"
                          size="sm"
                          variant={aiScene === opt.value ? "default" : "outline"}
                          onClick={() => setAiScene(opt.value)}
                          disabled={aiGenerating}
                        >
                          {opt.label}
                        </Button>
                      ))}
                    </div>
                  </div>

                  {/* Error display */}
                  {aiError && (
                    <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-3 text-xs text-destructive">
                      {aiError}
                    </div>
                  )}

                  {/* Preview of generated result */}
                  {form.system_prompt && !aiGenerating && (
                    <div className="bg-success/10 border border-success/30 rounded-lg p-4">
                      <p className="text-xs font-medium text-success mb-2 flex items-center gap-1.5">
                        <Sparkles className="h-3.5 w-3.5" />
                        AI 已生成内容，切换到「手动输入」标签页查看和编辑
                      </p>
                      <p className="text-xs text-success line-clamp-3">
                        {form.system_prompt.slice(0, 150)}
                        {form.system_prompt.length > 150 ? "..." : ""}
                      </p>
                    </div>
                  )}

                  {/* Generate button */}
                  <div className="flex items-center gap-3">
                    <Button
                      onClick={handleAiGenerate}
                      disabled={aiGenerating || !aiDescription.trim()}
                      className="gap-2"
                    >
                      {aiGenerating ? (
                        <>
                          <Loader2 className="animate-spin h-4 w-4" />
                          AI 正在生成...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-4 w-4" />
                          生成
                        </>
                      )}
                    </Button>
                    {aiGenerating && (
                      <span className="text-xs text-muted-foreground/50 animate-pulse">
                        正在调用 AI 模型，请稍候...
                      </span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setModalOpen(false)} disabled={saving}>
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving || !form.name.trim() || !form.scene}>
              {saving ? "保存中..." : editingPrompt ? "保存修改" : "创建 Prompt"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ================================================================= */}
      {/* Version History Modal */}
      {/* ================================================================= */}
      <Dialog open={versionModalOpen} onOpenChange={setVersionModalOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>版本历史</DialogTitle>
            <DialogDescription>
              查看该 Prompt 的历史版本
            </DialogDescription>
          </DialogHeader>

          {versionsLoading ? (
            <div className="py-8 text-center text-sm text-muted-foreground/50">加载中...</div>
          ) : versions.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground/50">暂无版本历史</div>
          ) : (
            <div className="space-y-3 py-2">
              {versions.map((v) => (
                <button
                  key={v.version}
                  type="button"
                  onClick={() => setSelectedVersion(v)}
                  className={`w-full text-left p-3 rounded-lg border transition-all ${
                    selectedVersion?.version === v.version
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-muted-foreground/20"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-semibold text-foreground/70">
                      v{v.version}
                    </span>
                    <span className="text-[10px] text-muted-foreground/50">
                      {v.created_at
                        ? new Date(v.created_at).toLocaleString("zh-CN")
                        : ""}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground/70 line-clamp-2">
                    {v.system_prompt.slice(0, 120)}
                    {v.system_prompt.length > 120 ? "..." : ""}
                  </p>
                </button>
              ))}
            </div>
          )}

          {/* Selected version detail */}
          {selectedVersion && (
            <div className="border-t border-border pt-3 mt-2">
              <h4 className="text-xs font-semibold text-muted-foreground mb-2">
                版本 v{selectedVersion.version} 完整内容
              </h4>
              <div className="bg-muted/50 border border-border rounded-lg p-3 max-h-[300px] overflow-y-auto">
                <pre className="text-xs text-foreground/70 whitespace-pre-wrap font-mono">
                  {selectedVersion.system_prompt || "(空)"}
                </pre>
              </div>
              <div className="flex gap-4 mt-2 text-[10px] text-muted-foreground/50">
                <span>回复随机性: {selectedVersion.temperature}</span>
                <span>回复长度限制: {selectedVersion.max_tokens}</span>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setVersionModalOpen(false)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ================================================================= */}
      {/* Archive Confirmation Dialog */}
      {/* ================================================================= */}
      <Dialog open={!!archiveTarget} onOpenChange={(open) => !open && setArchiveTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>归档 Prompt</DialogTitle>
            <DialogDescription>
              确认归档 <strong>{archiveTarget?.name}</strong> 吗？归档后该 Prompt 将不再可用，但不会删除数据。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => archiveTarget && handleArchive(archiveTarget)}
            >
              确认归档
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}
