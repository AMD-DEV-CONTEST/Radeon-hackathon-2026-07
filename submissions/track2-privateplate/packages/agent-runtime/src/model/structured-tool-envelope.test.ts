import { describe, expect, it } from "vitest";
import {
  buildToolEnvelopeSchema,
  isStructuredToolEnvelopeEnabled,
  parseToolEnvelopeContent,
  shouldUseStructuredToolEnvelope,
  structuredToolEnvelopeMode,
  synthesizeOpenAiToolCallResponse
} from "./structured-tool-envelope.js";
import { PRIVATEPLATE_CONTROL_TOOLS } from "./control-decisions.js";

describe("structured tool envelope", () => {
  it("builds oneOf branches for available tools", () => {
    const schema = buildToolEnvelopeSchema(
      PRIVATEPLATE_CONTROL_TOOLS.filter((t) => t.function.name === "finish_turn")
    );
    expect(schema.oneOf).toHaveLength(1);
    expect(schema.oneOf[0]!.properties.name.const).toBe("finish_turn");
    expect(schema.oneOf[0]!.properties.arguments).toMatchObject({
      type: "object",
      additionalProperties: false
    });
  });

  it("parses envelope JSON and rejects double-meaning content without name", () => {
    const ok = parseToolEnvelopeContent(
      JSON.stringify({
        name: "finish_turn",
        arguments: { goal: "compose_meal", message: "好的" }
      })
    );
    expect(ok?.name).toBe("finish_turn");
    expect(ok?.arguments.goal).toBe("compose_meal");
    expect(parseToolEnvelopeContent("not json")).toBeNull();
  });

  it("synthesizes OpenAI-shaped tool_calls from envelope", () => {
    const payload = synthesizeOpenAiToolCallResponse({
      model: "test-model",
      content: '{"name":"finish_turn","arguments":{"goal":"compose_meal","message":"ok"}}',
      envelope: {
        name: "finish_turn",
        argumentsJson: JSON.stringify({
          goal: "compose_meal",
          message: "ok"
        })
      }
    });
    const tc = (
      payload.choices as Array<{
        message: { tool_calls: Array<{ function: { name: string; arguments: string } }> };
      }>
    )[0]!.message.tool_calls[0]!;
    expect(tc.function.name).toBe("finish_turn");
    expect(JSON.parse(tc.function.arguments).goal).toBe("compose_meal");
  });

  it("respects PRIVATEPLATE_STRUCTURED_OUTPUTS policy", () => {
    expect(structuredToolEnvelopeMode({})).toBe("control");
    expect(structuredToolEnvelopeMode({ PRIVATEPLATE_STRUCTURED_OUTPUTS: "1" })).toBe(
      "control"
    );
    expect(structuredToolEnvelopeMode({ PRIVATEPLATE_STRUCTURED_OUTPUTS: "all" })).toBe(
      "all"
    );
    expect(isStructuredToolEnvelopeEnabled({ PRIVATEPLATE_STRUCTURED_OUTPUTS: "0" })).toBe(
      false
    );
    expect(
      isStructuredToolEnvelopeEnabled({ PRIVATEPLATE_STRUCTURED_OUTPUTS: "off" })
    ).toBe(false);
    expect(shouldUseStructuredToolEnvelope("FINAL_ONLY", {})).toBe(true);
    expect(shouldUseStructuredToolEnvelope("ACTION_ALLOWED", {})).toBe(false);
    expect(
      shouldUseStructuredToolEnvelope("ACTION_ALLOWED", {
        PRIVATEPLATE_STRUCTURED_OUTPUTS: "all"
      })
    ).toBe(true);
  });

  it("strips patterns and bounds free-form strings in envelope schemas", () => {
    const schema = buildToolEnvelopeSchema(
      PRIVATEPLATE_CONTROL_TOOLS.filter((t) => t.function.name === "finish_turn")
    );
    const args = schema.oneOf[0]!.properties.arguments as {
      properties?: { message?: { maxLength?: number; pattern?: string } };
    };
    expect(args.properties?.message?.maxLength).toBeTypeOf("number");
    expect(args.properties?.message?.pattern).toBeUndefined();
  });
});
