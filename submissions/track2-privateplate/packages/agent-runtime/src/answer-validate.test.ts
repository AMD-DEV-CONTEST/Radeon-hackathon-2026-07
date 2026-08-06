import { describe, expect, it } from "vitest";
import {
  collectAllowedDates,
  collectAllowedNumbers,
  extractNumbers,
  extractDates,
  validateFinalAnswer,
  type ValidationInput
} from "./answer-validate.js";

function input(overrides: Partial<ValidationInput>): ValidationInput {
  return {
    answer: "已生成预览，请确认后再执行。",
    toolOk: true,
    claimedSuccessWrite: false,
    hasCommitResult: false,
    retrievalSourceIds: [],
    citedSourceIds: [],
    allowedNumbers: [],
    mentionedNumbers: [],
    ...overrides
  };
}

describe("final answer write-claim validation", () => {
  it("does not mistake a preview phrase for an inventory write", () => {
    expect(
      validateFinalAnswer(
        input({
          answer: "已预览库存入库；确认后才会记入库存。",
          successfulTools: ["preview_inventory_change"]
        })
      )
    ).toEqual({ ok: true });
  });

  it("rejects an inventory write claim without a commit result", () => {
    const result = validateFinalAnswer(
      input({
        answer: "已经入库。",
        successfulTools: ["preview_inventory_change"]
      })
    );
    expect(result).toEqual({
      ok: false,
      reasons: ["inventory_write_claim_without_commit"]
    });
  });

  it("rejects member-memory and meal-completion write claims", () => {
    expect(
      validateFinalAnswer(
        input({
          answer: "已保存家庭资料。",
          successfulTools: ["preview_member_memory_change"]
        })
      )
    ).toEqual({
      ok: false,
      reasons: ["member_memory_write_claim_without_commit"]
    });

    expect(
      validateFinalAnswer(
        input({
          answer: "已记入摄入。",
          successfulTools: ["preview_meal_completion"]
        })
      )
    ).toEqual({
      ok: false,
      reasons: ["meal_completion_write_claim_without_commit"]
    });
  });

  it("rejects inventory debit claims after plan preview without a commit", () => {
    for (const answer of [
      "库存中的白菜、豆腐和熟米饭已从现有库存中扣除。",
      "库存已减少。",
      "本餐已扣库存。"
    ]) {
      expect(
        validateFinalAnswer(
          input({ answer, successfulTools: ["finalize_meal_plan"] })
        )
      ).toEqual({
        ok: false,
        reasons: ["plan_write_claim_without_commit"]
      });
    }
  });

  it("allows a plan preview that explicitly says the debit is still pending", () => {
    expect(
      validateFinalAnswer(
        input({
          answer: "计划已生成，确认后才会从现有库存中扣除。",
          successfulTools: ["finalize_meal_plan"]
        })
      )
    ).toEqual({ ok: true });
  });
});

describe("number extraction", () => {
  it("ignores indented ordered-list markers", () => {
    expect(extractNumbers("  4. 先确认\n4) 再入库\n4、最后查看")).toEqual([]);
  });

  it("ignores list markers the model separated with HTML breaks", () => {
    expect(
      extractNumbers(
        "当前库存如下：<br>1. 大白菜：约 400g<br>2. 鸡腿：约 360g<br>3. 熟米饭：约 300g<br>4. 北豆腐：350g"
      )
    ).toEqual([400, 360, 300, 350]);
  });

  it("keeps business numbers and body facts", () => {
    expect(extractNumbers("4g 豆腐，4 人，40 kcal；正文第 4 项")).toEqual([
      4,
      4,
      40,
      4
    ]);
  });

  it("does not treat a decimal at line start as a list marker", () => {
    expect(extractNumbers("4.5g 是估算值")).toEqual([4.5]);
  });

  it("does not extract the parts of an ISO service date", () => {
    expect(extractNumbers("服务日期是 2026-08-03。4g 豆腐。")).toEqual([4]);
  });

  it("extracts dates separately and validates them against serviceDate evidence", () => {
    expect(extractDates("今天是 2026-08-03，明天是 2026-08-04。")).toEqual([
      "2026-08-03",
      "2026-08-04"
    ]);
    expect(
      collectAllowedDates([
        { serviceDate: "2026-08-03", nested: { serviceDate: "tomorrow" } }
      ])
    ).toEqual(["2026-08-03"]);

    expect(
      validateFinalAnswer(
        input({
          answer: "服务日期是 2026-08-03。",
          allowedDates: ["2026-08-03"],
          mentionedDates: ["2026-08-03"]
        })
      )
    ).toEqual({ ok: true });
    expect(
      validateFinalAnswer(
        input({
          answer: "服务日期是 2026-08-04。",
          allowedDates: ["2026-08-03"],
          mentionedDates: ["2026-08-04"]
        })
      )
    ).toEqual({ ok: false, reasons: ["unproven_date:2026-08-04"] });
  });

  it("still rejects unproven numbers and false write claims in final content", () => {
    expect(
      validateFinalAnswer(
        input({
          answer: "计划已生成，今天额外有 999 kcal，库存也已经扣除了。",
          successfulTools: ["finalize_meal_plan"],
          mentionedNumbers: [999],
          allowedNumbers: []
        })
      )
    ).toEqual({
      ok: false,
      reasons: ["plan_write_claim_without_commit", "unproven_number:999"]
    });
  });

  it("accepts tool numbers the answer rounded or ceiled for readability", () => {
    expect(
      validateFinalAnswer(
        input({
          answer:
            "采购缺口：大白菜约 535g、香菇约 143g、鸡蛋约 500g，需要买 4 盒豆腐。",
          mentionedNumbers: [535, 143, 500, 4],
          allowedNumbers: [534.6, 142.56, 498.96, 3.21]
        })
      )
    ).toEqual({ ok: true });
  });

  it("keeps rejecting a number no tool result can support", () => {
    expect(
      validateFinalAnswer(
        input({
          answer: "今天还剩 620 kcal。",
          mentionedNumbers: [620],
          allowedNumbers: [534.6, 142.56]
        })
      )
    ).toEqual({ ok: false, reasons: ["unproven_number:620"] });
  });

  it("lets a knowledge answer name a dish the plan does not contain", () => {
    expect(
      validateFinalAnswer(
        input({
          answer: "主食建议用糙米代替白米饭，升糖速度更平缓。",
          successfulTools: ["retrieve_local_knowledge"],
          knownTemplates: [{ id: "tpl-plain-rice", name: "白米饭" }],
          allowedTemplateIds: []
        })
      )
    ).toEqual({ ok: true });
  });

  it("still rejects a dish the plan does not contain once planning ran", () => {
    expect(
      validateFinalAnswer(
        input({
          answer: "今晚给你安排了白米饭。",
          successfulTools: ["finalize_meal_plan"],
          knownTemplates: [{ id: "tpl-plain-rice", name: "白米饭" }],
          allowedTemplateIds: ["tpl-leftover-rice"]
        })
      )
    ).toEqual({ ok: false, reasons: ["unproven_template:tpl-plain-rice"] });
  });
});

describe("retrieved corpus text as numeric evidence", () => {
  it("treats vector-retriever chunk text as provenance for its own numbers", () => {
    expect(
      collectAllowedNumbers([
        {
          hits: [
            {
              title: "晚餐主食参考",
              content: "一般建议每餐主食 50-75g 干重，约 300 kcal。",
              score: 0.82
            }
          ]
        }
      ])
    ).toEqual(expect.arrayContaining([50, 75, 300]));
  });
});
