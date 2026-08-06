"use client";

import { useEffect, useState, useCallback } from "react";
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import Panel from "@/components/dashboard/Panel";
import {
  Download, Upload, AlertCircle, CheckCircle, Clock,
  XCircle, RefreshCw, TrendingUp, PlusCircle,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  PieChart, Pie, Cell, ResponsiveContainer,
} from "recharts";

interface UnresolvedEntry {
  id: string;
  session_id: string;
  platform_code: string | null;
  user_question: string;
  ai_reply: string | null;
  transfer_reason: string | null;
  conversation: string | null;
  satisfaction: string | null;
  category: string | null;
  status: string;
  priority: number;
  note: string | null;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
}

interface StatsData {
  status_distribution: Record<string, number>;
  category_distribution: Record<string, number>;
  avg_resolution_hours: number;
  total: number;
  trend?: Array<{ date_str: string; total_count: number; pending_count: number; resolved_count: number; exported_count: number }>;
  platform_distribution?: Record<string, number>;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "待处理", processing: "处理中", resolved: "已解决",
  rejected: "已驳回", exported: "已导出",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  processing: "bg-blue-100 text-blue-700",
  resolved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-muted text-muted-foreground/50",
  exported: "bg-purple-100 text-purple-700",
};

const SATISFACTION_LABELS: Record<string, string> = {
  bad: "差", neutral: "一般", good: "好",
};

const SATISFACTION_COLORS: Record<string, string> = {
  bad: "text-red-600", neutral: "text-amber-600", good: "text-green-600",
};

function extractCheckedSteps(conversation: string | null): string {
  if (!conversation) return "";
  const lines = conversation.split(/\r?\n/);
  const steps: string[] = [];
  let inSteps = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      if (inSteps && steps.length > 0) break;
      continue;
    }
    if (/^已排查步骤[：:]/.test(line)) {
      inSteps = true;
      const inline = line.replace(/^已排查步骤[：:]\s*/, "").trim();
      if (inline) steps.push(inline);
      continue;
    }
    if (inSteps && /^(未解决原因|用户|AI|客服|机器人)[：:]/.test(line)) break;
    if (inSteps) steps.push(line.replace(/^\s*(?:[-*]|\d+[.、)])\s*/, ""));
  }

  return steps.join("；");
}

export default function UnresolvedPanel() {
  const [entries, setEntries] = useState<UnresolvedEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [stats, setStats] = useState<StatsData | null>(null);
  const [selected, setSelected] = useState<UnresolvedEntry | null>(null);
  const [noteInput, setNoteInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; entries: unknown[] } | null>(null);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createForm, setCreateForm] = useState({
    channel: "app_h5",
    user_question: "",
    issue_type: "",
    checked_steps: "",
    unresolved_reason: "",
    ai_reply: "",
  });
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

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
      if (statusFilter !== "all") params.set("status", statusFilter);
      params.set("limit", "100");
      const res = await fetch(`/api/qa/unresolved?${params}`);
      if (res.ok) {
        const data = await res.json();
        setEntries(data.entries || []);
      } else {
        setError("加载未解决问题失败");
      }
    } catch {
      setError("网络请求失败");
    }
    setLoading(false);
  }, [statusFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch("/api/qa/unresolved/stats");
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch { /* skip */ }
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    fetchEntries();
    fetchStats();
  }, [fetchEntries, fetchStats]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleStatusChange = async (id: string, status: string) => {
    setSaving(true);
    try {
      const res = await fetch(`/api/qa/unresolved/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (res.ok) {
        setToast({ message: `状态已更新为 "${STATUS_LABELS[status] || status}"`, type: "success" });
        fetchEntries();
        fetchStats();
      }
    } catch {
      setToast({ message: "更新失败", type: "error" });
    }
    setSaving(false);
  };

  const handleSaveNote = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/qa/unresolved/${selected.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: noteInput, status: "processing" }),
      });
      if (res.ok) {
        setToast({ message: "备注已保存", type: "success" });
        setSelected(null);
        fetchEntries();
      }
    } catch {
      setToast({ message: "保存失败", type: "error" });
    }
    setSaving(false);
  };

  const handleExport = async (format: string) => {
    setExportLoading(true);
    try {
      const res = await fetch(`/api/qa/unresolved/export?format=${format}&status=${statusFilter}`);
      if (!res.ok) { setToast({ message: "导出失败", type: "error" }); return; }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ext = format === "markdown" ? "md" : format === "excel" ? "xls" : format;
      a.download = `unresolved_questions_${new Date().toISOString().slice(0, 10)}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
      setToast({ message: "导出成功，文件已下载", type: "success" });
      fetchEntries();
    } catch {
      setToast({ message: "导出失败", type: "error" });
    }
    setExportLoading(false);
  };

  const handleImport = async () => {
    if (!importFile) return;
    setImportLoading(true);
    setImportResult(null);
    try {
      const formData = new FormData();
      formData.append("file", importFile);
      const res = await fetch("/api/qa/knowledge/import-trained", {
        method: "POST",
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        setImportResult(data);
        setToast({ message: `成功导入 ${data.imported || 0} 条知识`, type: "success" });
        fetchEntries();
      } else {
        const err = await res.json().catch(() => ({ error: "导入失败" }));
        setToast({ message: err.error || "导入失败", type: "error" });
      }
    } catch {
      setToast({ message: "导入请求失败", type: "error" });
    }
    setImportLoading(false);
  };

  const handleCreateEntry = async () => {
    const userQuestion = createForm.user_question.trim();
    if (!userQuestion) {
      setToast({ message: "请填写用户原话", type: "error" });
      return;
    }

    setCreateLoading(true);
    try {
      const checkedSteps = createForm.checked_steps
        .split(/\r?\n/)
        .map((step) => step.trim())
        .filter(Boolean);

      const res = await fetch("/api/qa/unresolved", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: `manual_${Date.now()}`,
          platform_code: createForm.channel,
          user_question: userQuestion,
          issue_type: createForm.issue_type,
          checked_steps: checkedSteps,
          unresolved_reason: createForm.unresolved_reason,
          ai_reply: createForm.ai_reply,
        }),
      });

      if (res.ok) {
        setToast({ message: "未解决问题已记录", type: "success" });
        setCreateDialogOpen(false);
        setCreateForm({
          channel: "app_h5",
          user_question: "",
          issue_type: "",
          checked_steps: "",
          unresolved_reason: "",
          ai_reply: "",
        });
        fetchEntries();
        fetchStats();
      } else {
        const err = await res.json().catch(() => ({ error: "记录失败" }));
        setToast({ message: err.error || "记录失败", type: "error" });
      }
    } catch {
      setToast({ message: "记录请求失败", type: "error" });
    }
    setCreateLoading(false);
  };

  const statusCount = (s: string) => stats?.status_distribution?.[s] || 0;

  const actions = (
    <>
      <Button size="sm" onClick={() => setCreateDialogOpen(true)}>
        <PlusCircle className="w-3.5 h-3.5 mr-1" /> 新增记录
      </Button>
      <select
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
        className="w-32 h-8 text-xs rounded-lg border border-border bg-background px-2"
      >
        <option value="all">全部</option>
        <option value="pending">待处理 ({statusCount("pending")})</option>
        <option value="processing">处理中 ({statusCount("processing")})</option>
        <option value="resolved">已解决 ({statusCount("resolved")})</option>
        <option value="exported">已导出 ({statusCount("exported")})</option>
      </select>
      <Button size="sm" variant="outline" onClick={() => handleExport("excel")} disabled={exportLoading}>
        <Download className="w-3.5 h-3.5 mr-1" /> Excel
      </Button>
      <Button size="sm" variant="outline" onClick={() => handleExport("csv")} disabled={exportLoading}>
        <Download className="w-3.5 h-3.5 mr-1" /> CSV
      </Button>
      <Button size="sm" variant="outline" onClick={() => handleExport("markdown")} disabled={exportLoading}>
        <Download className="w-3.5 h-3.5 mr-1" /> MD
      </Button>
      <Button size="sm" onClick={() => setImportDialogOpen(true)}>
        <Upload className="w-3.5 h-3.5 mr-1" /> 导入训练
      </Button>
      <Button size="sm" variant="ghost" onClick={() => { fetchEntries(); fetchStats(); }}>
        <RefreshCw className="w-3.5 h-3.5" />
      </Button>
    </>
  );

  return (
    <Panel
      title="AI 未解决问题"
      subtitle="AI无法回答或满意度低的会话记录，导出后可导入话术训练系统"
      actions={actions}
      loading={loading}
      error={error}
      onRetry={fetchEntries}
      empty={!loading && !error && entries.length === 0}
      emptyIcon={<AlertCircle className="w-10 h-10" />}
      emptyTitle="暂无未解决问题"
      emptyDescription="过去24小时内没有AI无法处理的会话，继续保持！"
    >
      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
          <div className="bg-white rounded-lg border border-border p-3">
            <div className="text-xs text-muted-foreground/70">总计</div>
            <div className="text-xl font-bold text-foreground">{stats.total}</div>
          </div>
          <div className="bg-amber-50 rounded-lg border border-amber-200 p-3">
            <div className="text-xs text-amber-600">待处理</div>
            <div className="text-xl font-bold text-amber-700">{statusCount("pending")}</div>
          </div>
          <div className="bg-blue-50 rounded-lg border border-blue-200 p-3">
            <div className="text-xs text-blue-600">处理中</div>
            <div className="text-xl font-bold text-blue-700">{statusCount("processing")}</div>
          </div>
          <div className="bg-emerald-50 rounded-lg border border-emerald-200 p-3">
            <div className="text-xs text-emerald-600">已解决</div>
            <div className="text-xl font-bold text-emerald-700">{statusCount("resolved")}</div>
          </div>
          <div className="bg-purple-50 rounded-lg border border-purple-200 p-3">
            <div className="text-xs text-purple-600">已导出训练</div>
            <div className="text-xl font-bold text-purple-700">{statusCount("exported")}</div>
          </div>
        </div>
      )}

      {/* Charts */}
      {stats && stats.trend && stats.trend.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
          {/* Trend line chart */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <TrendingUp className="w-4 h-4" /> 每日趋势
              </CardTitle>
            </CardHeader>
            <CardContent className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={stats.trend.map((d) => ({ ...d, date: d.date_str?.slice(5) || "" }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="total_count" stroke="#94a3b8" name="总计" dot={false} />
                  <Line type="monotone" dataKey="pending_count" stroke="#f59e0b" name="待处理" dot={false} />
                  <Line type="monotone" dataKey="resolved_count" stroke="#10b981" name="已解决" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Category pie chart */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">分类分布</CardTitle>
            </CardHeader>
            <CardContent className="h-52">
              {Object.keys(stats.category_distribution).length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={Object.entries(stats.category_distribution)
                        .map(([k, v]) => ({ name: k, value: v }))
                        .filter((d) => d.value > 0)}
                      cx="50%" cy="50%" outerRadius={60} dataKey="value"
                      label={(props: { name?: string; percent?: number }) => `${props.name || ''} ${((props.percent ?? 0) * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {Object.keys(stats.category_distribution).map((_, i) => (
                        <Cell key={i} fill={["#f59e0b", "#3b82f6", "#10b981", "#8b5cf6", "#ef4444", "#ec4899"][i % 6]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex items-center justify-center h-full text-xs text-muted-foreground/50">暂无分类数据</div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-lg border border-border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">状态</TableHead>
              <TableHead className="min-w-[200px]">用户问题</TableHead>
              <TableHead className="min-w-[180px]">AI已排查步骤</TableHead>
              <TableHead className="w-24">分类</TableHead>
              <TableHead className="w-20">平台</TableHead>
              <TableHead className="w-20">满意度</TableHead>
              <TableHead className="w-28">时间</TableHead>
              <TableHead className="w-32">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow key={entry.id} className="group">
                <TableCell>
                  <Badge className={`text-xs ${STATUS_COLORS[entry.status] || "bg-muted"}`}>
                    {STATUS_LABELS[entry.status] || entry.status}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-md">
                  <div className="text-sm font-medium truncate" title={entry.user_question}>
                    {entry.user_question}
                  </div>
                  {entry.transfer_reason && (
                    <div className="text-xs text-muted-foreground/50 mt-0.5 truncate">
                      转人工: {entry.transfer_reason}
                    </div>
                  )}
                </TableCell>
                <TableCell className="max-w-xs">
                  <div className="text-xs text-muted-foreground/70 truncate" title={extractCheckedSteps(entry.conversation)}>
                    {extractCheckedSteps(entry.conversation) || "—"}
                  </div>
                </TableCell>
                <TableCell>
                  <span className="text-xs text-muted-foreground/70">{entry.category || "—"}</span>
                </TableCell>
                <TableCell>
                  <span className="text-xs text-muted-foreground/70">{entry.platform_code || "—"}</span>
                </TableCell>
                <TableCell>
                  {entry.satisfaction ? (
                    <span className={`text-xs font-medium ${SATISFACTION_COLORS[entry.satisfaction] || ""}`}>
                      {SATISFACTION_LABELS[entry.satisfaction] || entry.satisfaction}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground/20">—</span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground/50 whitespace-nowrap">
                  {new Date(entry.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {entry.status === "pending" && (
                      <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                        onClick={() => handleStatusChange(entry.id, "processing")}>
                        <Clock className="w-3 h-3 mr-1" /> 接手
                      </Button>
                    )}
                    {entry.status === "processing" && (
                      <>
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-green-600"
                          onClick={() => handleStatusChange(entry.id, "resolved")}>
                          <CheckCircle className="w-3 h-3 mr-1" /> 解决
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                          onClick={() => setSelected(entry)}>
                          备注
                        </Button>
                      </>
                    )}
                    {entry.status !== "resolved" && entry.status !== "rejected" && (
                      <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-muted-foreground/50"
                        onClick={() => handleStatusChange(entry.id, "rejected")}>
                        <XCircle className="w-3 h-3 mr-1" /> 驳回
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Create unresolved entry dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>新增未解决问题</DialogTitle>
            <DialogDescription>
              记录 AI 无法解决的问题，供后续导出、整理 SOP 和话术训练使用。
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground/70">渠道</label>
              <select
                value={createForm.channel}
                onChange={(e) => setCreateForm((prev) => ({ ...prev, channel: e.target.value }))}
                className="mt-1 w-full h-9 text-sm rounded-lg border border-border bg-background px-2"
              >
                <option value="app_h5">APP H5</option>
                <option value="pdd">拼多多</option>
                <option value="other">其他</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground/70">问题类型</label>
              <Input
                className="mt-1"
                placeholder="离线 / 画面异常 / 退换货 / 投诉"
                value={createForm.issue_type}
                onChange={(e) => setCreateForm((prev) => ({ ...prev, issue_type: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground/70">用户原话</label>
            <Textarea
              className="mt-1"
              placeholder="粘贴用户的真实问题描述"
              value={createForm.user_question}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, user_question: e.target.value }))}
              rows={3}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground/70">AI 已排查步骤</label>
            <Textarea
              className="mt-1"
              placeholder="每行一个步骤，例如：&#10;询问指示灯颜色&#10;让用户检查电源插头&#10;确认 App 显示离线"
              value={createForm.checked_steps}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, checked_steps: e.target.value }))}
              rows={3}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground/70">未解决原因</label>
            <Textarea
              className="mt-1"
              placeholder="例如：知识库未覆盖 / 用户拒绝继续排查 / 涉及退款政策 / 需要人工判断"
              value={createForm.unresolved_reason}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, unresolved_reason: e.target.value }))}
              rows={2}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground/70">AI 回复，可选</label>
            <Textarea
              className="mt-1"
              placeholder="如果有 AI 最后一轮回复，可以粘贴在这里"
              value={createForm.ai_reply}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, ai_reply: e.target.value }))}
              rows={2}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>取消</Button>
            <Button onClick={handleCreateEntry} disabled={createLoading}>
              {createLoading ? "记录中..." : "写入表格"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Note dialog */}
      <Dialog open={!!selected} onOpenChange={(o) => { if (!o) setSelected(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑备注</DialogTitle>
            <DialogDescription>
              问题：{selected?.user_question}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="记录维护备注、分析结论或处理方案..."
            value={noteInput}
            onChange={(e) => setNoteInput(e.target.value)}
            rows={4}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelected(null)}>取消</Button>
            <Button onClick={handleSaveNote} disabled={saving}>
              {saving ? "保存中..." : "保存备注"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Import trained knowledge dialog */}
      <Dialog open={importDialogOpen} onOpenChange={(o) => { if (!o) { setImportDialogOpen(false); setImportResult(null); } }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>导入训练后话术</DialogTitle>
            <DialogDescription>
              选择话术训练系统导出的文件（JSON/CSV/TXT/MD），系统将自动解析并写入知识库草稿。
            </DialogDescription>
          </DialogHeader>

          {!importResult ? (
            <>
              <div className="border-2 border-dashed border-border rounded-lg p-6 text-center"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const file = e.dataTransfer.files[0];
                  if (file) setImportFile(file);
                }}>
                <Upload className="w-8 h-8 mx-auto mb-2 text-muted-foreground/20" />
                <p className="text-sm text-muted-foreground/70 mb-1">
                  {importFile ? importFile.name : "拖拽文件到此处，或点击选择"}
                </p>
                <p className="text-xs text-muted-foreground/50 mb-3">
                  支持 JSON / CSV / TXT / MD，最大 10MB
                </p>
                <Input
                  type="file"
                  accept=".json,.csv,.txt,.md"
                  onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                  className="max-w-xs mx-auto"
                />
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setImportDialogOpen(false)}>取消</Button>
                <Button onClick={handleImport} disabled={!importFile || importLoading}>
                  {importLoading ? "导入中..." : "开始导入"}
                </Button>
              </DialogFooter>
            </>
          ) : (
            <div className="text-center py-4">
              <CheckCircle className="w-12 h-12 mx-auto mb-2 text-green-500" />
              <p className="text-lg font-medium text-green-700">导入成功</p>
              <p className="text-sm text-muted-foreground/70 mt-1">
                共导入 {importResult.imported} 条知识，状态为“待审核”
              </p>
              <Button variant="outline" className="mt-4" onClick={() => { setImportDialogOpen(false); setImportResult(null); }}>
                完成
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-4 right-4 z-50 px-4 py-2 rounded-lg shadow-lg text-sm text-white ${
          toast.type === "success" ? "bg-green-600" : "bg-red-600"
        }`}>
          {toast.message}
        </div>
      )}
    </Panel>
  );
}
