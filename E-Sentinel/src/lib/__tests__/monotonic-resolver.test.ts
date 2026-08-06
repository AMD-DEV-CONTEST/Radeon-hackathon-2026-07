/**
 * ADR-0003 5 层架构不变量测试：
 *   1. Agent 不得降级语义基线（adjudicator 唯一）；
 *   2. Agent 不得降级硬红线下限；
 *   3. 空检索 ≠ 没有违规（insufficient → 人工复核，且不影响最终风险）；
 *   4. 检索服务不可用 → 人工复核；
 *   5. Agent 可凭有效证据升级；
 *   6. 软关键词不产生 high/critical 下限（修复 4 个关键词陷阱误报）；
 *   7. 硬红线保持 critical（即使语义基线误判 low）；
 *   8. 最终风险跨重复运行稳定（Agent 输出漂移不改变 final risk）。
 *
 * 关键设计：resolveFinalRisk 是纯函数且 Agent 无 finalRisk 写权限——
 * 架构上不存在"Agent 降级"的输入通道，这是测试 #1/#8 的根。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  resolveFinalRisk,
  validateAgentEscalation,
  computeRequiresHumanReview,
  applyCustomerIssueMediumFloor,
} from "../qa/evaluate-core";
import { scanHardRedlines, classifySoftSignals, floorFromHighestRisk, type RiskLevel } from "../compliance-engine";
import type { AgentEvidence } from "../agent/types";

const GOLD = JSON.parse(
  readFileSync(path.join(__dirname, "../../../evals/configs/gold-set-severe-draft-v1.json"), "utf8")
);

function conversationOf(id: string): string {
  const c = (GOLD.cases as Array<{ id: string; conversation: string }>).find((x) => x.id === id);
  if (!c) throw new Error(`gold case not found: ${id}`);
  return c.conversation;
}

function baseEvidence(): AgentEvidence {
  return {
    evidence: [],
    policyFindings: [],
    proposedEscalation: undefined,
    escalationEvidence: [],
    evidenceConflict: false,
    requiresHumanReview: false,
    knowledgeStatus: "ok",
  };
}

/** 模拟 Agent 调查员一次运行的证据输出（升级值可在各轮间漂移）。 */
function agentEvidence(esc?: string): AgentEvidence {
  const e = baseEvidence();
  if (esc === "high" || esc === "critical") {
    e.proposedEscalation = esc;
    e.escalationEvidence = ["对话原文证据"];
  }
  return e;
}

describe("ADR-0003 单调安全架构不变量", () => {
  it("agent_cannot_downgrade_semantic_baseline", () => {
    // 语义基线 high/critical，Agent 无升级时最终风险不变
    expect(resolveFinalRisk({ hardFloor: "low", semanticBaseline: "high" })).toBe("high");
    expect(resolveFinalRisk({ hardFloor: "low", semanticBaseline: "critical" })).toBe("critical");
    // Agent 提议升级值不在 {high,critical} 时被忽略 —— 不存在降级通道
    expect(validateAgentEscalation({ ...baseEvidence(), proposedEscalation: "medium" as never })).toBeUndefined();
    expect(validateAgentEscalation({ ...baseEvidence(), proposedEscalation: "low" as never })).toBeUndefined();
  });

  it("agent_cannot_downgrade_hard_rule_floor", () => {
    expect(resolveFinalRisk({ hardFloor: "critical", semanticBaseline: "low" })).toBe("critical");
    expect(resolveFinalRisk({ hardFloor: "high", semanticBaseline: "medium" })).toBe("high");
  });

  it("empty_retrieval_is_not_negative_evidence", () => {
    // 检索无结果 → insufficient → 人工复核；不能解释为"没有违规"
    expect(
      computeRequiresHumanReview({ hardRedlineHit: false, riskLevel: "low", softRequiresReview: false, knowledgeStatus: "insufficient" })
    ).toBe(true);
    // 空检索不影响最终风险：baseline medium 保持 medium（不会因"没找到证据"降级）
    expect(resolveFinalRisk({ hardFloor: "low", semanticBaseline: "medium" })).toBe("medium");
  });

  it("retrieval_failure_requires_human_review", () => {
    expect(
      computeRequiresHumanReview({ hardRedlineHit: false, riskLevel: "low", softRequiresReview: false, knowledgeStatus: "unavailable" })
    ).toBe(true);
  });

  it("agent_can_escalate_with_valid_evidence", () => {
    const withEvidence: AgentEvidence = {
      ...baseEvidence(),
      evidence: [{ type: "privacy", content: "请把验证码发给我", source: "redline-privacy-01" }],
      proposedEscalation: "critical",
      escalationEvidence: ["请把验证码发给我"],
      requiresHumanReview: true,
    };
    expect(validateAgentEscalation(withEvidence)).toBe("critical");
    expect(
      resolveFinalRisk({ hardFloor: "low", semanticBaseline: "medium", agentEscalation: validateAgentEscalation(withEvidence) })
    ).toBe("critical");
    // 无证据的升级被忽略
    const noEvidence: AgentEvidence = { ...baseEvidence(), proposedEscalation: "critical" };
    expect(validateAgentEscalation(noEvidence)).toBeUndefined();
  });

  it("agent_cannot_escalate_with_policy_findings_only_or_conflict", () => {
    // 仅有 policyFindings、无对话原文升级证据 → 不背书（检索到政策≠客服违规）
    const policyOnly: AgentEvidence = {
      ...baseEvidence(),
      policyFindings: [{ rule: "退款政策", matched: "3 个工作日内原路退回", citation: "kb-1" }],
      proposedEscalation: "high",
    };
    expect(validateAgentEscalation(policyOnly)).toBeUndefined();
    // 工具证据与基线冲突 → 不自动升级，留给人工复核
    const conflicting: AgentEvidence = {
      ...baseEvidence(),
      proposedEscalation: "high",
      escalationEvidence: ["已为您登记，审核通过后 3 个工作日内原路退回"],
      evidenceConflict: true,
    };
    expect(validateAgentEscalation(conflicting)).toBeUndefined();
  });

  it("soft_keyword_does_not_create_critical_floor", () => {
    // case-008：客户诉诸 12315，客服处理得当 → 软信号存在但不产生 critical 下限
    const soft = classifySoftSignals(conversationOf("case-008"));
    expect(soft.flags.some((f) => f.code === "legal_action_threat")).toBe(true);
    expect(floorFromHighestRisk(scanHardRedlines(conversationOf("case-008")).highest_risk)).toBe("low");
    expect(resolveFinalRisk({ hardFloor: "low", semanticBaseline: "medium" })).toBe("medium");
    // case-005：退款陷阱同理
    const soft5 = classifySoftSignals(conversationOf("case-005"));
    expect(soft5.flags.some((f) => f.code === "refund_dispute")).toBe(true);
    expect(floorFromHighestRisk(scanHardRedlines(conversationOf("case-005")).highest_risk)).toBe("low");
  });

  it("hard_redline_remains_critical", () => {
    // case-003 索要验证码+银行卡 → 隐私硬红线 critical
    expect(floorFromHighestRisk(scanHardRedlines(conversationOf("case-003")).highest_risk)).toBe("critical");
    // case-006 威胁拉黑 → critical
    expect(floorFromHighestRisk(scanHardRedlines(conversationOf("case-006")).highest_risk)).toBe("critical");
    // case-012 广告法绝对化用语 → critical
    expect(floorFromHighestRisk(scanHardRedlines(conversationOf("case-012")).highest_risk)).toBe("critical");
    // 即使语义基线误判 low，最终也 critical
    expect(resolveFinalRisk({ hardFloor: "critical", semanticBaseline: "low" })).toBe("critical");
  });

  it("final_risk_is_stable_across_repeated_agent_runs", () => {
    // 模拟 agent 调查员 6 次运行：升级提议在 critical/high/undefined 间漂移。
    // 硬红线 critical 的严重案例，最终风险必须每次都保持 critical（Agent 无降级通道）。
    const hardFloor: RiskLevel = "critical";
    const escalations = ["critical", "high", undefined, "critical", "medium", undefined];
    const results = escalations.map((e) =>
      resolveFinalRisk({ hardFloor, semanticBaseline: "critical", agentEscalation: validateAgentEscalation(agentEvidence(e)) })
    );
    expect(results.every((r) => r === "critical")).toBe(true);

    // 语义严重案例（baseline high）：Agent 可凭证据升级到 critical，但绝不能降回 non-severe。
    // 稳定性指标 = 最终严重度一致（≥ high），而非逐字一致。
    const results2 = escalations.map((e) =>
      resolveFinalRisk({ hardFloor: "low", semanticBaseline: "high", agentEscalation: validateAgentEscalation(agentEvidence(e)) })
    );
    expect(results2.every((r) => r === "high" || r === "critical")).toBe(true);
  });

  it("gold-set 确定性层对齐：4 个关键词陷阱无硬红线、软信号不升严重", () => {
    for (const id of ["case-005", "case-008", "case-011", "case-015"]) {
      const hard = scanHardRedlines(conversationOf(id));
      expect(floorFromHighestRisk(hard.highest_risk)).toBe("low");
      // 软信号可存在，但 baseline=medium 时最终保持 medium（不升 severe）
      expect(resolveFinalRisk({ hardFloor: "low", semanticBaseline: "medium" })).toBe("medium");
    }
  });

  it("customer_issue_medium_floor_only_raises_low_to_medium", () => {
    // 退款/投诉/物流等中高风险客户诉求：客服处理得当 → low 升 medium（非 severe）
    expect(applyCustomerIssueMediumFloor("low", ["refund_dispute"])).toBe("medium");
    expect(applyCustomerIssueMediumFloor("low", ["legal_action_threat", "logistics_delay"])).toBe("medium");
    // 已有 medium/high/critical 时保持不变（只升不降）
    expect(applyCustomerIssueMediumFloor("medium", ["refund_dispute"])).toBe("medium");
    expect(applyCustomerIssueMediumFloor("high", ["refund_dispute"])).toBe("high");
    // 纯情绪信号不触发中风险下限
    expect(applyCustomerIssueMediumFloor("low", ["emotional_intensifier"])).toBe("low");
    expect(applyCustomerIssueMediumFloor("low", [])).toBe("low");
  });
});
