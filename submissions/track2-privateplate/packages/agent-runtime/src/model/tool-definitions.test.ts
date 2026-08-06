import { describe, expect, it } from "vitest";
import {
  normalizeStructuredTransport,
  parseModelToolArguments,
  PRIVATEPLATE_MODEL_TOOLS
} from "./tool-definitions.js";

describe("v2 tool argument parsing", () => {
  it("parses get_day_context", () => {
    expect(
      parseModelToolArguments("get_day_context", {
        goal: "inspect_context",
        dinerIds: ["mem-admin", "mem-father"],
        serviceDate: "2026-08-03"
      })
    ).toEqual({
      dinerIds: ["mem-admin", "mem-father"],
      serviceDate: "2026-08-03"
    });
  });

  it("parses find_dish_candidates with transport defaults", () => {
    expect(
      parseModelToolArguments("find_dish_candidates", {
        goal: "compose_meal",
        dinerIds: ["mem-admin"]
      })
    ).toEqual({
      dinerIds: ["mem-admin"],
      rejectedFoodIds: [],
      rejectedTemplateIds: []
    });
  });

  it("rejects undeclared sibling keys models invent", () => {
    expect(() =>
      parseModelToolArguments("find_dish_candidates", {
        dinerIds: ["mem-admin", "mem-father", "mem-mother"],
        rejectedFoodIds: ["food-chicken-leg"],
        rejectedTemplateIds: [],
        rejections: ["鸡腿"],
        requestedDishIds: ["tpl-x"],
        requestedPriorityFoodIds: ["food-tofu"]
      })
    ).toThrow(/Unknown fields.*find_dish_candidates/);
  });

  it("rejects invalid service dates", () => {
    expect(() =>
      parseModelToolArguments("get_day_context", {
        dinerIds: ["mem-admin"],
        serviceDate: "tomorrow"
      })
    ).toThrow();
  });

  it("unwraps double-quoted fixture ids in lists", () => {
    expect(
      parseModelToolArguments("find_dish_candidates", {
        dinerIds: ['"mem-admin"', '"mem-father"'],
        rejectedFoodIds: ['"food-chicken-leg"'],
        rejectedTemplateIds: []
      })
    ).toEqual({
      dinerIds: ["mem-admin", "mem-father"],
      rejectedFoodIds: ["food-chicken-leg"],
      rejectedTemplateIds: []
    });
  });

  it("normalizes every declared quoted string path in a finalize call", () => {
    expect(
      parseModelToolArguments("finalize_meal_plan", {
        goal: '"compose_meal"',
        dinerIds: ['"mem-admin"'],
        mealType: '"lunch"',
        candidateSetId: '"cset-1"',
        selectedDishes: [
          {
            templateId: '"tpl-cabbage-tofu-braise"',
            relativePortion: '"standard"'
          }
        ],
        mealPortionScale: 1.0,
        selectionReason: '"优先使用豆腐"'
      })
    ).toEqual({
      dinerIds: ["mem-admin"],
      mealType: "lunch",
      candidateSetId: "cset-1",
      selectedDishes: [
        {
          templateId: "tpl-cabbage-tofu-braise",
          relativePortion: "standard"
        }
      ],
      mealPortionScale: 1.0,
      selectionReason: "优先使用豆腐"
    });
  });

  it("preserves natural-language quotes and unwraps at most one JSON layer", () => {
    const query = "解释““最小披露””为什么重要。";
    expect(
      normalizeStructuredTransport("retrieve_local_knowledge", { query })
    ).toEqual({ query });

    const twiceWrapped = JSON.stringify(JSON.stringify("mem-admin"));
    expect(
      normalizeStructuredTransport("get_day_context", {
        dinerIds: [twiceWrapped]
      })
    ).toEqual({ dinerIds: ['"mem-admin"'] });
  });

  it("parses finalize_meal_plan", () => {
    expect(
      parseModelToolArguments("finalize_meal_plan", {
        goal: "compose_meal",
        dinerIds: ["mem-admin", "mem-father", "mem-mother"],
        mealType: "lunch",
        candidateSetId: "cset-1",
        selectedDishes: [
          { templateId: "tpl-cabbage-tofu-braise", relativePortion: "standard" }
        ],
        mealPortionScale: 1.0,
        selectionReason: "优先豆腐"
      })
    ).toMatchObject({
      mealType: "lunch",
      candidateSetId: "cset-1",
      mealPortionScale: 1.0
    });
  });

  it("exposes a variable 1–12 dish selection contract", () => {
    const finalize = PRIVATEPLATE_MODEL_TOOLS.find(
      (tool) => tool.function.name === "finalize_meal_plan"
    );
    const parameters = finalize?.function.parameters as unknown as {
      properties: {
        selectedDishes: { maxItems?: number };
      };
    };
    expect(finalize?.function.description).toContain("1–12");
    expect(finalize?.function.description).toContain("count is not fixed");
    expect(parameters.properties.selectedDishes.maxItems).toBe(12);
    expect(() =>
      parseModelToolArguments("finalize_meal_plan", {
        goal: "compose_meal",
        dinerIds: ["mem-admin"],
        mealType: "lunch",
        candidateSetId: "cset-1",
        selectedDishes: Array.from({ length: 13 }, (_, index) => ({
          templateId: `tpl-${index}`,
          relativePortion: "standard"
        })),
        mealPortionScale: 1.0,
        selectionReason: "test"
      })
    ).toThrow();
  });

  it("parses preview_meal_completion", () => {
    expect(
      parseModelToolArguments("preview_meal_completion", {
        goal: "preview_meal_completion",
        mode: "as_planned"
      })
    ).toEqual({ mode: "as_planned" });
  });

  it("defaults preview_meal_completion mode when omitted or confused with mealStructure", () => {
    expect(
      parseModelToolArguments("preview_meal_completion", {
        goal: "complete_meal"
      })
    ).toEqual({ mode: "as_planned" });
    expect(
      parseModelToolArguments("preview_meal_completion", {
        goal: "complete_meal",
        mode: "standard"
      })
    ).toEqual({ mode: "as_planned" });
  });

  it("parses preview_caregiver_task", () => {
    expect(
      parseModelToolArguments("preview_caregiver_task", {
        goal: "send_handoff",
        recipientLabel: "保姆",
        serveAt: "unspecified"
      })
    ).toEqual({ recipientLabel: "保姆", serveAt: "unspecified" });
  });

  it("accepts loose serveAt strings at transport without regex failure", () => {
    expect(
      parseModelToolArguments("preview_caregiver_task", {
        recipientLabel: "阿姨",
        serveAt: "18:00"
      })
    ).toEqual({ recipientLabel: "阿姨", serveAt: "18:00" });
    expect(
      parseModelToolArguments("preview_caregiver_task", {
        recipientLabel: "保姆"
      })
    ).toEqual({ recipientLabel: "保姆", serveAt: "unspecified" });
  });

  it("does not require transport-neutral arrays on find_dish_candidates", () => {
    const tool = PRIVATEPLATE_MODEL_TOOLS.find(
      (entry) => entry.function.name === "find_dish_candidates"
    );
    expect(tool?.function.parameters.required).toEqual(["dinerIds"]);
  });

  it("parses retrieve_local_knowledge", () => {
    expect(
      parseModelToolArguments("retrieve_local_knowledge", {
        goal: "retrieve_guidance",
        query: "任务卡能不能写疾病"
      })
    ).toEqual({ query: "任务卡能不能写疾病", topK: 2 });
  });

  it("registers product tools including RAG and write previews", () => {
    expect(PRIVATEPLATE_MODEL_TOOLS.map((t) => t.function.name).sort()).toEqual(
      [
        "finalize_meal_plan",
        "find_dish_candidates",
        "get_day_context",
        "get_inventory",
        "preview_caregiver_task",
        "preview_inventory_change",
        "preview_meal_completion",
        "preview_member_memory_change",
        "retrieve_local_knowledge"
      ].sort()
    );
  });
});
