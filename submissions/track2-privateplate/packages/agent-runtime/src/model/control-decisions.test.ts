import { describe, expect, it } from "vitest";
import {
  CONTROL_MESSAGE_MAX_LENGTH,
  FINISH_TURN_GOALS,
  PRIVATEPLATE_CONTROL_TOOLS,
  parseControlDecisionArguments
} from "./control-decisions.js";

describe("control decisions", () => {
  it("registers ask_user finish_turn refuse_request", () => {
    expect(
      PRIVATEPLATE_CONTROL_TOOLS.map((t) => t.function.name).sort()
    ).toEqual(["ask_user", "finish_turn", "refuse_request"].sort());
  });

  it("keeps finish_turn preview goals aligned across schema and Zod", () => {
    const finishTurn = PRIVATEPLATE_CONTROL_TOOLS.find(
      (tool) => tool.function.name === "finish_turn"
    );
    const goalSchema = finishTurn?.function.parameters.properties.goal as {
      enum: string[];
    };
    expect(goalSchema.enum).toEqual([...FINISH_TURN_GOALS]);

    for (const goal of [
      "preview_inventory",
      "update_inventory",
      "preview_member_memory",
      "update_member_memory",
      "preview_meal_completion",
      "complete_meal"
    ] as const) {
      expect(
        parseControlDecisionArguments("finish_turn", {
          goal,
          message: "已完成预览，等待确认。"
        })
      ).toEqual({
        kind: "final",
        goal,
        message: "已完成预览，等待确认。"
      });
    }
  });

  it("uses one widened message limit for control schemas", () => {
    const message = "好".repeat(CONTROL_MESSAGE_MAX_LENGTH);
    expect(
      parseControlDecisionArguments("finish_turn", {
        goal: "preview_inventory",
        message
      })
    ).toMatchObject({ kind: "final", goal: "preview_inventory", message });
  });

  it("unwraps one JSON string layer on finish_turn.goal", () => {
    expect(
      parseControlDecisionArguments("finish_turn", {
        goal: '"compose_meal"',
        message: "已为三人准备晚餐方案。"
      })
    ).toMatchObject({ kind: "final", goal: "compose_meal" });
  });
});
