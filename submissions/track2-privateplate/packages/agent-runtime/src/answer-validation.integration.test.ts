import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import type {
  AgentModelProvider,
  ModelRouteDecision,
  ModelRouteInput
} from "./model/provider.js";

class NumberAnswerProvider implements AgentModelProvider {
  readonly mode = "scripted_mock" as const;
  readonly model = "number-answer-provider";

  constructor(private readonly unprovenNumber = false) {}

  async route(input: ModelRouteInput): Promise<ModelRouteDecision> {
    if (this.unprovenNumber) {
      return this.final("1. 今天额外增加 999 kcal。");
    }

    const context = input.currentTurn.toolResults.at(-1);
    if (!context) {
      const args = { dinerIds: input.state.dinerIds };
      return {
        kind: "tool",
        goal: "inspect_context",
        tool: "get_day_context",
        arguments: args,
        raw_model_arguments: args,
        normalized_model_arguments: args,
        effective_arguments: args,
        policy: {
          status: "ok",
          effective: args,
          privacy_violation: false,
          reasons: []
        },
        privacy_violation: false,
        model: this.model,
        format_retry_count: 0,
        format_retry_reasons: []
      };
    }

    return this.final(
      `1. 已读取当日上下文。\n4. 服务日期是 ${String(
        context.data?.serviceDate
      )}。`
    );
  }

  private final(message: string): Extract<ModelRouteDecision, { kind: "final" }> {
    return {
      kind: "final",
      goal: "inspect_context",
      message,
      reasonCode: null,
      transport: "native_function",
      model: this.model,
      privacy_violation: false,
      format_retry_count: 0,
      format_retry_reasons: []
    };
  }
}

describe("end-to-end number provenance", () => {
  let domain: PrivatePlateDomain;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterEach(() => domain.close());

  it("accepts ordered-list markers and a grounded service date", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "number-provenance-grounded",
      new NumberAnswerProvider()
    );

    const result = await agent.handleUserMessage("查看今日上下文");

    expect(result.validationOk).toBe(true);
    expect(result.answer).toContain("4. 服务日期");
  });

  it("still blocks an ungrounded business number without tool evidence", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "number-provenance-ungrounded",
      new NumberAnswerProvider(true)
    );

    const result = await agent.handleUserMessage("直接回答");

    expect(result.validationOk).toBe(false);
    expect(result.validationReasons).toContain("unproven_number:999");
    expect(result.phase).toBe("ERROR");
  });
});
