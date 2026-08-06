"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import Panel from "@/components/dashboard/Panel";
import type { KnowledgeEntry } from "@/lib/types/bot";

export default function CampaignSyncPanel() {
  const [campaignEntries, setCampaignEntries] = useState<KnowledgeEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<string | null>(null);

  const fetchCampaigns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/qa/knowledge?category=campaign");
      if (res.ok) {
        const data = await res.json();
        setCampaignEntries(data.entries || []);
      } else {
        const errData = await res.json().catch(() => ({ error: "加载失败" }));
        setError(errData.error || "加载活动条目失败");
      }
    } catch {
      setError("网络请求失败，请检查后端服务");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchCampaigns();
  }, [fetchCampaigns]);

  const handleImport = async () => {
    setImporting(true);
    setImportResult(null);
    const res = await fetch("/api/qa/knowledge/batch-import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ campaign_doc: importText }),
    });
    if (res.ok) {
      const data = await res.json();
      setImportResult(`成功导入 ${data.entries?.length || 0} 条知识条目`);
      setImportText("");
      fetchCampaigns();
    } else {
      const err = await res.json();
      setImportResult(`导入失败: ${err.error || "未知错误"}`);
    }
    setImporting(false);
  };

  const isEmpty = !loading && !error && campaignEntries.length === 0;

  return (
    <Panel
      title="活动对接"
      subtitle="将活动方案、促销规则等文档自动提取为知识库条目"
      loading={loading}
      error={error}
      onRetry={fetchCampaigns}
      empty={isEmpty}
      emptyTitle="暂无活动知识条目"
      emptyDescription="点击「导入活动文档」，LLM 将自动提取产品信息、促销规则、FAQ 等结构化条目"
      emptyAction={{ label: "导入活动文档", onClick: () => setImportOpen(true) }}
      actions={
        <Button size="sm" onClick={() => setImportOpen(true)}>
          + 导入活动文档
        </Button>
      }
    >
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium flex items-center justify-between">
            <span>活动知识条目</span>
            <span className="text-xs text-muted-foreground/50 font-normal">{campaignEntries.length} 条</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>标题</TableHead>
                <TableHead>平台</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>优先级</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>更新时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {campaignEntries.map((e) => (
                <TableRow key={e.id} className="hover:bg-muted/50">
                  <TableCell className="font-medium text-sm max-w-[300px] truncate">
                    {e.title}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground/70">
                    {e.platform_id || "全局"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={
                      e.status === "published" ? "bg-emerald-100 text-emerald-700" :
                      e.status === "draft" ? "bg-yellow-100 text-yellow-700" :
                      "bg-muted text-muted-foreground/70"
                    }>
                      {e.status === "published" ? "已发布" : e.status === "draft" ? "草稿" : "已归档"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">{e.priority}</TableCell>
                  <TableCell className="text-xs text-muted-foreground/70">{e.source || "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground/70">
                    {e.updated_at ? new Date(e.updated_at).toLocaleDateString("zh-CN") : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Import Dialog */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>导入活动文档</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground/70">
              粘贴活动方案、促销规则等文档内容。LLM 将自动提取产品信息、促销规则、FAQ 等结构化知识条目。
            </p>
            <Textarea
              className="min-h-[200px]"
              placeholder="粘贴活动文档内容，例如：&#10;双十一活动方案&#10;活动时间：11月1日-11月11日&#10;满减规则：满300减50，满500减100&#10;参与平台：天猫、京东、抖音&#10;..."
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
            />
          </div>
          {importResult && (
            <p className={`text-xs ${importResult.includes("失败") ? "text-red-600" : "text-emerald-600"}`}>
              {importResult}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setImportOpen(false)}>取消</Button>
            <Button onClick={handleImport} disabled={!importText.trim() || importing}>
              {importing ? "LLM 提取中..." : "LLM 提取并导入"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}
