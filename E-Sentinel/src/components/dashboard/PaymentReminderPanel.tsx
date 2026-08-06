"use client";

import { useState, useEffect, useCallback } from "react";
import Panel from "./Panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Send, Eye, PauseCircle } from "lucide-react";
import { formatCurrency, formatCompactPercent } from "@/lib/utils";

const STATUS_LABELS: Record<string, string> = {
  pending_payment: "待支付", reminded: "已提醒", paid: "已支付", cancelled: "已取消", expired: "已过期",
};
const STATUS_COLORS: Record<string, string> = {
  pending_payment: "bg-warning/10 text-warning border-warning/20",
  reminded: "bg-info/10 text-info border-info/20",
  paid: "bg-success/10 text-success border-success/20",
  cancelled: "bg-muted text-muted-foreground/70",
  expired: "bg-destructive/10 text-destructive border-destructive/20",
};

interface PendingOrder {
  id: string;
  external_order_id: string;
  customer_name: string | null;
  product_name: string | null;
  order_amount: number | null;
  order_status: string;
  created_at_order: string;
  expire_at: string | null;
  platform: { name: string } | null;
  reminders: Array<{ count: number }>;
}

export default function PaymentReminderPanel() {
  const [orders, setOrders] = useState<PendingOrder[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchOrders = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch("/api/qa/payment-reminders");
      const data = await res.json();
      if (data.error) { setError(data.error); return; }
      setOrders(data.orders || []);
      setCounts(data.counts || {});
    } catch {
      setError("Failed to load payment reminders");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  async function sendReminders(orderIds?: string[]) {
    try {
      setSending(true);
      const res = await fetch("/api/qa/payment-reminders", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(orderIds ? { order_ids: orderIds } : {}),
      });
      const data = await res.json();
      if (data.error) { setError(data.error); return; }
      fetchOrders();
    } catch {
      setError("Failed to send reminders");
    } finally {
      setSending(false);
    }
  }

  const totalPending = (counts.pending_payment || 0) + (counts.reminded || 0);
  const convertibleBase = (counts.pending_payment || 0) + (counts.reminded || 0) + (counts.paid || 0);
  const conversionRate = convertibleBase > 0
    ? formatCompactPercent((counts.paid || 0) / convertibleBase)
    : "—";

  return (
    <Panel
      title="智能催付"
      subtitle={`待催付 ${totalPending} 单 · 已转化 ${counts.paid || 0} 单 · 转化率 ${conversionRate}`}
      loading={loading}
      error={error}
      onRetry={fetchOrders}
      empty={!loading && orders.length === 0}
      emptyTitle="暂无待催付订单"
      emptyDescription="当系统接入订单数据后，待支付订单将在此展示并可自动催付。"
    >
      {/* Summary cards */}
      <div className="grid grid-cols-5 gap-3 mb-5">
        {["pending_payment", "reminded", "paid", "cancelled", "expired"].map((s) => (
          <div key={s} className="bg-white border rounded-lg p-3">
            <div className="text-xs text-muted-foreground/70">{STATUS_LABELS[s]}</div>
            <div className="text-2xl font-bold mt-0.5">{counts[s] || 0}</div>
          </div>
        ))}
      </div>

      {/* Action bar */}
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-muted-foreground/50">
          {orders.length > 0 ? `共 ${orders.length} 条订单` : ""}
        </span>
        <Button
          size="sm"
          onClick={() => sendReminders()}
          disabled={sending || totalPending === 0}
        >
          {sending ? "发送中..." : "一键催付"}
        </Button>
      </div>

      {/* Orders table */}
      <div className="bg-white border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/50 border-b">
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">订单号</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">客户</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">商品</th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground">金额</th>
              <th className="text-center px-4 py-3 font-medium text-muted-foreground">状态</th>
              <th className="text-center px-4 py-3 font-medium text-muted-foreground">提醒次数</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">下单时间</th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {orders.map((order) => (
              <tr key={order.id} className="hover:bg-muted/50">
                <td className="px-4 py-3 font-mono text-xs">{order.external_order_id}</td>
                <td className="px-4 py-3">{order.customer_name || "—"}</td>
                <td className="px-4 py-3 text-xs text-muted-foreground/70 max-w-32 truncate">
                  {order.product_name || "—"}
                </td>
                <td className="px-4 py-3 text-right font-mono text-xs">
                  {order.order_amount ? formatCurrency(order.order_amount) : "—"}
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge className={STATUS_COLORS[order.order_status]}>
                    {STATUS_LABELS[order.order_status]}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-center text-xs text-muted-foreground/70">
                  {Array.isArray(order.reminders) ? order.reminders.length : ((order.reminders as unknown as Array<{count: number}>)?.[0]?.count ?? 0)}
                </td>
                <td className="px-4 py-3 text-xs text-muted-foreground/70">
                  {new Date(order.created_at_order).toLocaleDateString("zh-CN")}
                </td>
                <td className="px-4 py-3 text-right">
                  {(order.order_status === "pending_payment" || order.order_status === "reminded") && (
                    <Button
                      size="sm"
                      variant="secondary"
                      className="text-xs"
                      onClick={() => sendReminders([order.id])}
                      disabled={sending}
                    >
                      催付
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
