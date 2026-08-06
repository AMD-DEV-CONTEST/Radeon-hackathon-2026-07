/**
 * 冻结门槛测试（ADR-0003 第 4 层扩展）：
 *   1. policy_finding_requires_retrieval        — 退款/承诺类 finding 强制检索
 *   2. product_claim_requires_knowledge_tool    — 产品事实类 finding 强制检索
 *   3. hard_redline_does_not_require_fake_retrieval — 硬红线不做无意义 RAG
 *   4. missing_source_requires_human_review     — 空检索/无来源必须人工复核
 *   5. tool_failure_cannot_downgrade_baseline   — 工具失败/检索不可用不得降级风险
 *   6. agent_output_has_no_final_risk_authority — Agent 无 finalRisk 写权限
 *   7. dual_and_agent_share_same_baseline_snapshot — 共享基线快照下两档风险一致
 *
 * 契约：deriveRequiredTools / deriveRetrievalQuery / validateAgentEscalation /
 * resolveFinalRisk / computeRequiresHumanReview 全部纯函数，可独立复算。
 */
import {
  deriveRequiredTools,
  deriveRetrievalQuery,
  classifyFindingType,
} from "../agent/investigation-policy";
import {
  resolveFinalRisk,
  validateAgentEscalation,
  computeRequiresHumanReview,
} from "../qa/evaluate-core";
import type { AgentEvidence } from "../agent/types";

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

describe("冻结门槛：调查策略与工具契约", () => {
  it("policy_finding_requires_retrieval", () => {
    // 退款/承诺类 finding → 必须强制 retrieve_knowledge
    const tools = deriveRequiredTools({
      baselineViolations: [
        { category: "专业性", rule: "禁止虚假承诺", finding_type: "false_commitment" },
      ],
      softSignals: [],
      hardRedlineHit: false,
    });
    expect(tools).toContain("retrieve_knowledge");

    const refund = deriveRequiredTools({
      baselineViolations: [{ category: "专业性", rule: "退款政策违规", finding_type: "refund_policy" }],
      softSignals: [],
      hardRedlineHit: false,
    });
    expect(refund).toContain("retrieve_knowledge");
  });

  it("product_claim_requires_knowledge_tool", () => {
    const tools = deriveRequiredTools({
      baselineViolations: [{ category: "专业性", rule: "产品信息不实", finding_type: "product_accuracy" }],
      softSignals: [],
      hardRedlineHit: false,
    });
    expect(tools).toContain("retrieve_knowledge");
    // product_accuracy → 检索意图 product_qa，query 带型号
    expect(deriveRetrievalQuery(["product_accuracy"], "客服：Gemini 335 深度范围 0.1-20m")).toMatch(/Gemini 335/);
    expect(deriveRetrievalQuery(["product_accuracy"], "客服：Gemini 335 深度范围")).toMatch(/产品规格参数/);
  });

  it("hard_redline_does_not_require_fake_retrieval", () => {
    // 硬红线命中（如索要验证码/威胁）→ 确定性层直接处置，不做无意义的 RAG
    const tools = deriveRequiredTools({
      baselineViolations: [
        { category: "合规与隐私", rule: "索要验证码", finding_type: "privacy_request" },
      ],
      softSignals: [],
      hardRedlineHit: true,
    });
    expect(tools).toEqual([]);
    // 隐私/威胁类 finding 即使无硬红线命中也不需要检索（语义上不依赖知识库）
    const noHard = deriveRequiredTools({
      baselineViolations: [{ category: "合规与隐私", rule: "索要验证码", finding_type: "privacy_request" }],
      softSignals: [],
      hardRedlineHit: false,
    });
    expect(noHard).toEqual([]);
  });

  it("missing_source_requires_human_review", () => {
    // 无来源（insufficient/unavailable）→ 必须人工复核，且不得当作"没有违规"
    expect(
      computeRequiresHumanReview({ hardRedlineHit: false, riskLevel: "low", softRequiresReview: false, knowledgeStatus: "insufficient" })
    ).toBe(true);
    expect(
      computeRequiresHumanReview({ hardRedlineHit: false, riskLevel: "low", softRequiresReview: false, knowledgeStatus: "unavailable" })
    ).toBe(true);
    // 有来源（ok）且低风险 → 不强制人工复核
    expect(
      computeRequiresHumanReview({ hardRedlineHit: false, riskLevel: "low", softRequiresReview: false, knowledgeStatus: "ok" })
    ).toBe(false);
  });

  it("tool_failure_cannot_downgrade_baseline", () => {
    // 工具失败（检索 unavailable）不影响最终风险：baseline high 保持 high
    const withToolFailure = resolveFinalRisk({ hardFloor: "low", semanticBaseline: "high" });
    expect(withToolFailure).toBe("high");
    // 工具失败产生的 knowledgeStatus 只触发人工复核，不改变 risk
    expect(
      computeRequiresHumanReview({ hardRedlineHit: false, riskLevel: "high", softRequiresReview: false, knowledgeStatus: "unavailable" })
    ).toBe(true);
    // 检索不可用时 Agent 无法提供升级证据 → 升级被忽略，基线保持
    const failedEvidence: AgentEvidence = { ...baseEvidence(), knowledgeStatus: "unavailable", proposedEscalation: "critical" };
    expect(validateAgentEscalation(failedEvidence)).toBeUndefined();
    expect(resolveFinalRisk({ hardFloor: "low", semanticBaseline: "medium", agentEscalation: validateAgentEscalation(failedEvidence) })).toBe("medium");
  });

  it("agent_output_has_no_final_risk_authority", () => {
    // 架构不变量：resolveFinalRisk 没有接收"Agent 降级值"的通道。
    // Agent 的 proposedEscalation 只接受 high/critical 且必须附客服侧违规原句。
    expect(validateAgentEscalation({ ...baseEvidence(), proposedEscalation: "medium" as never })).toBeUndefined();
    expect(validateAgentEscalation({ ...baseEvidence(), proposedEscalation: "low" as never })).toBeUndefined();
    expect(validateAgentEscalation({ ...baseEvidence(), proposedEscalation: "high" })).toBeUndefined(); // 无证据
    // 即便 Agent 声称"降级"，最终风险仍取 max(硬红线, 基线, 升级)
    expect(resolveFinalRisk({ hardFloor: "low", semanticBaseline: "critical" })).toBe("critical");
    expect(resolveFinalRisk({ hardFloor: "high", semanticBaseline: "low" })).toBe("high");
  });

  it("dual_and_agent_share_same_baseline_snapshot", () => {
    // 配对消融核心不变量：给定同一 baseline snapshot，Dual（无 Agent）与
    // Agent（无有效升级）必须产出完全相同的最终风险 —— 差异只能来自工具层。
    const snapshot = { risk_level: "high", violations: [{ finding_type: "refund_policy" }] };
    const hardFloor: "high" | "low" | "medium" | "critical" = "low";
    const dualRisk = resolveFinalRisk({ hardFloor, semanticBaseline: snapshot.risk_level as "high" });
    // Agent 跑了调查但无有效升级 → 与 Dual 相同
    const agentRanNoEscalation = resolveFinalRisk({
      hardFloor,
      semanticBaseline: snapshot.risk_level as "high",
      agentEscalation: validateAgentEscalation({ ...baseEvidence(), policyFindings: [{ rule: "退款政策", matched: "x", citation: "kb-1" }] }),
    });
    expect(agentRanNoEscalation).toBe(dualRisk);
    // 只有 Agent 凭客服侧违规原句升级时才可能高于 Dual
    const escalated = resolveFinalRisk({
      hardFloor,
      semanticBaseline: snapshot.risk_level as "high",
      agentEscalation: validateAgentEscalation({ ...baseEvidence(), proposedEscalation: "critical", escalationEvidence: ["客服：今天肯定到账"] }),
    });
    expect(escalated === "critical").toBe(true);
    // 升级后风险 ≥ Dual（用风险序而非字母序比较）
    const order: Record<string, number> = { low: 0, medium: 1, high: 2, critical: 3 };
    expect(order[escalated]).toBeGreaterThanOrEqual(order[dualRisk]);
  });

  it("classifyFindingType 兜底推断", () => {
    expect(classifyFindingType("专业性", "禁止承诺无法兑现的事项")).toBe("false_commitment");
    expect(classifyFindingType("专业性", "退款政策引用错误")).toBe("refund_policy");
    expect(classifyFindingType("专业性", "提供错误的产品价格")).toBe("product_accuracy");
    expect(classifyFindingType("合规与隐私", "索要验证码")).toBe("privacy_request");
    expect(classifyFindingType("服务态度", "推诿敷衍")).toBe("service_attitude");
  });

  it("escalation_evidence_must_be_grounded_in_conversation (W6)", () => {
    // 传入对话上下文时，升级证据必须是对话原文的连续片段（≥8 字符）；
    // 模型编造的 quote 不得背书升级。
    const conversation = "客服：您好。\n客户：这个坏了我要退款。\n客服：抱歉，今天肯定给您到账的。";
    const grounded = { ...baseEvidence(), proposedEscalation: "high" as const, escalationEvidence: ["今天肯定给您到账的"] };
    expect(validateAgentEscalation(grounded, conversation)).toBe("high");
    // 编造 quote 不在原文中 → 升级被拒
    const fabricated = { ...baseEvidence(), proposedEscalation: "high" as const, escalationEvidence: ["我们绝不赔付任何损失"] };
    expect(validateAgentEscalation(fabricated, conversation)).toBeUndefined();
    // 短于 8 字符的引用不背书升级
    const tooShort = { ...baseEvidence(), proposedEscalation: "high" as const, escalationEvidence: ["到账"] };
    expect(validateAgentEscalation(tooShort, conversation)).toBeUndefined();
    // 不传 conversation 时保持向后兼容（非空数组即可）
    expect(validateAgentEscalation(grounded)).toBe("high");
  });
});
