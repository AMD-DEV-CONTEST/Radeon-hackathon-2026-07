// Guardian Center（节点⑤真实数据接线）
// 数据源：GET /api/guardian/pending → { pending:[...] }
// 动作：POST /api/guardian/approve → { ticket_id, human_ok, reason }
// 原版 4 条硬编码假审批已删除；当前后端 pending=[] → 真实空态（系统安全）

import { useEffect, useState } from "react";
import { Shield, ShieldCheck, Loader2, RefreshCw, Check, X } from "lucide-react";
import { fetchGuardianPending, guardianApprove, type GuardianTicket } from "./lib/api";
import { ErrorBanner, Skeleton } from "./_ui";

// 审批类型 → 中文标签（覆盖 grok_write / delete_file / run_command / network / rm_rf / general）
const TYPE_LABEL: Record<string, string> = {
  grok_write: "Grok 写操作",
  delete_file: "删除文件",
  run_command: "执行命令",
  network: "联网请求",
  rm_rf: "强制删除",
  general: "通用操作",
};

export default function GuardianCenter() {
  const [tickets, setTickets] = useState<GuardianTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [acting, setActing] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError("");
    fetchGuardianPending().then(setTickets).catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const act = async (t: GuardianTicket, ok: boolean) => {
    const id = t.ticket_id || t.id || "";
    if (!id) return;
    setActing(id);
    try {
      await guardianApprove(id, ok, ok ? "前端批准" : "前端拒绝");
      setTickets((prev) => prev.filter((x) => (x.ticket_id || x.id) !== id));
    } catch (e: any) {
      setError(e?.message || "操作失败");
    } finally {
      setActing(null);
    }
  };

  const riskClass = (r?: string) =>
    r === "P0" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300"
    : r === "P1" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
    : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300";

  // 风险等级优先取后端 level_name（P0/P1/P2），兜底 risk
  const riskOf = (t: GuardianTicket) => t.level_name || t.risk || "P?";
  const typeLabel = (t: GuardianTicket) => TYPE_LABEL[t.type || ""] || t.type || "操作";
  const actionText = (t: GuardianTicket) => t.detail || t.action || t.summary || (t.id || "");

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      <div className="flex items-center gap-2 mb-1">
        <Shield size={18} />
        <h2 className="text-lg font-semibold">Guardian Center</h2>
        <button onClick={load} title="刷新" className="ml-auto p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <p className="text-xs text-zinc-400 mb-6">AI 安全驾驶舱 · 危险操作审批 · 数据来自 /api/guardian/pending</p>

      {loading && <Skeleton lines={3} />}
      {error && <ErrorBanner message={error} onRetry={load} />}

      {!loading && tickets.length === 0 && !error && (
        <div className="flex flex-col items-center gap-3 py-16 text-zinc-400">
          <ShieldCheck size={30} strokeWidth={1.2} className="text-emerald-400" />
          <div className="text-sm">当前没有待审批的危险操作</div>
          <div className="text-[11px]">当 AI 触发高风险动作（删文件 / 执行命令 / 改配置）时会在这里等待你的批准</div>
        </div>
      )}

      <div className="space-y-3">
        {tickets.map((t, i) => {
          const id = t.ticket_id || t.id || String(i);
          return (
            <div key={id} className="bg-white dark:bg-zinc-900 rounded-xl p-4 border border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-3">
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${riskClass(riskOf(t))}`}>{riskOf(t)}</span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-300">{typeLabel(t)}</span>
                <span className="text-sm font-medium truncate">{actionText(t)}</span>
                <div className="ml-auto flex gap-2 shrink-0">
                  <button onClick={() => act(t, true)} disabled={acting === id}
                    className="flex items-center gap-1 px-3 py-1 bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 rounded text-xs hover:bg-emerald-200 disabled:opacity-50">
                    {acting === id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}批准
                  </button>
                  <button onClick={() => act(t, false)} disabled={acting === id}
                    className="flex items-center gap-1 px-3 py-1 bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-300 rounded text-xs hover:bg-red-100 disabled:opacity-50">
                    <X size={12} />拒绝
                  </button>
                </div>
              </div>
              {t.intent && <div className="mt-2 text-[11px] text-zinc-400">意图: <span className="font-mono">{t.intent}</span></div>}
              {t.reason && <div className="text-xs text-zinc-400">风险原因: {t.reason}</div>}
              {t.suggestion && <div className="text-xs text-zinc-400">建议: {t.suggestion}</div>}
            </div>
          );
        })}
      </div>
    </main>
  );
}
