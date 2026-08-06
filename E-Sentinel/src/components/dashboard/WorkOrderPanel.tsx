"use client";

import { useState, useEffect, useCallback } from "react";
import Panel from "./Panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Clock, AlertTriangle, UserCheck } from "lucide-react";

const STATUS_LABELS: Record<string, string> = {
  open: "待处理", in_progress: "处理中", resolved: "已解决", closed: "已关闭",
};
const PRIORITY_LABELS: Record<string, string> = {
  low: "低", medium: "中", high: "高", critical: "紧急",
};
const PRIORITY_COLORS: Record<string, string> = {
  low: "bg-muted text-muted-foreground/70",
  medium: "bg-info/10 text-info border-info/20",
  high: "bg-warning/10 text-warning border-warning/20",
  critical: "bg-destructive/10 text-destructive border-destructive/20",
};
const STATUS_COLORS: Record<string, string> = {
  open: "bg-muted text-muted-foreground/70",
  in_progress: "bg-info/10 text-info border-info/20",
  resolved: "bg-success/10 text-success border-success/20",
  closed: "bg-border text-muted-foreground/50",
};
const CATEGORY_LABELS: Record<string, string> = {
  general: "通用", compliance: "合规", script_fix: "话术修复",
  knowledge_gap: "知识缺口", customer_complaint: "客户投诉", system_issue: "系统故障",
};
const DEFAULT_SLA_HOURS = 24;

interface WorkOrder {
  id: string;
  title: string;
  description: string;
  source: string;
  priority: string;
  status: string;
  category: string;
  assigned_to: string | null;
  assignee_name?: string | null;
  source_session_id?: string | null;
  sla_hours?: number | null;
  created_at: string;
  updated_at?: string;
  resolved_at: string | null;
}

function slaRemaining(createdAt: string, slaHours: number): { hours: number; urgent: boolean; expired: boolean } {
  const created = new Date(createdAt).getTime();
  const deadline = created + slaHours * 3600000;
  const remaining = (deadline - Date.now()) / 3600000;
  return {
    hours: Math.max(0, remaining),
    urgent: remaining > 0 && remaining <= 2,
    expired: remaining <= 0,
  };
}

function formatSla(createdAt: string, slaHours: number): string {
  const sla = slaRemaining(createdAt, slaHours);
  if (sla.expired) return "已超时";
  if (sla.hours < 1) return `${Math.round(sla.hours * 60)} 分钟`;
  return `${sla.hours.toFixed(1)} 小时`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function WorkOrderPanel() {
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [selectedOrder, setSelectedOrder] = useState<WorkOrder | null>(null);

  const fetchOrders = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams();
      if (filter) params.set("status", filter);
      const res = await fetch(`/api/qa/work-orders?${params.toString()}`);
      const data = await res.json();
      if (data.error) { setError(data.error); return; }
      setOrders(data.work_orders || []);
    } catch {
      setError("Failed to load work orders");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { void fetchOrders(); }, [fetchOrders]);

  async function updateStatus(id: string, status: string, resolution?: string) {
    try {
      const body: Record<string, string> = { status };
      if (status === "closed" && resolution) body.resolution = resolution;
      const res = await fetch(`/api/qa/work-orders/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.error) { setError(data.error); return; }
      fetchOrders();
    } catch {
      setError("Failed to update work order status");
    }
  }

  const openCount = orders.filter((o) => o.status === "open").length;
  const criticalCount = orders.filter((o) => o.priority === "critical" && o.status !== "closed").length;
  const overdueCount = orders.filter((o) => {
    if (o.status === "closed" || o.status === "resolved") return false;
    const sla = slaRemaining(o.created_at, o.sla_hours || DEFAULT_SLA_HOURS);
    return sla.expired;
  }).length;

  return (
    <Panel
      title="工单管理"
      subtitle={`待处理 ${openCount} · 紧急 ${criticalCount}${overdueCount > 0 ? ` · 超 SLA ${overdueCount}` : ""}`}
      loading={loading}
      error={error}
      onRetry={fetchOrders}
      empty={!loading && orders.length === 0}
      emptyTitle="暂无工单"
      emptyDescription="当质检发现严重问题或合规拦截触发时，将自动生成工单。"
    >
      {/* Summary cards — clickable to filter */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        {["open", "in_progress", "resolved", "closed"].map((s) => {
          const count = orders.filter((o) => o.status === s).length;
          return (
            <button
              key={s}
              type="button"
              onClick={() => setFilter(filter === s ? "" : s)}
              className={`bg-white border rounded-lg p-3 text-left transition-all hover:shadow-sm ${
                filter === s ? "ring-2 ring-primary/30 border-primary/50" : ""
              } ${s === "closed" ? "opacity-60" : ""}`}
            >
              <div className="text-xs text-muted-foreground/70">{STATUS_LABELS[s]}</div>
              <div className="text-2xl font-bold mt-0.5">{count}</div>
            </button>
          );
        })}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 mb-4">
        {["", "open", "in_progress", "resolved", "closed"].map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              filter === s ? "bg-foreground text-white" : "bg-muted text-muted-foreground hover:bg-border"
            }`}
          >
            {s ? STATUS_LABELS[s] : "全部"}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground/50 self-center">{orders.length} 条工单</span>
      </div>

      {/* Orders table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-muted/50 border-b">
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">工单</th>
              <th className="text-left px-3 py-3 font-medium text-muted-foreground w-16">优先级</th>
              <th className="text-left px-3 py-3 font-medium text-muted-foreground w-16">分类</th>
              <th className="text-left px-3 py-3 font-medium text-muted-foreground w-16">负责人</th>
              <th className="text-left px-3 py-3 font-medium text-muted-foreground w-20">SLA</th>
              <th className="text-left px-3 py-3 font-medium text-muted-foreground w-16">状态</th>
              <th className="text-left px-3 py-3 font-medium text-muted-foreground w-28">更新时间</th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground w-40">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {orders.map((order) => {
              const sla = slaRemaining(order.created_at, order.sla_hours || DEFAULT_SLA_HOURS);
              const isClosed = order.status === "closed";
              const isUrgent = order.priority === "critical" && order.status !== "closed" && order.status !== "resolved";
              const isOverdue = sla.expired && order.status !== "closed" && order.status !== "resolved";
              return (
                <tr
                  key={order.id}
                  className={`hover:bg-muted/50 transition-colors ${
                    isClosed ? "opacity-50" : ""
                  } ${
                    isUrgent || isOverdue ? "bg-destructive/5" : ""
                  }`}
                >
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => setSelectedOrder(order)}
                      className={`text-left font-medium hover:text-primary hover:underline underline-offset-2 ${isClosed ? "text-muted-foreground/70" : ""}`}
                    >
                      {order.title}
                    </button>
                    <div className="text-xs text-muted-foreground/50 mt-0.5 line-clamp-1">{order.description}</div>
                  </td>
                  <td className="px-3 py-3">
                    <Badge className={PRIORITY_COLORS[order.priority]}>{PRIORITY_LABELS[order.priority] || order.priority}</Badge>
                  </td>
                  <td className="px-3 py-3 text-xs text-muted-foreground/70">
                    {CATEGORY_LABELS[order.category] || order.category}
                  </td>
                  <td className="px-3 py-3 text-xs text-muted-foreground/70">
                    {order.assignee_name ? (
                      <span className="inline-flex items-center gap-1">
                        <UserCheck className="w-3 h-3" strokeWidth={2} />
                        {order.assignee_name}
                      </span>
                    ) : (
                      <span className="text-muted-foreground/40">未分配</span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <span className={`inline-flex items-center gap-1 text-xs font-mono ${
                      sla.expired ? "text-destructive font-semibold" :
                      sla.urgent ? "text-warning font-semibold" :
                      "text-muted-foreground/70"
                    }`}>
                      {sla.expired || sla.urgent ? (
                        <AlertTriangle className="w-3 h-3" strokeWidth={2.5} />
                      ) : (
                        <Clock className="w-3 h-3" strokeWidth={1.5} />
                      )}
                      {formatSla(order.created_at, order.sla_hours || DEFAULT_SLA_HOURS)}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <Badge className={STATUS_COLORS[order.status]}>{STATUS_LABELS[order.status] || order.status}</Badge>
                  </td>
                  <td className="px-3 py-3 text-xs text-muted-foreground/50">
                    {formatTime(order.updated_at || order.created_at)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      {order.status === "open" && (
                        <Button size="sm" onClick={() => updateStatus(order.id, "in_progress")} className="text-xs h-7">
                          接单
                        </Button>
                      )}
                      {order.status === "in_progress" && (
                        <>
                          <Button size="sm" variant="secondary" onClick={() => updateStatus(order.id, "resolved")} className="text-xs h-7">
                            解决
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => updateStatus(order.id, "open")} className="text-xs h-7">
                            退回
                          </Button>
                        </>
                      )}
                      {order.status === "resolved" && (
                        <>
                          <Button size="sm" variant="secondary" onClick={() => updateStatus(order.id, "closed", "问题已解决并验证")} className="text-xs h-7">
                            关闭
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => updateStatus(order.id, "in_progress")} className="text-xs h-7">
                            重开
                          </Button>
                        </>
                      )}
                      {order.status === "closed" && (
                        <Button size="sm" variant="ghost" onClick={() => updateStatus(order.id, "in_progress")} className="text-xs h-7 text-muted-foreground/50">
                          重开
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      </div>

      <Sheet open={selectedOrder !== null} onOpenChange={(open) => { if (!open) setSelectedOrder(null); }}>
        <SheetContent side="right" className="w-full sm:max-w-xl overflow-y-auto">
          {selectedOrder && (
            <>
              <SheetHeader>
                <div className="flex items-center gap-2">
                  <Badge className={PRIORITY_COLORS[selectedOrder.priority]}>
                    {PRIORITY_LABELS[selectedOrder.priority] || selectedOrder.priority}
                  </Badge>
                  <Badge className={STATUS_COLORS[selectedOrder.status]}>
                    {STATUS_LABELS[selectedOrder.status] || selectedOrder.status}
                  </Badge>
                </div>
                <SheetTitle>{selectedOrder.title}</SheetTitle>
                <SheetDescription>工单详情与处置证据</SheetDescription>
              </SheetHeader>

              <dl className="mt-6 grid grid-cols-2 gap-x-5 gap-y-4 text-sm">
                <div>
                  <dt className="text-xs text-muted-foreground">负责人</dt>
                  <dd className="mt-1 font-medium">{selectedOrder.assignee_name || "未分配"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">分类</dt>
                  <dd className="mt-1 font-medium">{CATEGORY_LABELS[selectedOrder.category] || selectedOrder.category}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">SLA</dt>
                  <dd className="mt-1 font-medium">{formatSla(selectedOrder.created_at, selectedOrder.sla_hours || DEFAULT_SLA_HOURS)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">来源</dt>
                  <dd className="mt-1 font-medium">{selectedOrder.source || "—"}</dd>
                </div>
              </dl>

              <section className="mt-6 rounded-lg border border-border bg-muted/30 p-4">
                <h3 className="text-sm font-semibold">证据与问题描述</h3>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{selectedOrder.description || "暂无补充证据"}</p>
              </section>
            </>
          )}
        </SheetContent>
      </Sheet>
    </Panel>
  );
}
