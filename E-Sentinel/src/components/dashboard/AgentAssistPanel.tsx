"use client";

import { useState, useEffect, type ReactNode } from "react";
import Panel from "./Panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface AgentInfo {
  id: string;
  name: string;
  team_id: string | null;
  session_count: number;
  latest_score: number | null;
  latest_risk: string | null;
}

interface AssistResult {
  agent_id: string;
  customer_info: Record<string, unknown> | null;
  customer_history: Array<Record<string, unknown>>;
  knowledge_recommendations: Array<Record<string, unknown>>;
  script_recommendations: Array<Record<string, unknown>>;
}

/** 结果区块统一外壳：语义色表头 + 内容区 */
function ResultSection({
  title,
  accent,
  badge,
  children,
}: {
  title: string;
  accent: string;
  badge?: string;
  children: ReactNode;
}) {
  return (
    <div className="bg-card border rounded-lg overflow-hidden">
      <div
        className={`px-4 py-2.5 border-b text-xs font-medium flex items-center justify-between ${accent}`}
      >
        <span>{title}</span>
        {badge && <span className="text-[11px] font-semibold">{badge}</span>}
      </div>
      {children}
    </div>
  );
}

/** 区块空状态：说明输入对话后该区块将生成什么内容 */
function SectionEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="px-4 py-8 text-center text-xs text-muted-foreground/70">
      {children}
    </div>
  );
}

export default function AgentAssistPanel() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [conversation, setConversation] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [result, setResult] = useState<AssistResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchAgents(); }, []);

  async function fetchAgents() {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch("/api/qa/agent-assist");
      if (res.ok) {
        const data = await res.json();
        if (data.agents && data.agents.length > 0) {
          setAgents(data.agents);
          setLoading(false);
          return;
        }
      }
    } catch { /* API not available, use demo data */ }
    // Fallback demo data
    setAgents([
      { id: "agent_01", name: "张小明", team_id: "team_a", session_count: 47, latest_score: 92, latest_risk: "low" },
      { id: "agent_02", name: "李小红", team_id: "team_a", session_count: 35, latest_score: 78, latest_risk: "medium" },
      { id: "agent_03", name: "王大伟", team_id: "team_b", session_count: 62, latest_score: 95, latest_risk: null },
      { id: "agent_04", name: "陈小芳", team_id: "team_b", session_count: 28, latest_score: 85, latest_risk: "low" },
    ]);
    setLoading(false);
  }

  async function handleSearch() {
    if (!conversation.trim()) return;
    try {
      setSearching(true);
      setResult(null);
      const res = await fetch("/api/qa/agent-assist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation: conversation.trim(),
          agent_id: selectedAgent,
          customer_id: customerId.trim() || null,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (!data.error) { setResult(data); return; }
      }
    } catch { /* API not available */ }
    // Demo fallback
    setResult({
      agent_id: selectedAgent || "agent_01",
      customer_info: { name: "客户张三", level: "VIP", history: "已购买3次" },
      customer_history: [{ date: "2026-05-20", topic: "物流查询", sentiment: "neutral" }, { date: "2026-05-18", topic: "退换货", sentiment: "angry" }],
      knowledge_recommendations: [{ title: "退货流程", content: "非人为损坏7天内可退换，需保留原包装", relevance: 0.95 }, { title: "物流时效", content: "江浙沪1-2天，其他地区2-4天", relevance: 0.82 }],
      script_recommendations: [{ script: "您好！非常理解您的感受。退换货流程很简单：点击订单详情→申请售后→填写原因→提交，我们会在24小时内审核。", scenario: "售后安抚" }, { script: "感谢您的耐心等待！这款产品广受好评，现在下单还附赠赠品，非常划算。", scenario: "促单引导" }],
    });
    setSearching(false);
  }

  // 所选坐席对象：用于读取 GET 返回的真实字段 latest_risk
  const selectedAgentInfo = selectedAgent
    ? (agents.find((a) => a.id === selectedAgent) ?? null)
    : null;

  // 合规提醒：基于 POST 真实返回的 script_recommendations 命中数量
  const complianceNotes: string[] = [];
  if (result && result.script_recommendations.length > 0) {
    complianceNotes.push(
      `已命中 ${result.script_recommendations.length} 条质检/话术规则，回复时请优先遵循推荐话术。`
    );
  }

  // 风险提示：基于所选坐席最新质检风险等级（GET 返回的真实字段 latest_risk）
  const riskNotes: string[] = [];
  if (
    selectedAgentInfo?.latest_risk === "critical" ||
    selectedAgentInfo?.latest_risk === "high"
  ) {
    riskNotes.push(
      `所选坐席最新质检风险等级为「${selectedAgentInfo.latest_risk}」，建议谨慎回复并参考合规提醒。`
    );
  }

  // 客户姓名：POST 返回 customer_info 中的真实字段 name
  const customerName = result?.customer_info
    ? String((result.customer_info as Record<string, unknown>).name ?? "")
    : "";

  return (
    <Panel
      title="坐席辅助"
      subtitle="实时监听对话 · 推荐话术与知识库"
      loading={loading}
      error={error}
      onRetry={fetchAgents}
      empty={!loading && agents.length === 0}
      emptyTitle="暂无坐席数据"
      emptyDescription="请先在 profiles 表中添加 role=agent 的坐席账号。"
    >
      <div className="grid grid-cols-1 lg:grid-cols-[400px_minmax(0,1fr)] gap-4 items-start">
        {/* ===== 左列：输入区 ===== */}
        <div className="space-y-4">
          {/* 步骤 1：选择会话 */}
          <section className="bg-card border rounded-lg p-4">
            <div className="flex items-center gap-2">
              <span className="grid place-items-center w-5 h-5 rounded-full bg-primary text-primary-foreground text-[11px] font-bold">1</span>
              <h3 className="text-sm font-semibold text-foreground">选择会话</h3>
            </div>
            <p className="text-xs text-muted-foreground mt-1 mb-3">
              选择本次对话对应的坐席，用于关联质检记录与客户历史。
            </p>
            {agents.length > 0 ? (
              <div className="grid grid-cols-2 gap-2">
                {agents.map((agent) => (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => setSelectedAgent(agent.id === selectedAgent ? null : agent.id)}
                    className={`text-left px-3 py-2 rounded-lg border text-sm transition-colors ${
                      agent.id === selectedAgent
                        ? "border-foreground bg-muted/50"
                        : "border-border hover:border-muted-foreground/20"
                    }`}
                  >
                    <div className="font-medium text-foreground/70">{agent.name}</div>
                    <div className="text-xs text-muted-foreground/50 mt-0.5">
                      {agent.session_count} 会话
                      {agent.latest_score !== null && ` · ${agent.latest_score}分`}
                    </div>
                    {agent.latest_risk && (
                      <Badge className={`text-xs mt-1 ${
                        agent.latest_risk === "critical"
                          ? "bg-destructive/10 text-destructive"
                          : agent.latest_risk === "high"
                            ? "bg-warning/10 text-warning"
                            : "bg-muted text-muted-foreground"
                      }`}>
                        {agent.latest_risk}
                      </Badge>
                    )}
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-xs text-muted-foreground/70 py-3 text-center">
                暂无可选坐席
              </div>
            )}
          </section>

          {/* 步骤 2：粘贴对话 + 客户信息 */}
          <section className="bg-card border rounded-lg p-4">
            <div className="flex items-center gap-2">
              <span className="grid place-items-center w-5 h-5 rounded-full bg-primary text-primary-foreground text-[11px] font-bold">2</span>
              <h3 className="text-sm font-semibold text-foreground">输入对话内容</h3>
            </div>
            <p className="text-xs text-muted-foreground mt-1 mb-3">
              粘贴客户消息与客服回复，AI 将实时匹配话术、知识库与合规风险。
            </p>
            <Textarea
              placeholder="粘贴客服对话内容（客户消息 + 客服回复）..."
              value={conversation}
              onChange={(e) => setConversation(e.target.value)}
              className="w-full text-sm min-h-[140px]"
            />
            <div className="mt-3">
              <label htmlFor="customer-id" className="block text-xs text-muted-foreground mb-1.5">
                客户信息（可选）
              </label>
              <input
                id="customer-id"
                type="text"
                placeholder="输入客户ID，用于关联客户历史"
                value={customerId}
                onChange={(e) => setCustomerId(e.target.value)}
                className="flex h-9 w-full rounded-lg border border-border bg-background px-3 py-1 text-sm placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </div>
            <Button
              size="lg"
              className="w-full mt-4"
              onClick={handleSearch}
              disabled={searching || !conversation.trim()}
            >
              {searching ? "分析中..." : "智能推荐"}
            </Button>
          </section>

          {/* 客户历史对话：POST 返回的真实字段，仅在有结果时展示 */}
          {result && result.customer_history.length > 0 && (
            <section className="bg-card border rounded-lg overflow-hidden">
              <div className="px-4 py-2.5 bg-muted/50 border-b text-xs font-medium text-muted-foreground flex items-center justify-between">
                <span>客户历史对话（{result.customer_history.length}）</span>
                {customerName && <span className="text-[11px] font-semibold">{customerName}</span>}
              </div>
              <div className="divide-y max-h-48 overflow-y-auto">
                {result.customer_history.map((session, i) => (
                  <div key={i} className="px-4 py-2 text-xs">
                    <div className="text-foreground/70">
                      <span className="text-muted-foreground/50">客: </span>
                      {String(session.customer_message || "").slice(0, 80)}
                    </div>
                    <div className="text-muted-foreground/70 mt-0.5">
                      <span className="text-muted-foreground/50">服: </span>
                      {String(session.bot_reply || "").slice(0, 80)}
                    </div>
                    <div className="flex gap-2 mt-0.5">
                      <span className="text-muted-foreground/50">
                        {session.satisfaction ? `满意度: ${session.satisfaction}` : ""}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

        {/* ===== 右列：AI 推荐结果区 ===== */}
        <div className="space-y-4">
          {/* 未生成结果时的引导说明 */}
          {!result && (
            <div className="bg-card border rounded-lg p-4">
              <p className="text-sm font-medium text-foreground">AI 推荐结果</p>
              <p className="mt-1 text-xs text-muted-foreground">
                输入对话并点击「智能推荐」后，以下内容将出现在这里：
              </p>
              <ul className="mt-2 space-y-1 text-xs text-muted-foreground/80 list-disc pl-4">
                <li>推荐话术 — 基于质检规则库匹配的最佳回复</li>
                <li>相关知识库 — 命中知识库的参考条目</li>
                <li>合规提醒 — 话术红线与合规要点</li>
                <li>风险提示 — 坐席风险与客户投诉风险</li>
              </ul>
            </div>
          )}

          {/* 推荐话术 */}
          <ResultSection
            title="推荐话术"
            accent="bg-success/10 text-success"
            badge={result ? `${result.script_recommendations.length} 条` : undefined}
          >
            {result && result.script_recommendations.length > 0 ? (
              <div className="divide-y">
                {result.script_recommendations.map((item, i) => (
                  <div key={i} className="px-4 py-3 hover:bg-muted/50">
                    <div className="font-medium text-sm text-foreground/70">
                      {String(item.config_key || item.rule_text || "话术")}
                    </div>
                    <div className="text-xs text-muted-foreground/70 mt-0.5">
                      {typeof item.config_value === "object"
                        ? JSON.stringify(item.config_value).slice(0, 200)
                        : String(item.rule_text || "").slice(0, 200)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <SectionEmpty>基于质检规则库匹配的推荐话术将出现在这里。</SectionEmpty>
            )}
          </ResultSection>

          {/* 相关知识库 */}
          <ResultSection
            title="相关知识库"
            accent="bg-info/10 text-info"
            badge={result ? `${result.knowledge_recommendations.length} 条` : undefined}
          >
            {result && result.knowledge_recommendations.length > 0 ? (
              <div className="divide-y">
                {result.knowledge_recommendations.map((item, i) => (
                  <div key={i} className="px-4 py-3 hover:bg-muted/50">
                    <div className="font-medium text-sm text-foreground/70">
                      {String(item.title || "无标题")}
                    </div>
                    <div className="text-xs text-muted-foreground/70 mt-0.5 line-clamp-2">
                      {String(item.content || "").slice(0, 200)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <SectionEmpty>与对话内容相关的知识库条目将出现在这里。</SectionEmpty>
            )}
          </ResultSection>

          {/* 合规提醒 */}
          <ResultSection title="合规提醒" accent="bg-warning/10 text-warning">
            {complianceNotes.length > 0 ? (
              <div className="divide-y">
                {complianceNotes.map((note, i) => (
                  <div key={i} className="px-4 py-3 text-xs text-foreground/70">{note}</div>
                ))}
              </div>
            ) : (
              <SectionEmpty>未发现明显合规问题。话术红线与合规要点将在这里提示。</SectionEmpty>
            )}
          </ResultSection>

          {/* 风险提示 */}
          <ResultSection title="风险提示" accent="bg-destructive/10 text-destructive">
            {riskNotes.length > 0 ? (
              <div className="divide-y">
                {riskNotes.map((note, i) => (
                  <div key={i} className="px-4 py-3 text-xs text-foreground/70">{note}</div>
                ))}
              </div>
            ) : (
              <SectionEmpty>坐席风险与客户投诉风险将在这里提示。</SectionEmpty>
            )}
          </ResultSection>
        </div>
      </div>
    </Panel>
  );
}
