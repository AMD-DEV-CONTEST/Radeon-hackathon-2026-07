/**
 * Tool-envelope structured outputs for vLLM when native tools cannot be
 * combined with structured_outputs (vLLM 0.25.x).
 *
 * Request emits one JSON object: { name, arguments } constrained by oneOf
 * branches built from the same tool definitions the provider would have sent.
 */
import type { PRIVATEPLATE_MODEL_TOOLS } from "./tool-definitions.js";
import type { PRIVATEPLATE_CONTROL_TOOLS } from "./control-decisions.js";

type AnyToolDef =
  | (typeof PRIVATEPLATE_MODEL_TOOLS)[number]
  | (typeof PRIVATEPLATE_CONTROL_TOOLS)[number];

export type ToolEnvelopeSchema = {
  oneOf: Array<{
    type: "object";
    additionalProperties: false;
    properties: {
      name: { const: string };
      arguments: Record<string, unknown>;
    };
    required: ["name", "arguments"];
  }>;
};

/**
 * Structured tool-envelope policy (`PRIVATEPLATE_STRUCTURED_OUTPUTS`):
 * - unset / control / 1 / true / on: FINAL_ONLY + BLOCKED only (default).
 *   Full-tool oneOf envelopes can deadlock xgrammar into whitespace until
 *   max_tokens on ACTION_ALLOWED; native tools stay there.
 * - all / always: every mode (experimental).
 * - 0 / false / off / no: disabled.
 */
export function structuredToolEnvelopeMode(
  env: NodeJS.ProcessEnv = process.env
): "off" | "control" | "all" {
  const raw = (env.PRIVATEPLATE_STRUCTURED_OUTPUTS ?? "control")
    .trim()
    .toLowerCase();
  if (raw === "0" || raw === "false" || raw === "off" || raw === "no") {
    return "off";
  }
  if (raw === "all" || raw === "always") return "all";
  return "control";
}

export function isStructuredToolEnvelopeEnabled(
  env: NodeJS.ProcessEnv = process.env
): boolean {
  return structuredToolEnvelopeMode(env) !== "off";
}

/** Whether this agent loop mode should use the JSON tool envelope. */
export function shouldUseStructuredToolEnvelope(
  mode: "ACTION_ALLOWED" | "FINAL_ONLY" | "BLOCKED",
  env: NodeJS.ProcessEnv = process.env
): boolean {
  const policy = structuredToolEnvelopeMode(env);
  if (policy === "off") return false;
  if (policy === "all") return true;
  return mode === "FINAL_ONLY" || mode === "BLOCKED";
}

export function buildToolEnvelopeSchema(tools: AnyToolDef[]): ToolEnvelopeSchema {
  if (tools.length === 0) {
    throw new Error("buildToolEnvelopeSchema requires at least one tool");
  }
  return {
    oneOf: tools.map((tool) => ({
      type: "object" as const,
      additionalProperties: false as const,
      properties: {
        name: { const: tool.function.name },
        arguments: sanitizeParametersForStructuredOutput(
          tool.function.parameters as Record<string, unknown>
        )
      },
      required: ["name", "arguments"] as ["name", "arguments"]
    }))
  };
}

/**
 * xgrammar / structured outputs are picky about some JSON Schema keywords.
 * Keep type/enum/const/required/additionalProperties/items/properties and
 * numeric bounds; drop unsupported vendor extensions and regex patterns
 * (patterns have triggered whitespace-padding deadlocks on this stack).
 */
function sanitizeParametersForStructuredOutput(
  schema: Record<string, unknown>
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(schema)) {
    if (
      key === "description" ||
      key === "title" ||
      key === "examples" ||
      key === "default" ||
      key === "pattern"
    ) {
      continue;
    }
    if (key === "properties" && value && typeof value === "object") {
      const props: Record<string, unknown> = {};
      for (const [prop, propSchema] of Object.entries(
        value as Record<string, unknown>
      )) {
        if (propSchema && typeof propSchema === "object") {
          props[prop] = sanitizeParametersForStructuredOutput(
            propSchema as Record<string, unknown>
          );
        } else {
          props[prop] = propSchema;
        }
      }
      out.properties = props;
      continue;
    }
    if (key === "items" && value && typeof value === "object") {
      out.items = sanitizeParametersForStructuredOutput(
        value as Record<string, unknown>
      );
      continue;
    }
    if (Array.isArray(value)) {
      out[key] = value.map((item) =>
        item && typeof item === "object"
          ? sanitizeParametersForStructuredOutput(item as Record<string, unknown>)
          : item
      );
      continue;
    }
    if (value && typeof value === "object") {
      out[key] = sanitizeParametersForStructuredOutput(
        value as Record<string, unknown>
      );
      continue;
    }
    out[key] = value;
  }
  // Bound free-form strings so constrained decoding cannot run away.
  if (out.type === "string" && out.enum === undefined && out.const === undefined) {
    if (typeof out.maxLength !== "number") {
      out.maxLength = 1200;
    }
  }
  return out;
}

export function envelopeInstructionForTools(tools: AnyToolDef[]): string {
  const catalog = tools.map((tool) => ({
    name: tool.function.name,
    description: tool.function.description
  }));
  return [
    "Respond with exactly one JSON object of the form",
    '{"name":"<tool_name>","arguments":{...}}.',
    "Do not wrap enum string values in extra quotes.",
    "Do not emit markdown fences or any text outside the JSON object.",
    "In finish_turn.summary, do not invent numeric calories, grams, or counts that were not returned by tools.",
    "Argument objects must satisfy the structured schema for the chosen name.",
    `Available tools: ${JSON.stringify(catalog)}`
  ].join(" ");
}

export function parseToolEnvelopeContent(content: unknown): {
  name: string;
  arguments: Record<string, unknown>;
  argumentsJson: string;
} | null {
  if (typeof content !== "string" || !content.trim()) return null;
  let text = content.trim();
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence?.[1]) text = fence[1].trim();
  const tag = text.match(/<tool_call>\s*([\s\S]*?)\s*<\/tool_call>/i);
  if (tag?.[1]) text = tag[1].trim();
  try {
    const parsed = JSON.parse(text) as {
      name?: unknown;
      arguments?: unknown;
    };
    if (typeof parsed.name !== "string" || !parsed.name) return null;
    const args =
      parsed.arguments && typeof parsed.arguments === "object"
        ? (parsed.arguments as Record<string, unknown>)
        : {};
    return {
      name: parsed.name,
      arguments: args,
      argumentsJson: JSON.stringify(args)
    };
  } catch {
    return null;
  }
}

export function synthesizeOpenAiToolCallResponse(input: {
  model: string;
  content: string | null;
  envelope: { name: string; argumentsJson: string } | null;
  usage?: Record<string, unknown>;
}): Record<string, unknown> {
  const toolCalls = input.envelope
    ? [
        {
          id: `envelope-${input.envelope.name}`,
          type: "function",
          function: {
            name: input.envelope.name,
            arguments: input.envelope.argumentsJson
          }
        }
      ]
    : [];
  return {
    id: "chatcmpl-envelope",
    object: "chat.completion",
    model: input.model,
    choices: [
      {
        index: 0,
        finish_reason: toolCalls.length ? "tool_calls" : "stop",
        message: {
          role: "assistant",
          content: toolCalls.length ? null : input.content,
          tool_calls: toolCalls.length ? toolCalls : undefined
        }
      }
    ],
    usage: input.usage ?? {}
  };
}
