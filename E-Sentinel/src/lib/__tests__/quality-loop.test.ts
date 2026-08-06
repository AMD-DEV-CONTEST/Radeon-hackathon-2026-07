jest.mock("@/lib/supabase", () => ({ supabaseAdmin: null }));

import {
  isUuid,
  persistQualityEvaluation,
  qualityDecision,
  qualityEvidenceRefs,
  recordQualityOverturn,
} from "@/lib/governance/quality-loop";
import { requiresHumanApprovalForTopic } from "@/lib/adapters/reply-orchestrator";

describe("quality governance loop", () => {
  it("keeps shadow evaluations in review even when the score is high", () => {
    expect(qualityDecision("low", "shadow")).toBe("review");
    expect(qualityDecision("low", "active")).toBe("pass");
    expect(qualityDecision("high", "active")).toBe("review");
    expect(qualityDecision("critical", "active")).toBe("block");
  });

  it("turns model quotes into bounded evidence references", () => {
    const refs = qualityEvidenceRefs([
      { category: "合规", rule: "不得承诺退款", source_quote: "请提供完整银行卡号" },
      { category: "服务", rule: "使用敬语", source_quote: "" },
    ]);

    expect(refs).toEqual([
      {
        type: "conversation_quote",
        category: "合规",
        rule: "不得承诺退款",
        quote: "请提供完整银行卡号",
      },
    ]);
  });

  it("validates UUID approvers without accepting arbitrary identifiers", () => {
    expect(isUuid("00000000-0000-4000-8000-000000000001")).toBe(true);
    expect(isUuid("operator-1")).toBe(false);
    expect(isUuid(null)).toBe(false);
  });

  it("requires human approval for sensitive customer topics", () => {
    expect(requiresHumanApprovalForTopic("我要求退款并投诉到12315")).toBe(true);
    expect(requiresHumanApprovalForTopic("请问这款商品什么时候发货")).toBe(false);
  });

  it("degrades when governance storage is unavailable", async () => {
    await expect(persistQualityEvaluation({
      reportId: "report-1",
      tenantId: "default",
      ticketId: "ticket-1",
      correlationId: "corr-1",
      conversationLength: 42,
      intent: "物流咨询",
      sentimentScore: 2,
      totalScore: 92,
      riskLevel: "low",
      violations: [],
      reviewMode: "active",
    })).resolves.toEqual({
      evaluationId: null,
      findingIds: [],
      workItemIds: [],
      persisted: false,
    });

    await expect(recordQualityOverturn({
      reportId: "report-1",
      tenantId: "default",
      reason: "人工确认误判",
    })).resolves.toEqual({
      evaluationUpdated: false,
      findingsUpdated: false,
      approvalSaved: false,
    });
  });
});
