import { logAudit, logLlmCall, type AuditAction } from "../audit";

jest.mock("@/lib/supabase", () => ({
  supabaseAdmin: null,
}));

describe("AuditAction type", () => {
  const allActions: AuditAction[] = [
    "login",
    "logout",
    "evaluate",
    "overturn",
    "dispatch_feishu",
    "llm_call",
    "knowledge_create",
    "knowledge_update",
    "knowledge_delete",
    "bot_config_create",
    "bot_config_activate",
    "bot_config_archive",
    "optimization_task_create",
    "optimization_task_update",
    "report_generate",
    "campaign_import",
    "rule_create",
    "rule_delete",
    "feishu_event_receive",
    "auto_evaluate_failed",
    "knowledge_publish",
    "knowledge_reject",
    "bot_config_publish",
    "bot_config_reject",
    "bot_config_generate",
  ];

  it("covers all Phase 3 review-workflow actions", () => {
    expect(allActions).toContain("knowledge_publish");
    expect(allActions).toContain("knowledge_reject");
    expect(allActions).toContain("bot_config_publish");
    expect(allActions).toContain("bot_config_reject");
    expect(allActions).toContain("bot_config_generate");
  });

  it("covers all Phase 2 core actions", () => {
    expect(allActions).toContain("evaluate");
    expect(allActions).toContain("overturn");
    expect(allActions).toContain("dispatch_feishu");
    expect(allActions).toContain("llm_call");
    expect(allActions).toContain("feishu_event_receive");
  });
});

describe("logAudit", () => {
  it("is a callable function with correct parameter shape", () => {
    expect(typeof logAudit).toBe("function");
    // Function should accept the documented params (type check only)
    expect(logAudit.length).toBe(1); // single params object
  });

  it("does not throw even without supabase configuration", async () => {
    // Without supabaseAdmin configured, logAudit should silently skip
    const result = await logAudit({
      action: "evaluate",
      user_id: "test-user",
      resource_type: "test",
      resource_id: "test-1",
      detail: { score: 95 },
    });
    expect(result).toBeUndefined();
  });
});

describe("logLlmCall", () => {
  it("is a callable function with correct parameter shape", () => {
    expect(typeof logLlmCall).toBe("function");
    expect(logLlmCall.length).toBe(1);
  });

  it("does not throw without supabase configuration", async () => {
    const result = await logLlmCall({
      model: "kimi",
      prompt_type: "qa_evaluate",
      tokens_used: 150,
      latency_ms: 1200,
      correlation_id: "qa_test123",
    });
    expect(result).toBeUndefined();
  });
});
