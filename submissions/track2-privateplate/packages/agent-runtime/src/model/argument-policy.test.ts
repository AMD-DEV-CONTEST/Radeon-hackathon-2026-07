import { describe, expect, it } from "vitest";
import { applyTrustedArgumentPolicy } from "./argument-policy.js";

const dictionary = {
  members: [
    { id: "mem-admin", displayName: "管理员", roleLabel: "admin", healthTags: [] }
  ],
  foods: [{ id: "food-tofu", name: "北豆腐" }],
  templates: [{ id: "tpl-x", name: "测试菜" }],
  planTags: [],
  caregiverRecipientLabels: ["保姆", "阿姨", "家庭保姆"]
};

const baseState = {
  dinerIds: ["mem-admin"],
  activePlanId: "plan-1",
  expectedRecipientLabel: "阿姨",
  knownServeAt: null as string | null
};

describe("applyTrustedArgumentPolicy preview normalization", () => {
  it("canonicalizes bare clock serveAt using user text", () => {
    const result = applyTrustedArgumentPolicy({
      tool: "preview_caregiver_task",
      userText: "今晚六点开饭，给阿姨生成任务卡",
      dinerIdsLocked: false,
      state: baseState,
      dictionary,
      rawArgs: {
        recipientLabel: "阿姨",
        serveAt: "18:00"
      }
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.effective.serveAt).toBe("今天 18:00");
    }
  });

  it("uses knownServeAt from pending clarification when model omits serveAt", () => {
    const result = applyTrustedArgumentPolicy({
      tool: "preview_caregiver_task",
      userText: "生成任务卡",
      dinerIdsLocked: false,
      state: {
        ...baseState,
        knownServeAt: "今天 12:00"
      },
      dictionary,
      rawArgs: {
        recipientLabel: "阿姨"
      }
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.effective.serveAt).toBe("今天 12:00");
    }
  });

  it("always normalizes preview_meal_completion mode to as_planned", () => {
    const result = applyTrustedArgumentPolicy({
      tool: "preview_meal_completion",
      userText: "按计划吃完这顿",
      dinerIdsLocked: false,
      state: baseState,
      dictionary,
      rawArgs: {
        mode: "standard"
      }
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.effective.mode).toBe("as_planned");
    }
  });

  it("accepts empty get_inventory args", () => {
    const result = applyTrustedArgumentPolicy({
      tool: "get_inventory",
      userText: "看一下库存",
      dinerIdsLocked: false,
      state: baseState,
      dictionary,
      rawArgs: {}
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.effective).toEqual({});
    }
  });
});
