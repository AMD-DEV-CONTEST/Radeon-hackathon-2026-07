"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import Panel from "@/components/dashboard/Panel";
import { Pencil, Archive, CheckCircle, XCircle, X, History, Plus, Upload, FileText, Sparkles, Loader2, ChevronDown, ChevronRight } from "lucide-react";
import type { KnowledgeEntry, KnowledgeCategory, KnowledgeTone } from "@/lib/types/bot";

const CATEGORY_LABELS: Record<KnowledgeCategory, string> = {
  product: "产品", faq: "FAQ", after_sales_policy: "售后政策",
  campaign: "活动", greeting: "欢迎语",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-amber-100 text-amber-700",
  published: "bg-emerald-100 text-emerald-700",
  archived: "bg-muted text-muted-foreground/50",
};

const STATUS_OPTIONS = [
  { value: "published", label: "已发布" },
  { value: "draft", label: "待审核" },
  { value: "archived", label: "已归档" },
] as const;

const SOURCE_LABELS: Record<string, string> = {
  knowledge_gap: "缺口检测",
  manual: "手动创建",
  campaign: "活动导入",
  batch_import: "批量导入",
};

const TONE_LABELS: Record<Exclude<KnowledgeTone, "">, string> = {
  professional: "专业严谨",
  friendly: "亲切活泼",
  concise: "简洁高效",
};

const TONE_COLORS: Record<Exclude<KnowledgeTone, "">, string> = {
  professional: "bg-blue-100 text-blue-700 border-blue-200",
  friendly: "bg-pink-100 text-pink-700 border-pink-200",
  concise: "bg-teal-100 text-teal-700 border-teal-200",
};

const TAG_COLORS = [
  "bg-indigo-100 text-indigo-700",
  "bg-violet-100 text-violet-700",
  "bg-cyan-100 text-cyan-700",
  "bg-orange-100 text-orange-700",
  "bg-rose-100 text-rose-700",
  "bg-lime-100 text-lime-700",
  "bg-amber-100 text-amber-700",
  "bg-fuchsia-100 text-fuchsia-700",
];

export default function KnowledgeBasePanel() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<KnowledgeCategory | "all">("all");
  const [statusFilter, setStatusFilter] = useState("published");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<KnowledgeEntry | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({
    title: "", content: "", category: "faq" as KnowledgeCategory,
    priority: 5, tone: "" as KnowledgeTone, tags: [] as string[], status: "published" as string,
  });
  const [sortBy, setSortBy] = useState("newest");
  const [tagInput, setTagInput] = useState("");
  const [batchActionLoading, setBatchActionLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [ragQuery, setRagQuery] = useState("");
  const [ragResult, setRagResult] = useState<KnowledgeEntry[]>([]);
  const [ragLoading, setRagLoading] = useState(false);
  const [gaps, setGaps] = useState<Record<string, unknown> | null>(null);
  const [gapsLoading, setGapsLoading] = useState(false);
  const [platformMap, setPlatformMap] = useState<Record<string, string>>({});
  const [archiveTarget, setArchiveTarget] = useState<KnowledgeEntry | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<KnowledgeEntry | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [publishing, setPublishing] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchPublishing, setBatchPublishing] = useState(false);
  const [versionTarget, setVersionTarget] = useState<KnowledgeEntry | null>(null);
  const [versionHistory, setVersionHistory] = useState<Array<{ type: string; field: string; old_value: unknown; new_value: unknown; at: string }>>([]);
  const [versionLoading, setVersionLoading] = useState(false);
  // Edit sheet advanced section toggle
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // Unified add dialog state
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [addDialogTab, setAddDialogTab] = useState<"manual" | "ai">("manual");
  const [addManualForm, setAddManualForm] = useState({ title: "", content: "", category: "faq" as KnowledgeCategory });
  const [addManualSaving, setAddManualSaving] = useState(false);
  // AI Import state (used within unified dialog AI tab)
  const [aiImportTab, setAiImportTab] = useState<"file" | "text">("file");
  const [aiImportFile, setAiImportFile] = useState<File | null>(null);
  const [aiImportText, setAiImportText] = useState("");
  const [aiImportLoading, setAiImportLoading] = useState(false);
  const [aiImportResult, setAiImportResult] = useState<{ imported: number; entries: { title: string; id: string }[] } | null>(null);
  const [aiImportError, setAiImportError] = useState<string | null>(null);
  const [aiImportDragOver, setAiImportDragOver] = useState(false);
  // Toast notification
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  // Hit analysis view
  const [showHitAnalysis, setShowHitAnalysis] = useState(false);
  const [hitAnalysisData, setHitAnalysisData] = useState<{
    totalHits: number;
    totalEntries: number;
    topEntry: { title: string; hit_count: number } | null;
    zeroHitCount: number;
    top20: Array<{ id: string; title: string; category: string; hit_count: number; updated_at: string }>;
    zeroHits: Array<{ id: string; title: string; category: string; content: string; tone: string; tags: string[]; priority: number; status: string }>;
  } | null>(null);
  const [hitAnalysisLoading, setHitAnalysisLoading] = useState(false);

  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (activeCategory !== "all") params.set("category", activeCategory);
      if (search.trim()) params.set("q", search.trim());
      params.set("status", statusFilter);
      if (sortBy) params.set("sort", sortBy);
      const res = await fetch(`/api/qa/knowledge?${params}`);
      if (res.ok) {
        const data = await res.json();
        setEntries(data.entries || []);
      } else {
        const errData = await res.json().catch(() => ({ error: "加载失败" }));
        setError(errData.error || "加载知识库失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setLoading(false);
  }, [activeCategory, search, statusFilter, sortBy]);

  const fetchHitAnalysis = useCallback(async () => {
    setHitAnalysisLoading(true);
    setHitAnalysisData(null);
    try {
      const res = await fetch("/api/qa/knowledge/stats");
      if (res.ok) {
        const data = await res.json();
        setHitAnalysisData(data);
      }
    } catch {
      /* skip */
    }
    setHitAnalysisLoading(false);
  }, []);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  // Fetch pending count for badge
  const [pendingCount, setPendingCount] = useState(0);
  useEffect(() => {
    fetch("/api/qa/knowledge/pending?limit=100")
      .then((r) => r.json())
      .then((data) => setPendingCount((data.entries || []).length))
      .catch(() => {});
  }, [entries]);

  useEffect(() => {
    fetch("/api/qa/platforms")
      .then((r) => r.json())
      .then((data) => {
        const map: Record<string, string> = {};
        (data.platforms || []).forEach((p: { id: number; name: string }) => {
          map[String(p.id)] = p.name;
        });
        setPlatformMap(map);
      })
      .catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    const res = await fetch(
      selected ? `/api/qa/knowledge/${selected.id}` : "/api/qa/knowledge",
      {
        method: selected ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editForm),
      }
    );
    if (res.ok) {
      setSelected(null);
      setEditMode(false);
      setAdvancedOpen(false);
      setToast({ message: selected ? "知识条目已更新" : "知识条目已创建", type: "success" });
      fetchEntries();
    }
    setSaving(false);
  };

  const handlePublish = async (id: string) => {
    setPublishing(id);
    await fetch(`/api/qa/knowledge/${id}/publish`, { method: "POST" });
    setToast({ message: "知识条目已发布", type: "success" });
    setPublishing(null);
    fetchEntries();
  };

  const handleReject = async () => {
    if (!rejectTarget) return;
    setRejecting(true);
    await fetch(`/api/qa/knowledge/${rejectTarget.id}/reject`, { method: "POST" });
    setToast({ message: "草稿已驳回", type: "success" });
    setRejecting(false);
    setRejectTarget(null);
    fetchEntries();
  };

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  };

  const selectAll = () => {
    if (selectedIds.size === entries.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(entries.map((e) => e.id)));
    }
  };

  const handleBatchPublish = async () => {
    if (selectedIds.size === 0) return;
    setBatchPublishing(true);
    for (const id of selectedIds) {
      await fetch(`/api/qa/knowledge/${id}/publish`, { method: "POST" });
    }
    setToast({ message: `已批量发布 ${selectedIds.size} 条知识`, type: "success" });
    setBatchPublishing(false);
    setSelectedIds(new Set());
    fetchEntries();
  };

  const handleViewVersions = async (entry: KnowledgeEntry) => {
    if (versionTarget?.id === entry.id) { setVersionTarget(null); setVersionHistory([]); return; }
    setVersionTarget(entry);
    setVersionLoading(true);
    try {
      const res = await fetch(`/api/qa/knowledge/${entry.id}/versions`);
      if (res.ok) {
        const data = await res.json();
        setVersionHistory(data.versions || []);
      }
    } catch { /* skip */ }
    setVersionLoading(false);
  };

  const handleBatchOperation = async (action: "delete" | "archive" | "publish") => {
    if (selectedIds.size === 0) return;
    setBatchActionLoading(true);
    const res = await fetch("/api/qa/knowledge/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ids: Array.from(selectedIds) }),
    });
    setBatchActionLoading(false);
    if (res.ok) {
      setToast({ message: action === "delete" ? "已批量删除" : "已批量归档", type: "success" });
      setSelectedIds(new Set());
      fetchEntries();
    }
  };

  const handleAddManual = async () => {
    if (!addManualForm.title.trim() || !addManualForm.content.trim()) return;
    setAddManualSaving(true);
    const res = await fetch("/api/qa/knowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(addManualForm),
    });
    if (res.ok) {
      setAddManualForm({ title: "", content: "", category: "faq" });
      setAddDialogOpen(false);
      setToast({ message: "知识条目已添加", type: "success" });
      fetchEntries();
    }
    setAddManualSaving(false);
  };

  const handleAiImport = async () => {
    if (aiImportTab === "file" && !aiImportFile) return;
    if (aiImportTab === "text" && !aiImportText.trim()) return;

    setAiImportLoading(true);
    setAiImportResult(null);
    setAiImportError(null);

    try {
      let res: Response;
      if (aiImportTab === "file" && aiImportFile) {
        const formData = new FormData();
        formData.append("file", aiImportFile);
        res = await fetch("/api/qa/knowledge/import", { method: "POST", body: formData });
      } else {
        res = await fetch("/api/qa/knowledge/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: aiImportText }),
        });
      }
      const data = await res.json();
      if (res.ok) {
        setAiImportResult(data);
        setToast({ message: `AI 导入成功，已添加 ${data.imported || 0} 条知识`, type: "success" });
        fetchEntries();
      } else {
        setAiImportError(data.error || "导入失败，请重试");
      }
    } catch {
      setAiImportError("网络请求失败，请检查后端服务");
    }
    setAiImportLoading(false);
  };

  const addTag = () => {
    const t = tagInput.trim();
    const currentTags = Array.isArray(editForm.tags) ? editForm.tags : [];
    if (t && !currentTags.includes(t)) {
      setEditForm({ ...editForm, tags: [...currentTags, t] });
    }
    setTagInput("");
  };

  const removeTag = (tag: string) => {
    const currentTags = Array.isArray(editForm.tags) ? editForm.tags : [];
    setEditForm({ ...editForm, tags: currentTags.filter((t) => t !== tag) });
  };

  const getTagColor = (tag: string): string => {
    let hash = 0;
    for (let i = 0; i < tag.length; i++) hash = tag.charCodeAt(i) + ((hash << 5) - hash);
    return TAG_COLORS[Math.abs(hash) % TAG_COLORS.length];
  };

  const handleArchive = async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    await fetch(`/api/qa/knowledge/${archiveTarget.id}`, { method: "DELETE" });
    setToast({ message: "知识条目已归档", type: "success" });
    setArchiving(false);
    setArchiveTarget(null);
    fetchEntries();
  };

  const handleRagSearch = async () => {
    setRagLoading(true);
    const res = await fetch(`/api/qa/knowledge?rag=${encodeURIComponent(ragQuery)}`);
    if (res.ok) {
      const data = await res.json();
      setRagResult(data.entries || []);
    }
    setRagLoading(false);
  };

  const handleGapAnalysis = async () => {
    setGapsLoading(true);
    setGaps(null);
    const res = await fetch("/api/qa/knowledge/gaps", { method: "GET" });
    if (res.ok) {
      const data = await res.json();
      setGaps(data);
    }
    setGapsLoading(false);
  };

  const openAddDialog = () => {
    setAddDialogTab("manual");
    setAddManualForm({ title: "", content: "", category: "faq" });
    setAiImportTab("file");
    setAiImportFile(null);
    setAiImportText("");
    setAiImportResult(null);
    setAiImportError(null);
    setAddDialogOpen(true);
  };

  const categories: (KnowledgeCategory | "all")[] = ["all", "product", "faq", "after_sales_policy", "campaign", "greeting"];
  const isEmpty = !loading && !error && entries.length === 0;

  return (
    <Panel
      title="知识库管理"
      subtitle="管理电商客服知识条目，支持 RAG 语义检索、缺口检测与自动沉淀"
      loading={loading}
      error={error}
      onRetry={fetchEntries}
      empty={isEmpty}
      emptyIcon={<FileText className="h-10 w-10 text-muted-foreground/20" />}
      emptyTitle={
        statusFilter === "draft" ? "暂无待审核条目" : "暂无知识条目"
      }
      emptyDescription={
        statusFilter === "draft"
          ? "知识缺口检测会自动生成待审核条目"
          : "点击右上角「添加知识」创建第一条知识库内容"
      }
      emptyAction={{
        label: "添加知识",
        onClick: openAddDialog,
      }}
      actions={
        <>
          <Button size="sm" variant="outline" onClick={handleGapAnalysis} disabled={gapsLoading}>
            {gapsLoading ? "检测中..." : "知识缺口检测"}
          </Button>
          <Button size="sm" variant="outline" onClick={async () => {
            setToast({ message: "正在推送到 Dify...", type: "success" });
            try {
              const res = await fetch("/api/qa/knowledge/push-to-dify", { method: "POST" });
              const data = await res.json();
              setToast({ message: data.succeeded ? `推送到 Dify 成功: ${data.succeeded} 条` : `推送失败: ${data.error}`, type: data.succeeded ? "success" : "error" });
            } catch { setToast({ message: "推送请求失败", type: "error" }); }
          }}><Upload className="w-3.5 h-3.5 mr-1" />推送到 Dify</Button>
          <Button size="sm" className="bg-brand-500 hover:bg-brand-600 text-white" onClick={() => { setSelected(null); setEditForm({ title: "", content: "", category: "faq", priority: 5, tone: "", tags: [], status: "published" }); setEditMode(true); setTagInput(""); setAdvancedOpen(false); }}>
            + 新增条目
          </Button>
        </>
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
      <div className="space-y-4">
        {/* RAG search */}
        <div className="flex gap-2">
          <Input
            className="flex-1"
            placeholder="RAG 语义检索：输入用户问题进行相似度匹配..."
            value={ragQuery}
            onChange={(e) => setRagQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleRagSearch()}
          />
          <Button size="sm" variant="outline" onClick={handleRagSearch} disabled={ragLoading}>
            {ragLoading ? <><Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />检索中...</> : "检索"}
          </Button>
        </div>

        {ragResult.length > 0 && (
          <Card className="border-blue-200 bg-blue-50/50">
            <CardContent className="py-3">
              <p className="text-xs text-muted-foreground/70 mb-2">RAG 匹配结果 ({ragResult.length} 条)</p>
              {ragResult.map((e) => (
                <div key={e.id} className="text-xs py-1 border-b border-blue-100 last:border-0">
                  <span className="font-medium">{e.title}</span>
                  <span className="text-muted-foreground/50 ml-2">— {(e.content || "").slice(0, 100)}...</span>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* Gap analysis result */}
        {gaps && (
          <Card className="border-amber-200 bg-amber-50/50">
            <CardContent className="py-3 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-amber-800">知识缺口检测</p>
                {(gaps.total_unhandled as number) != null && (
                  <span className="text-xs text-amber-600">{(gaps.total_unhandled as number)} 条未命中会话</span>
                )}
              </div>
              {(gaps.gaps as Array<{ question: string; similarity: number }>)?.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-muted-foreground/70">未命中问题 ({(gaps.gaps as Array<{ question: string; similarity: number }>).length} 条)</p>
                  {(gaps.gaps as Array<{ question: string; similarity: number }>).slice(0, 10).map((g, i) => (
                    <div key={i} className="text-xs text-muted-foreground py-1 border-b border-amber-100 last:border-0">
                      {g.question}
                    </div>
                  ))}
                </div>
              )}
              {(gaps.clusters as Array<{ topic: string; count: number; examples?: string[]; suggestion?: string }>)?.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground/70">缺口聚类</p>
                  {(gaps.clusters as Array<{ topic: string; count: number; examples?: string[]; suggestion?: string }>).map((c, i) => (
                    <div key={i} className="p-2 bg-white rounded border border-amber-100">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-amber-800">{c.topic}</span>
                        <span className="text-xs text-amber-600">{c.count} 条</span>
                      </div>
                      {c.suggestion && (
                        <p className="text-xs text-blue-700 mt-1 bg-blue-50 p-1.5 rounded">
                          建议：{c.suggestion}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Status tabs */}
        <div className="flex gap-1 flex-wrap">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => { setStatusFilter(opt.value); setActiveCategory("all"); setShowHitAnalysis(false); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all relative ${
                statusFilter === opt.value
                  ? "bg-brand-500 text-white"
                  : "bg-muted text-muted-foreground hover:bg-border"
              }`}
            >
              {opt.label}
              {opt.value === "draft" && pendingCount > 0 && (
                <span className={`absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full text-[10px] flex items-center justify-center ${
                  statusFilter === "draft" ? "bg-white text-zinc-900" : "bg-red-500 text-white"
                }`}>
                  {pendingCount}
                </span>
              )}
            </button>
          ))}
          <button
            type="button"
            onClick={() => { setShowHitAnalysis(true); fetchHitAnalysis(); }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              showHitAnalysis
                ? "bg-brand-500 text-white"
                : "bg-muted text-muted-foreground hover:bg-border"
            }`}
          >
            命中分析
          </button>
        </div>

        {/* Hit Analysis View */}
        {showHitAnalysis && (
          <div className="space-y-4">
            {hitAnalysisLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-6 w-6 text-muted-foreground/50 animate-spin" />
                <span className="ml-2 text-sm text-muted-foreground/70">加载命中分析数据...</span>
              </div>
            ) : hitAnalysisData ? (
              <>
                {/* Stat cards */}
                <div className="grid grid-cols-3 gap-4">
                  <div className="bg-white rounded-lg shadow-sm p-4 border border-muted">
                    <p className="text-xs text-muted-foreground/70 mb-1">总命中次数</p>
                    <p className="text-3xl font-bold text-foreground">{hitAnalysisData.totalHits.toLocaleString()}</p>
                    <p className="text-xs text-muted-foreground/50 mt-1">{hitAnalysisData.totalEntries} 条已发布</p>
                  </div>
                  <div className="bg-white rounded-lg shadow-sm p-4 border border-muted">
                    <p className="text-xs text-muted-foreground/70 mb-1">热门条目 TOP1</p>
                    {hitAnalysisData.topEntry ? (
                      <>
                        <p className="text-lg font-bold text-foreground truncate" title={hitAnalysisData.topEntry.title}>
                          {hitAnalysisData.topEntry.title}
                        </p>
                        <p className="text-xs text-brand-500 mt-1">{hitAnalysisData.topEntry.hit_count.toLocaleString()} 次命中</p>
                      </>
                    ) : (
                      <p className="text-3xl font-bold text-muted-foreground/20">—</p>
                    )}
                  </div>
                  <div className="bg-white rounded-lg shadow-sm p-4 border border-muted">
                    <p className="text-xs text-muted-foreground/70 mb-1">零命中条目数</p>
                    <p className="text-3xl font-bold text-amber-600">{hitAnalysisData.zeroHitCount}</p>
                    <p className="text-xs text-muted-foreground/50 mt-1">
                      {hitAnalysisData.totalEntries > 0
                        ? `占比 ${((hitAnalysisData.zeroHitCount / hitAnalysisData.totalEntries) * 100).toFixed(1)}%`
                        : "—"}
                    </p>
                  </div>
                </div>

                {/* Top 20 table */}
                <Card>
                  <CardContent className="p-0">
                    <div className="px-4 py-3 border-b border-muted">
                      <p className="text-sm font-semibold text-foreground/70">Top 20 热门条目</p>
                    </div>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[50px]">排名</TableHead>
                          <TableHead>标题</TableHead>
                          <TableHead>分类</TableHead>
                          <TableHead className="text-right">命中次数</TableHead>
                          <TableHead className="text-right">最近更新时间</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {hitAnalysisData.top20.length === 0 ? (
                          <TableRow>
                            <TableCell colSpan={5} className="text-center text-muted-foreground/50 py-6">
                              暂无数据
                            </TableCell>
                          </TableRow>
                        ) : (
                          hitAnalysisData.top20.map((e, i) => (
                            <TableRow key={e.id} className="h-10">
                              <TableCell className="text-xs text-muted-foreground/70 px-4 py-2">
                                {i + 1}
                              </TableCell>
                              <TableCell className="font-medium text-sm max-w-[200px] truncate px-4 py-2">
                                {e.title}
                              </TableCell>
                              <TableCell className="px-4 py-2">
                                <Badge variant="outline" className="text-xs">
                                  {CATEGORY_LABELS[e.category as KnowledgeCategory] || e.category}
                                </Badge>
                              </TableCell>
                              <TableCell className="text-right text-sm font-medium text-foreground/70 px-4 py-2">
                                {e.hit_count.toLocaleString()}
                              </TableCell>
                              <TableCell className="text-right text-xs text-muted-foreground/50 px-4 py-2">
                                {e.updated_at ? new Date(e.updated_at).toLocaleDateString("zh-CN") : "—"}
                              </TableCell>
                            </TableRow>
                          ))
                        )}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>

                {/* Zero hits list */}
                <Card>
                  <CardContent className="p-0">
                    <div className="px-4 py-3 border-b border-muted">
                      <p className="text-sm font-semibold text-foreground/70">
                        零命中条目
                        {hitAnalysisData.zeroHitCount > 10 && (
                          <span className="text-xs text-muted-foreground/50 ml-1 font-normal">
                            （显示前 10 条，共 {hitAnalysisData.zeroHitCount} 条）
                          </span>
                        )}
                      </p>
                    </div>
                    {hitAnalysisData.zeroHits.length === 0 ? (
                      <div className="px-4 py-6 text-center text-sm text-muted-foreground/50">
                        所有条目均有命中记录
                      </div>
                    ) : (
                      <div className="divide-y divide-muted">
                        {hitAnalysisData.zeroHits.map((e) => (
                          <div key={e.id} className="flex items-center justify-between px-4 py-3">
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-foreground/70 truncate">{e.title}</p>
                              <p className="text-xs text-muted-foreground/50 mt-0.5">
                                {CATEGORY_LABELS[e.category as KnowledgeCategory] || e.category}
                              </p>
                            </div>
                            <Button
                              size="sm"
                              variant="outline"
                              className="ml-3 shrink-0"
                              onClick={() => {
                                setSelected({
                                  id: e.id,
                                  title: e.title,
                                  content: e.content,
                                  category: e.category as KnowledgeCategory,
                                  priority: e.priority,
                                  tone: e.tone,
                                  tags: e.tags,
                                  status: e.status,
                                } as KnowledgeEntry);
                                setEditForm({
                                  title: e.title || "",
                                  content: e.content || "",
                                  category: e.category as KnowledgeCategory,
                                  priority: e.priority ?? 5,
                                  tone: (e.tone || "") as KnowledgeTone,
                                  tags: Array.isArray(e.tags) ? e.tags : [],
                                  status: e.status || "published",
                                });
                                setEditMode(true);
                                setTagInput("");
                                setAdvancedOpen(false);
                              }}
                            >
                              完善内容
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            ) : (
              <div className="flex items-center justify-center py-16">
                <p className="text-sm text-muted-foreground/50">加载失败，请重试</p>
              </div>
            )}
          </div>
        )}

        {/* Category tabs + search + sort + unified add button */}
        {!showHitAnalysis && (
        <>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex gap-1 flex-1">
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setActiveCategory(cat)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  activeCategory === cat
                    ? "bg-indigo-100 text-indigo-700"
                    : "bg-muted text-muted-foreground hover:bg-border"
                }`}
              >
                {cat === "all" ? "全部" : CATEGORY_LABELS[cat]}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <select
              className="h-9 rounded-md border border-border bg-white px-2 text-xs text-muted-foreground"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
            >
              <option value="newest">最新</option>
              <option value="popular">最热</option>
              <option value="name">名称</option>
            </select>
            <Input
              className="min-w-[260px]"
              placeholder="搜索关键词..."
              inputMode="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button
              size="sm"
              className="bg-brand-500 hover:bg-brand-600 text-white"
              onClick={openAddDialog}
            >
              <Plus className="h-4 w-4 mr-1" />
              添加知识
            </Button>
          </div>
        </div>

        {/* Entries table */}
        <Card>
          <CardContent className="p-0">
            {selectedIds.size > 0 && (
              <div className="px-4 py-2 bg-zinc-50 border-b border-zinc-100 flex items-center gap-3">
                <span className="text-xs text-muted-foreground">已选 {selectedIds.size} 条</span>
                {statusFilter === "draft" ? (
                  <Button size="sm" onClick={handleBatchPublish} disabled={batchPublishing}>
                    {batchPublishing ? "批量发布中..." : "批量发布"}
                  </Button>
                ) : (
                  <>
                    {statusFilter !== "archived" && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="text-amber-600 border-amber-200 hover:bg-amber-50"
                        onClick={() => handleBatchOperation("archive")}
                        disabled={batchActionLoading}
                      >
                        {batchActionLoading ? "处理中..." : "批量归档"}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => handleBatchOperation("delete")}
                      disabled={batchActionLoading}
                    >
                      {batchActionLoading ? "处理中..." : "批量归档"}
                    </Button>
                  </>
                )}
              </div>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[40px]">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === entries.length && entries.length > 0}
                      onChange={selectAll}
                      className="w-4 h-4 rounded border-muted-foreground/20 accent-zinc-900"
                    />
                  </TableHead>
                  <TableHead>标题</TableHead>
                  <TableHead>分类</TableHead>
                  <TableHead>来源</TableHead>
                  {statusFilter === "draft" && <TableHead>置信度</TableHead>}
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((e) => (
                  <TableRow key={e.id} className="h-12">
                    <TableCell className="px-4 py-2">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(e.id)}
                        onChange={() => toggleSelect(e.id)}
                        className="w-4 h-4 rounded border-muted-foreground/20 accent-zinc-900"
                      />
                    </TableCell>
                    <TableCell className="font-medium text-sm max-w-[200px] truncate px-4 py-2">
                      {e.title}
                    </TableCell>
                    <TableCell className="px-4 py-2">
                      <Badge variant="outline" className="text-xs">
                        {CATEGORY_LABELS[e.category] || e.category}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground/70 px-4 py-2">
                      {SOURCE_LABELS[e.source || ""] || e.source || "手动"}
                    </TableCell>
                    {statusFilter === "draft" && (
                      <TableCell className="text-xs px-4 py-2">
                        {(() => {
                          const metrics = (e.effect_metrics && typeof e.effect_metrics === "object")
                            ? (e.effect_metrics as Record<string, unknown>)
                            : null;
                          if (!metrics || metrics.llm_confidence == null) return "—";
                          return (
                            <span className={`font-medium ${metrics.auto_published ? "text-emerald-600" : "text-muted-foreground"}`}>
                              {((Number(metrics.llm_confidence) * 100).toFixed(0))}%
                              {metrics.auto_published ? " 自动" : ""}
                            </span>
                          );
                        })()}
                      </TableCell>
                    )}
                    <TableCell className="px-4 py-2">
                      <span className={`inline-block px-2 py-0.5 text-xs rounded-full font-medium ${STATUS_COLORS[e.status] || ""}`}>
                        {e.status === "published" ? "已发布" : e.status === "draft" ? "草稿" : "已归档"}
                      </span>
                    </TableCell>
                    <TableCell className="text-right px-4 py-2">
                      <div className="flex items-center justify-end gap-1">
                        {e.status === "draft" ? (
                          <>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground/50 hover:text-emerald-600 hover:bg-emerald-50"
                              title="发布"
                              onClick={() => handlePublish(e.id)}
                              disabled={publishing === e.id}
                            >
                              <CheckCircle className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground/50 hover:text-red-600 hover:bg-red-50"
                              title="驳回"
                              onClick={() => setRejectTarget(e)}
                            >
                              <XCircle className="h-4 w-4" />
                            </Button>
                          </>
                        ) : (
                          <>
                            {(e.version ?? 1) > 1 && (
                              <Button
                                variant="ghost"
                                size="icon"
                                className={`h-8 w-8 ${versionTarget?.id === e.id ? "text-amber-600 bg-amber-50" : "text-muted-foreground/50 hover:text-amber-600 hover:bg-amber-50"}`}
                                title="版本历史"
                                onClick={() => handleViewVersions(e)}
                              >
                                <History className="h-4 w-4" />
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground/50 hover:text-blue-600 hover:bg-blue-50"
                              title="编辑"
                              onClick={() => { setSelected(e); setEditForm({ title: e.title || "", content: e.content || "", category: e.category || "faq", priority: e.priority ?? 5, tone: (e.tone || "") as KnowledgeTone, tags: Array.isArray(e.tags) ? e.tags : [], status: e.status || "published" }); setEditMode(true); setTagInput(""); setAdvancedOpen(false); }}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground/50 hover:text-red-600 hover:bg-red-50"
                              title="归档"
                              onClick={() => setArchiveTarget(e)}
                            >
                              <Archive className="h-4 w-4" />
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        </>
        )}

        {/* Edit Sheet */}
        <Sheet open={editMode} onOpenChange={setEditMode}>
          <SheetContent side="right" className="w-[500px] sm:max-w-[500px] overflow-y-auto">
            <SheetHeader>
              <SheetTitle>{selected ? "编辑知识条目" : "新增知识条目"}</SheetTitle>
            </SheetHeader>
            <div className="space-y-4 mt-6">
              <div>
                <label className="text-xs font-medium text-muted-foreground/70">分类</label>
                <select
                  className="w-full mt-1 rounded-md border px-2 py-1.5 text-sm"
                  value={editForm.category}
                  onChange={(e) => setEditForm({ ...editForm, category: e.target.value as KnowledgeCategory })}
                >
                  {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground/70">标题</label>
                <Input
                  className="mt-1"
                  value={editForm.title}
                  onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground/70">内容</label>
                <Textarea
                  className="mt-1 min-h-[200px]"
                  value={editForm.content}
                  onChange={(e) => setEditForm({ ...editForm, content: e.target.value })}
                />
              </div>

              {/* Advanced settings expandable section */}
              <div className="border border-border rounded-lg">
                <button
                  type="button"
                  onClick={() => setAdvancedOpen(!advancedOpen)}
                  className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-medium text-muted-foreground hover:bg-muted/50 rounded-lg transition-colors"
                >
                  <span>高级设置</span>
                  {advancedOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </button>
                {advancedOpen && (
                  <div className="px-3 pb-3 space-y-4 border-t border-muted pt-3">
                    <div>
                      <label className="text-xs font-medium text-muted-foreground/70">语调</label>
                      <select
                        className="w-full mt-1 rounded-md border px-2 py-1.5 text-sm"
                        value={editForm.tone}
                        onChange={(e) => setEditForm({ ...editForm, tone: e.target.value as KnowledgeTone })}
                      >
                        <option value="">不设置</option>
                        {Object.entries(TONE_LABELS).map(([k, v]) => (
                          <option key={k} value={k}>{v}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-muted-foreground/70">标签</label>
                      <div className="flex gap-2 mt-1">
                        <Input
                          className="flex-1"
                          placeholder="输入标签后按回车添加"
                          value={tagInput}
                          onChange={(e) => setTagInput(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
                        />
                        <Button size="sm" variant="outline" onClick={addTag} type="button">
                          <Plus className="h-3 w-3" />
                        </Button>
                      </div>
                      {editForm.tags.length > 0 && (
                        <div className="flex gap-1 flex-wrap mt-2">
                          {editForm.tags.map((tag, i) => (
                            <span
                              key={i}
                              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium ${getTagColor(tag)}`}
                            >
                              {tag}
                              <button
                                type="button"
                                className="hover:opacity-70"
                                onClick={() => removeTag(tag)}
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div>
                      <label className="text-xs font-medium text-muted-foreground/70">优先级 (1-10)</label>
                      <Input
                        className="mt-1 w-24"
                        type="number"
                        min={1}
                        max={10}
                        value={editForm.priority}
                        onChange={(e) => setEditForm({ ...editForm, priority: Number(e.target.value) })}
                      />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-muted-foreground/70">状态</label>
                      <select
                        className="w-full mt-1 rounded-md border px-2 py-1.5 text-sm"
                        value={editForm.status}
                        onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
                      >
                        <option value="draft">待审核</option>
                        <option value="published">已发布</option>
                        <option value="archived">已归档</option>
                      </select>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-2 pt-2">
                <Button className="flex-1 bg-brand-500 hover:bg-brand-600 text-white" onClick={handleSave} disabled={saving}>
                  {saving ? "保存中..." : "保存"}
                </Button>
                <Button variant="outline" onClick={() => setEditMode(false)}>取消</Button>
              </div>
            </div>
          </SheetContent>
        </Sheet>

        {/* Archive confirmation dialog */}
        <Dialog open={!!archiveTarget} onOpenChange={(open) => { if (!open) setArchiveTarget(null); }}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认归档</DialogTitle>
              <DialogDescription>
                确定要归档知识条目「{archiveTarget?.title}」吗？归档后机器人将不再使用此知识。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setArchiveTarget(null)}>取消</Button>
              <Button variant="destructive" onClick={handleArchive} disabled={archiving}>
                {archiving ? "归档中..." : "确认归档"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Reject confirmation dialog */}
        <Dialog open={!!rejectTarget} onOpenChange={(open) => { if (!open) setRejectTarget(null); }}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>驳回草稿</DialogTitle>
              <DialogDescription>
                驳回后将归档该知识条目草稿「{rejectTarget?.title}」。此操作可撤销（可从已归档中恢复）。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setRejectTarget(null)}>取消</Button>
              <Button variant="destructive" onClick={handleReject} disabled={rejecting}>
                {rejecting ? "驳回中..." : "确认驳回"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Version history dialog */}
        <Dialog open={!!versionTarget} onOpenChange={(open) => { if (!open) { setVersionTarget(null); setVersionHistory([]); } }}>
          <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle className="text-sm">版本历史 — {versionTarget?.title}</DialogTitle>
              <DialogDescription className="text-xs">
                当前版本 v{versionTarget?.version}，共 {versionHistory.length} 条变更记录
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              {versionLoading ? (
                <p className="text-xs text-muted-foreground/50 py-4 text-center">加载中...</p>
              ) : versionHistory.length === 0 ? (
                <p className="text-xs text-muted-foreground/50 py-4 text-center">暂无变更记录</p>
              ) : (
                versionHistory.map((v, i) => {
                  const oldContent = typeof v.old_value === "string" ? v.old_value : JSON.stringify(v.old_value || "");
                  const newContent = typeof v.new_value === "string" ? v.new_value : JSON.stringify(v.new_value || "");
                  return (
                    <div key={i} className="rounded-lg border border-border overflow-hidden">
                      <div className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-muted">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-[10px]">
                            {v.type === "create" ? "创建" : v.type === "update" ? "更新" : v.type === "publish" ? "发布" : v.type === "archive" ? "归档" : String(v.type)}
                          </Badge>
                          <span className="text-[10px] text-muted-foreground/70">{new Date(v.at).toLocaleString("zh-CN")}</span>
                        </div>
                        <span className="text-[10px] text-muted-foreground/50">{v.field || "—"}</span>
                      </div>
                      {v.field && oldContent && newContent && oldContent !== newContent ? (
                        <div className="p-3 space-y-2">
                          {v.field === "content" ? (
                            <div className="space-y-2">
                              <div className="p-2 rounded bg-red-50 border border-red-100 text-xs text-red-700">
                                <span className="text-[10px] text-red-400 font-medium">旧版本</span>
                                <p className="mt-0.5 line-clamp-3">{oldContent}</p>
                              </div>
                              <div className="p-2 rounded bg-emerald-50 border border-emerald-100 text-xs text-emerald-700">
                                <span className="text-[10px] text-emerald-400 font-medium">新版本</span>
                                <p className="mt-0.5 line-clamp-3">{newContent}</p>
                              </div>
                            </div>
                          ) : (
                            <div className="flex items-center gap-2 text-xs">
                              <code className="text-red-600 line-through bg-red-50 px-1.5 py-0.5 rounded">{oldContent}</code>
                              <span className="text-muted-foreground/20">→</span>
                              <code className="text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded">{newContent}</code>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="px-3 py-2 text-xs text-muted-foreground/70">
                          {v.type === "create" ? "创建条目" : v.type === "publish" ? "发布条目" : v.type === "archive" ? "归档条目" : "状态变更"}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </DialogContent>
        </Dialog>

        {/* Unified Add Knowledge dialog */}
        <Dialog open={addDialogOpen} onOpenChange={(open) => { if (!open) { setAddDialogOpen(false); setAiImportResult(null); setAiImportError(null); } }}>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                添加知识
              </DialogTitle>
              <DialogDescription>
                手动填写知识条目，或通过 AI 智能识别批量导入
              </DialogDescription>
            </DialogHeader>

            {/* Outer tab switcher: manual vs AI */}
            <div className="border-b border-border pb-3 mb-3">
            <div className="flex gap-0 rounded-lg bg-muted p-0.5">
              <button
                type="button"
                onClick={() => { setAddDialogTab("manual"); setAiImportError(null); }}
                className={`flex-1 flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium transition-all ${
                  addDialogTab === "manual"
                    ? "bg-white text-foreground shadow-sm"
                    : "text-muted-foreground/70 hover:text-foreground/70"
                }`}
              >
                <Pencil className="h-3.5 w-3.5" />
                手动添加
              </button>
              <button
                type="button"
                onClick={() => { setAddDialogTab("ai"); setAiImportError(null); }}
                className={`flex-1 flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium transition-all ${
                  addDialogTab === "ai"
                    ? "bg-white text-foreground shadow-sm"
                    : "text-muted-foreground/70 hover:text-foreground/70"
                }`}
              >
                <Sparkles className="h-3.5 w-3.5" />
                AI 智能导入
              </button>
            </div>
            </div>

            {/* Manual tab content */}
            {addDialogTab === "manual" && (
              <div className="space-y-4 py-2">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">
                    标题 <span className="text-red-400">*</span>
                  </label>
                  <Input
                    placeholder="输入知识条目标题"
                    value={addManualForm.title}
                    onChange={(e) => setAddManualForm({ ...addManualForm, title: e.target.value })}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">
                    分类
                  </label>
                  <select
                    className="w-full h-9 rounded-md border border-border bg-white px-2 text-sm"
                    value={addManualForm.category}
                    onChange={(e) => setAddManualForm({ ...addManualForm, category: e.target.value as KnowledgeCategory })}
                  >
                    {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">
                    内容 <span className="text-red-400">*</span>
                  </label>
                  <Textarea
                    className="min-h-[120px]"
                    placeholder="输入知识内容..."
                    value={addManualForm.content}
                    onChange={(e) => setAddManualForm({ ...addManualForm, content: e.target.value })}
                  />
                </div>
                <Button
                  className="w-full bg-brand-500 hover:bg-brand-600 text-white"
                  onClick={handleAddManual}
                  disabled={addManualSaving || !addManualForm.title.trim() || !addManualForm.content.trim()}
                >
                  {addManualSaving ? "添加中..." : "添加知识"}
                </Button>
              </div>
            )}

            {/* AI tab content */}
            {addDialogTab === "ai" && (
              <>
                {/* Inner tab switcher for AI: file vs text */}
                <div className="flex gap-0 rounded-lg bg-muted p-0.5">
                  <button
                    type="button"
                    onClick={() => { setAiImportTab("file"); setAiImportError(null); }}
                    className={`flex-1 flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium transition-all ${
                      aiImportTab === "file"
                        ? "bg-white text-foreground shadow-sm"
                        : "text-muted-foreground/70 hover:text-foreground/70"
                    }`}
                  >
                    <Upload className="h-3.5 w-3.5" />
                    上传文件
                  </button>
                  <button
                    type="button"
                    onClick={() => { setAiImportTab("text"); setAiImportError(null); }}
                    className={`flex-1 flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium transition-all ${
                      aiImportTab === "text"
                        ? "bg-white text-foreground shadow-sm"
                        : "text-muted-foreground/70 hover:text-foreground/70"
                    }`}
                  >
                    <FileText className="h-3.5 w-3.5" />
                    粘贴文本
                  </button>
                </div>

                {/* Loading state */}
                {aiImportLoading && (
                  <div className="flex flex-col items-center justify-center py-8 space-y-3">
                    <Loader2 className="h-8 w-8 text-indigo-500 animate-spin" />
                    <p className="text-sm text-muted-foreground">AI 正在分析文本，提取问答对...</p>
                    <p className="text-xs text-muted-foreground/50">这可能需要几秒钟</p>
                  </div>
                )}

                {/* Result state */}
                {!aiImportLoading && aiImportResult && (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-4 space-y-3">
                    <div className="flex items-center gap-2">
                      <CheckCircle className="h-5 w-5 text-emerald-600" />
                      <p className="text-sm font-semibold text-emerald-800">
                        成功导入 {aiImportResult.imported} 条问答
                      </p>
                    </div>
                    {aiImportResult.entries.length > 0 && (
                      <div className="space-y-1.5">
                        <p className="text-xs font-medium text-muted-foreground/70">导入预览：</p>
                        <div className="max-h-40 overflow-y-auto space-y-1">
                          {aiImportResult.entries.map((entry, i) => (
                            <div key={entry.id || i} className="text-xs text-muted-foreground py-1 px-2 bg-white rounded border border-emerald-100 truncate">
                              {i + 1}. {entry.title}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      className="w-full"
                      onClick={() => { setAddDialogOpen(false); setAiImportResult(null); setAiImportError(null); setAiImportFile(null); setAiImportText(""); }}
                    >
                      完成
                    </Button>
                  </div>
                )}

                {/* Error state */}
                {!aiImportLoading && aiImportError && (
                  <div className="rounded-lg border border-red-200 bg-red-50/50 p-4 space-y-3">
                    <div className="flex items-center gap-2">
                      <XCircle className="h-5 w-5 text-red-600" />
                      <p className="text-sm font-semibold text-red-800">导入失败</p>
                    </div>
                    <p className="text-xs text-red-600">{aiImportError}</p>
                    <Button
                      size="sm"
                      variant="outline"
                      className="w-full border-red-200 text-red-700 hover:bg-red-50"
                      onClick={handleAiImport}
                    >
                      重试
                    </Button>
                  </div>
                )}

                {/* Input state (no loading/result/error) */}
                {!aiImportLoading && !aiImportResult && !aiImportError && (
                  <>
                    {aiImportTab === "file" ? (
                      <div
                        className={`relative rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
                          aiImportDragOver
                            ? "border-indigo-400 bg-indigo-50/50"
                            : "border-border hover:border-muted-foreground/20 bg-muted/50/50"
                        }`}
                        onDragOver={(e) => { e.preventDefault(); setAiImportDragOver(true); }}
                        onDragLeave={(e) => { e.preventDefault(); setAiImportDragOver(false); }}
                        onDrop={(e) => {
                          e.preventDefault();
                          setAiImportDragOver(false);
                          const droppedFile = e.dataTransfer.files?.[0];
                          if (droppedFile) {
                            const ext = droppedFile.name.toLowerCase();
                            if (ext.endsWith(".txt") || ext.endsWith(".csv") || ext.endsWith(".md")) {
                              setAiImportFile(droppedFile);
                              setAiImportError(null);
                            } else {
                              setAiImportError("不支持的文件格式，请上传 .txt、.csv 或 .md 文件");
                            }
                          }
                        }}
                      >
                        {aiImportFile ? (
                          <div className="space-y-1">
                            <FileText className="h-8 w-8 text-indigo-500 mx-auto" />
                            <p className="text-sm font-medium text-foreground/70">{aiImportFile.name}</p>
                            <p className="text-xs text-muted-foreground/50">
                              {(aiImportFile.size / 1024).toFixed(1)} KB
                            </p>
                            <button
                              type="button"
                              className="text-xs text-muted-foreground/50 hover:text-red-500 mt-1"
                              onClick={() => setAiImportFile(null)}
                            >
                              移除文件
                            </button>
                          </div>
                        ) : (
                          <div className="space-y-2">
                            <Upload className="h-8 w-8 text-muted-foreground/20 mx-auto" />
                            <p className="text-sm text-muted-foreground/70">
                              拖拽文件到此处，或点击下方选择文件
                            </p>
                            <p className="text-xs text-muted-foreground/50">
                              支持 .txt / .csv / .md 格式，最大 5MB
                            </p>
                          </div>
                        )}
                        <input
                          type="file"
                          accept=".txt,.csv,.md"
                          className="absolute inset-0 opacity-0 cursor-pointer"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) {
                              setAiImportFile(file);
                              setAiImportError(null);
                            }
                          }}
                        />
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <Textarea
                          className="min-h-[180px]"
                          placeholder="在此粘贴文本内容，AI 将自动识别并提取问答对..."
                          value={aiImportText}
                          onChange={(e) => { setAiImportText(e.target.value); setAiImportError(null); }}
                        />
                        <p className="text-xs text-muted-foreground/50">
                          支持纯文本内容，AI 将自动提取 FAQ 问答对
                        </p>
                      </div>
                    )}

                    <Button
                      className="w-full bg-brand-500 hover:bg-brand-600 text-white"
                      onClick={handleAiImport}
                      disabled={
                        (aiImportTab === "file" && !aiImportFile) ||
                        (aiImportTab === "text" && !aiImportText.trim())
                      }
                    >
                      <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                      开始智能识别导入
                    </Button>
                  </>
                )}
              </>
            )}
          </DialogContent>
        </Dialog>
      </div>
    </Panel>
  );
}
