"use client";

import { useState } from "react";
import { formatPercent, formatDateTime } from "@/lib/utils";
import Panel from "./Panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TrendingUp, Clock, ShieldCheck, Users } from "lucide-react";

interface ConfigCompare {
  config_key: string;
  pre_publish: Record<string, unknown> | null;
  post_publish: { total_sessions: number; good_rate: number; bad_rate: number } | null;
  effect_metrics?: Record<string, unknown> | null;
}

interface KnowledgeCompare {
  title: string;
  hits: number;
  gap_sources: number;
  last_hit: string | null;
  effect_metrics: Record<string, unknown> | null;
  update_log: Array<{ update_type: string; created_at: string }> | null;
}

// ── Static before/after comparison data ──────────────────────────────────────
const BEFORE_STATS = { coverage: "20%", accuracy: "72%", response: "2min", reviewed: "抽检" };
const AFTER_STATS = { coverage: "100%", accuracy: "91%", response: "<8s", reviewed: "全量" };

const IMPROVEMENTS = [
  {
    label: "质检覆盖率",
    before: "人工抽检 20%",
    after: "AI 全量 100%",
    icon: ShieldCheck,
  },
  {
    label: "评估准确率",
    before: "72%",
    after: "91%",
    icon: TrendingUp,
  },
  {
    label: "问题发现时效",
    before: "天级",
    after: "小时级",
    icon: Clock,
  },
  {
    label: "人工成本",
    before: "月均 160+ 小时",
    after: "月均节省 120 小时",
    icon: Users,
  },
];

// ── Component ────────────────────────────────────────────────────────────────
export default function EffectComparePanel() {
  const [idInput, setIdInput] = useState("");
  const [type, setType] = useState<"config" | "knowledge">("config");
  const [data, setData] = useState<ConfigCompare | KnowledgeCompare | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function fetchCompare() {
    if (!idInput.trim()) return;
    try {
      setLoading(true);
      setError(null);
      const param = type === "config" ? "config_id" : "knowledge_id";
      const res = await fetch(`/api/qa/effect-compare?${param}=${encodeURIComponent(idInput.trim())}`);
      const json = await res.json();
      if (json.error) {
        setError(json.error);
        setData(null);
        return;
      }
      setData(json);
    } catch {
      setError("Failed to load comparison data");
    } finally {
      setLoading(false);
    }
  }

  const isConfig = type === "config" && data && "config_key" in data;
  const isKnowledge = type === "knowledge" && data && "title" in data;

  return (
    <Panel
      title="效果对比"
      subtitle="AI 质检全量覆盖 vs 传统人工抽检 — 关键指标对比与改进跟踪"
      loading={loading}
      error={error}
      onRetry={fetchCompare}
    >
      {/* ════════════════════════════════════════════════════════════════════
          Section 1 — Static AI optimization before/after comparison
          ════════════════════════════════════════════════════════════════════ */}
      <section className="mb-6">
        <h3 className="text-sm font-semibold text-foreground mb-3">AI 质检优化效果</h3>

        {/* Two stat cards: Before vs After */}
        <div className="grid grid-cols-2 gap-4 mb-5">
          {/* Before (人工 QA) */}
          <div className="rounded-xl border border-border bg-muted/50 p-4 sm:p-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="inline-flex size-6 items-center justify-center rounded-md bg-border text-xs font-bold text-muted-foreground">
                前
              </span>
              <span className="text-xs font-medium text-muted-foreground/70">优化前 (人工 QA)</span>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground/70">覆盖率</span>
                <span className="text-sm font-semibold text-foreground/70">{BEFORE_STATS.coverage}</span>
              </div>
              <div className="h-px bg-border" />
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground/70">准确率</span>
                <span className="text-sm font-semibold text-foreground/70">{BEFORE_STATS.accuracy}</span>
              </div>
              <div className="h-px bg-border" />
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground/70">平均响应</span>
                <span className="text-sm font-semibold text-foreground/70">{BEFORE_STATS.response}</span>
              </div>
              <div className="h-px bg-border" />
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground/70">质检方式</span>
                <span className="text-sm font-semibold text-foreground/70">{BEFORE_STATS.reviewed}</span>
              </div>
            </div>
          </div>

          {/* After (AI QA) */}
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 sm:p-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="inline-flex size-6 items-center justify-center rounded-md bg-emerald-500 text-xs font-bold text-white">
                后
              </span>
              <span className="text-xs font-medium text-emerald-700">优化后 (AI QA)</span>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-emerald-700">覆盖率</span>
                <span className="text-sm font-semibold text-emerald-800">{AFTER_STATS.coverage}</span>
              </div>
              <div className="h-px bg-emerald-200" />
              <div className="flex items-center justify-between">
                <span className="text-xs text-emerald-700">准确率</span>
                <span className="text-sm font-semibold text-emerald-800">{AFTER_STATS.accuracy}</span>
              </div>
              <div className="h-px bg-emerald-200" />
              <div className="flex items-center justify-between">
                <span className="text-xs text-emerald-700">平均响应</span>
                <span className="text-sm font-semibold text-emerald-800">{AFTER_STATS.response}</span>
              </div>
              <div className="h-px bg-emerald-200" />
              <div className="flex items-center justify-between">
                <span className="text-xs text-emerald-700">质检方式</span>
                <span className="text-sm font-semibold text-emerald-800">{AFTER_STATS.reviewed}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Key improvements list */}
        <div className="rounded-xl border bg-white overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/50">
            <span className="text-xs font-semibold text-muted-foreground">关键改进点</span>
          </div>
          <div className="divide-y">
            {IMPROVEMENTS.map((item, i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-3">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                  <item.icon className="size-4" />
                </div>
                <div className="flex-1 min-w-0 flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground/70 shrink-0">{item.label}</span>
                  <span className="text-xs text-muted-foreground/50 shrink-0">:</span>
                  <span className="text-xs text-muted-foreground/70 line-through shrink-0">{item.before}</span>
                  <span className="text-xs text-muted-foreground/20 shrink-0">→</span>
                  <span className="text-xs font-medium text-emerald-600 truncate">{item.after}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════════════
          Section 2 — Detail query: per-config / per-knowledge comparison
          ════════════════════════════════════════════════════════════════════ */}
      <section className="border-t pt-5">
        <h3 className="text-sm font-semibold text-foreground mb-3">详情查询</h3>
        <p className="text-xs text-muted-foreground/50 mb-4">
          按话术配置或知识库条目查询发布前后的详细指标对比
        </p>

        {/* Search controls */}
        <div className="flex gap-2 mb-5">
          <div className="flex gap-1 bg-muted rounded-lg p-0.5">
            {(["config", "knowledge"] as const).map((t) => (
              <button
                key={t}
                onClick={() => {
                  setType(t);
                  setData(null);
                  setError(null);
                }}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  type === t
                    ? "bg-white text-foreground shadow-sm"
                    : "text-muted-foreground/70 hover:text-foreground/70"
                }`}
              >
                {t === "config" ? "话术配置" : "知识库"}
              </button>
            ))}
          </div>
          <Input
            placeholder={type === "config" ? "输入 config_id" : "输入 knowledge_id"}
            value={idInput}
            onChange={(e) => setIdInput(e.target.value)}
            className="flex-1 text-sm"
            onKeyDown={(e) => e.key === "Enter" && fetchCompare()}
          />
          <Button size="sm" onClick={fetchCompare}>
            查询
          </Button>
        </div>

        {/* Config comparison result */}
        {isConfig && (
          <div className="space-y-4">
            <div className="bg-white border rounded-lg p-4">
              <h3 className="font-medium text-sm text-foreground/70 mb-3">
                {(data as ConfigCompare).config_key}
              </h3>
              {(data as ConfigCompare).post_publish ? (
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-muted/50 rounded-lg p-3 text-center">
                    <div className="text-xs text-muted-foreground/70 mb-0.5">发布后会话数</div>
                    <div className="text-2xl font-bold">
                      {(data as ConfigCompare).post_publish!.total_sessions}
                    </div>
                  </div>
                  <div className="bg-green-50 rounded-lg p-3 text-center">
                    <div className="text-xs text-green-600 mb-0.5">好评率</div>
                    <div className="text-2xl font-bold text-green-700">
                      {formatPercent((data as ConfigCompare).post_publish!.good_rate)}
                    </div>
                  </div>
                  <div className="bg-red-50 rounded-lg p-3 text-center">
                    <div className="text-xs text-red-600 mb-0.5">差评率</div>
                    <div className="text-2xl font-bold text-red-700">
                      {formatPercent((data as ConfigCompare).post_publish!.bad_rate)}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground/50 py-4 text-center">
                  该配置尚未激活，无发布后数据
                </div>
              )}
            </div>

            {/* Pre-publish effect metrics */}
            {(data as ConfigCompare).pre_publish && (
              <div className="bg-white border rounded-lg p-4">
                <h3 className="font-medium text-sm text-foreground/70 mb-2">发布前基准指标</h3>
                <pre className="text-xs text-muted-foreground/70 bg-muted/50 rounded-lg p-3 overflow-auto max-h-48">
                  {JSON.stringify((data as ConfigCompare).pre_publish, null, 2)}
                </pre>
              </div>
            )}

            {(data as ConfigCompare).effect_metrics && (
              <div className="bg-white border rounded-lg p-4">
                <h3 className="font-medium text-sm text-foreground/70 mb-2">效果指标快照</h3>
                <pre className="text-xs text-muted-foreground/70 bg-muted/50 rounded-lg p-3 overflow-auto max-h-48">
                  {JSON.stringify((data as ConfigCompare).effect_metrics, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* Knowledge comparison result */}
        {isKnowledge && (
          <div className="space-y-4">
            <div className="bg-white border rounded-lg p-4">
              <h3 className="font-medium text-sm text-foreground/70 mb-3">
                {(data as KnowledgeCompare).title}
              </h3>
              <div className="grid grid-cols-3 gap-3 mb-3">
                <div className="bg-muted/50 rounded-lg p-3 text-center">
                  <div className="text-xs text-muted-foreground/70 mb-0.5">命中次数</div>
                  <div className="text-2xl font-bold">{(data as KnowledgeCompare).hits}</div>
                </div>
                <div className="bg-muted/50 rounded-lg p-3 text-center">
                  <div className="text-xs text-muted-foreground/70 mb-0.5">覆盖缺口</div>
                  <div className="text-2xl font-bold">{(data as KnowledgeCompare).gap_sources}</div>
                </div>
                <div className="bg-muted/50 rounded-lg p-3 text-center">
                  <div className="text-xs text-muted-foreground/70 mb-0.5">最后命中</div>
                  <div className="text-sm font-medium mt-1">
                    {formatDateTime((data as KnowledgeCompare).last_hit)}
                  </div>
                </div>
              </div>
              {(data as KnowledgeCompare).effect_metrics && (
                <div className="text-xs text-muted-foreground/70 bg-muted/50 rounded-lg p-3">
                  效果指标: {JSON.stringify((data as KnowledgeCompare).effect_metrics)}
                </div>
              )}
            </div>

            {/* Update log */}
            {(data as KnowledgeCompare).update_log &&
              (data as KnowledgeCompare).update_log!.length > 0 && (
                <div className="bg-white border rounded-lg overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-muted/50 border-b">
                        <th className="text-left px-4 py-2 font-medium text-muted-foreground">更新时间</th>
                        <th className="text-left px-4 py-2 font-medium text-muted-foreground">更新类型</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {(data as KnowledgeCompare).update_log!.map((log, i) => (
                        <tr key={i}>
                          <td className="px-4 py-2 text-xs text-muted-foreground/70">
                            {formatDateTime(log.created_at)}
                          </td>
                          <td className="px-4 py-2">
                            <Badge className="bg-muted text-foreground/70">
                              {log.update_type}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </div>
        )}

        {/* Query empty state (shown only when no query has been performed yet) */}
        {!data && !loading && !error && (
          <div className="text-center py-8 text-muted-foreground/50 border rounded-lg bg-white">
            <p className="text-3xl mb-2">&#x1F50D;</p>
            <p className="text-sm">输入 ID 查询指定条目发布前后的效果对比数据</p>
          </div>
        )}
      </section>
    </Panel>
  );
}
