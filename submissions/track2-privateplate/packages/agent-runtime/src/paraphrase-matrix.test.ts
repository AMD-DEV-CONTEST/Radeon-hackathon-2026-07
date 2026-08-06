import { describe, expect, it } from "vitest";
import { classifyIntent } from "./policy.js";

describe("paraphrase matrix (intent only)", () => {
  const cases = [
    ["规划午餐", "plan_meal"],
    ["中午吃什么", "plan_meal"],
    ["换一道菜", "revise_meal"],
    ["查看库存", "inspect_context"]
  ] as const;

  for (const [text, intent] of cases) {
    it(`${text} → ${intent}`, () => {
      expect(classifyIntent(text).intent).toBe(intent);
    });
  }
});
