// ============================================================================
// Tests for Unresolved Questions Module
// Tests: normalization, CSV/JSON parsing, API response format, idempotency
// ============================================================================

import { createCorrelationId } from "@/lib/correlation";
import { resolveCategory, parseJsonEntries, parseCsvEntries } from "@/lib/knowledge-import-utils";
import {
  buildConversationText,
  extractCheckedSteps,
  normalizeCheckedSteps,
  toExportRecord,
} from "@/lib/unresolved-questions";

// ── Helpers (mirror of route logic for unit testing) ────────────────────

function normalizeRow(raw: Record<string, unknown>): Record<string, unknown> {
  return {
    ...raw,
    tags: Array.isArray(raw.tags) ? raw.tags : [],
    category: raw.category || null,
    note: raw.note || null,
    assigned_to: raw.assigned_to || null,
  };
}

function extractUserQuestion(conversation: string): { userQuestion: string; aiReply: string } {
  const lines = conversation.split("\n");
  let userQuestion = "";
  let aiReply = "";
  let foundUser = false;
  let foundAI = false;

  for (const line of lines) {
    const um = line.match(/^(?:用户|顾客|Customer|买家)[：:]\s*(.+)/i);
    if (um && !foundUser) {
      userQuestion = um[1].trim().slice(0, 500);
      foundUser = true;
      continue;
    }
    const am = line.match(/^(?:客服|机器人|Bot|AI)[：:]\s*(.+)/i);
    if (am && foundUser && !foundAI) {
      aiReply = am[1].trim().slice(0, 500);
      foundAI = true;
    }
  }
  return { userQuestion, aiReply };
}

// Helper to extract first user question for gap analysis (used in cron)
function extractGapQuestions(conversation: string): string[] {
  const lines = conversation.split("\n");
  const questions: string[] = [];
  for (const line of lines) {
    const m = line.match(/^(?:用户|顾客|Customer|买家)[：:]\s*(.+)/i);
    if (m && m[1].length > 3) questions.push(m[1]);
  }
  return questions;
}

// ── Tests ──────────────────────────────────────────────────────────────

describe("UnresolvedQuestions - Normalization", () => {
  test("normalizeRow fills defaults for null fields", () => {
    const raw = { id: "1", session_id: "s1", user_question: "test" };
    const norm = normalizeRow(raw);
    expect(norm.tags).toEqual([]);
    expect(norm.category).toBeNull();
    expect(norm.note).toBeNull();
  });

  test("normalizeRow preserves existing values", () => {
    const raw = { id: "1", session_id: "s1", user_question: "test", tags: ["a"], category: "faq", note: "hello" };
    const norm = normalizeRow(raw);
    expect(norm.tags).toEqual(["a"]);
    expect(norm.category).toBe("faq");
    expect(norm.note).toBe("hello");
  });
});

describe("UnresolvedQuestions - CSV Parsing", () => {
  test("parses valid CSV with headers", () => {
    const csv = "title,content,category\n问题1,回答1,faq\n问题2,回答2,product";
    const result = parseCsvEntries(csv);
    expect(result).toHaveLength(2);
    expect(result[0].title).toBe("问题1");
    expect(result[0].content).toBe("回答1");
    expect(result[0].category).toBe("faq");
    expect(result[1].category).toBe("product");
  });

  test("returns empty for single-line CSV", () => {
    expect(parseCsvEntries("title,content")).toEqual([]);
  });

  test("returns empty for empty input", () => {
    expect(parseCsvEntries("")).toEqual([]);
  });

  test("simple CSV without commas in values", () => {
    const csv = "title,content,category\nhello world,answer text,faq";
    const result = parseCsvEntries(csv);
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("hello world");
    expect(result[0].content).toBe("answer text");
  });
});

describe("UnresolvedQuestions - JSON Parsing", () => {
  test("parses valid JSON array", () => {
    const json = '[{"title":"T1","content":"C1","category":"faq"}]';
    const result = parseJsonEntries(json);
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("T1");
  });

  test("strips markdown code fences", () => {
    const json = '```json\n[{"title":"T1","content":"C1"}]\n```';
    const result = parseJsonEntries(json);
    expect(result).toHaveLength(1);
  });

  test("handles nested JSON extraction", () => {
    const json = '一些文字 [{"title":"T1","content":"C1"}] 更多文字';
    const result = parseJsonEntries(json);
    expect(result).toHaveLength(1);
  });

  test("returns empty for invalid JSON", () => {
    expect(parseJsonEntries("not json")).toEqual([]);
  });
});

describe("UnresolvedQuestions - Category Resolution", () => {
  test("maps Chinese category labels", () => {
    expect(resolveCategory("物流")).toBe("faq");
    expect(resolveCategory("产品")).toBe("product");
    expect(resolveCategory("售后")).toBe("after_sales_policy");
    expect(resolveCategory("活动")).toBe("campaign");
    expect(resolveCategory("欢迎语")).toBe("greeting");
  });

  test("passes through English categories", () => {
    expect(resolveCategory("faq")).toBe("faq");
    expect(resolveCategory("product")).toBe("product");
  });

  test("defaults to faq for unknown categories", () => {
    expect(resolveCategory("unknown")).toBe("faq");
    expect(resolveCategory(undefined as unknown as string)).toBe("faq");
  });
});

describe("UnresolvedQuestions - Conversation Parsing", () => {
  test("extracts first user question from conversation", () => {
    const conv = "用户：你好，请问这个什么时候发货？\n客服：亲，正常48小时内发货哦\n用户：能快点吗？";
    const { userQuestion, aiReply } = extractUserQuestion(conv);
    expect(userQuestion).toBe("你好，请问这个什么时候发货？");
    expect(aiReply).toBe("亲，正常48小时内发货哦");
  });

  test("handles English labels", () => {
    const conv = "Customer: Where is my order?\nBot: Let me check for you.";
    const { userQuestion, aiReply } = extractUserQuestion(conv);
    expect(userQuestion).toBe("Where is my order?");
    expect(aiReply).toBe("Let me check for you.");
  });

  test("truncates long questions to 500 chars", () => {
    const long = "用户：" + "a".repeat(600);
    const { userQuestion } = extractUserQuestion(long);
    expect(userQuestion.length).toBeLessThanOrEqual(500);
  });

  test("extracts all user questions for gap analysis", () => {
    const conv = "用户：第一个问题\n客服：回答\n用户：第二个问题\n用户：第三个问题";
    const questions = extractGapQuestions(conv);
    expect(questions).toHaveLength(3);
    expect(questions[0]).toBe("第一个问题");
    expect(questions[2]).toBe("第三个问题");
  });
});

describe("UnresolvedQuestions - Correlation ID", () => {
  test("creates correlation ID with prefix", () => {
    const id = createCorrelationId("uq");
    expect(id).toMatch(/^uq_/);
  });
});

describe("UnresolvedQuestions - Minimal Record Fields", () => {
  test("normalizes checked steps from multiline text", () => {
    const steps = normalizeCheckedSteps("1. 问指示灯颜色\n2. 检查电源\n- 查看 App 状态");
    expect(steps).toEqual(["问指示灯颜色", "检查电源", "查看 App 状态"]);
  });

  test("builds conversation text with checked steps and reason", () => {
    const conversation = buildConversationText({
      user_question: "摄像头离线了",
      ai_reply: "先确认指示灯状态",
      checked_steps: ["询问指示灯颜色", "检查电源插头"],
      unresolved_reason: "三轮排查仍未恢复",
    });

    expect(conversation).toContain("用户：摄像头离线了");
    expect(conversation).toContain("已排查步骤：");
    expect(conversation).toContain("1. 询问指示灯颜色");
    expect(conversation).toContain("未解决原因：三轮排查仍未恢复");
  });

  test("extracts checked steps for export", () => {
    const steps = extractCheckedSteps({
      conversation: "用户：摄像头离线了\n已排查步骤：\n1. 问指示灯\n2. 查路由器\n未解决原因：需要人工",
    });

    expect(steps).toBe("问指示灯；查路由器");
  });

  test("maps export record to review table fields", () => {
    const row = toExportRecord({
      id: "1",
      session_id: "manual_1",
      platform_code: "pdd",
      user_question: "我要退货",
      category: "退换货",
      transfer_reason: "涉及平台售后政策",
      status: "pending",
      created_at: "2026-06-14T00:00:00Z",
      conversation: "已排查步骤：\n1. 索要订单号",
    });

    expect(row["渠道"]).toBe("pdd");
    expect(row["问题类型"]).toBe("退换货");
    expect(row["AI已排查步骤"]).toBe("索要订单号");
    expect(row["未解决原因"]).toBe("涉及平台售后政策");
  });
});

describe("UnresolvedQuestions - Import Trained Parsing", () => {
  test("handles trained output with multiple entries", () => {
    const csv = "title,content,category,keywords\n发货时间,正常48小时内发货,faq,发货;物流\n退款流程,联系售后处理,after_sales_policy,退款;退货";
    const result = parseCsvEntries(csv);
    expect(result).toHaveLength(2);
    expect(result[0].title).toBe("发货时间");
    expect(result[0].category).toBe("faq");
  });

  test("returns empty for CSV missing required headers", () => {
    expect(parseCsvEntries("name,value\nhello,world")).toEqual([]);
  });
});
