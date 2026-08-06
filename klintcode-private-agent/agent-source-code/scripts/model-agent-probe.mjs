#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve, sep } from "node:path";

const endpoint = process.env.KLINTCODE_ENDPOINT
  ?? "https://token-plan-cn.xiaomimimo.com/v1";
const model = process.env.KLINTCODE_MODEL ?? "mimo-v2.5-pro";
const apiKey = process.env.MIMO_API_KEY;
if (!apiKey) {
  throw new Error("MIMO_API_KEY is required");
}

const apiBase = endpoint.replace(/\/+$/, "");
const chatUrl = apiBase.endsWith("/v1")
  ? `${apiBase}/chat/completions`
  : `${apiBase}/v1/chat/completions`;
const workspace = mkdtempSync(join(tmpdir(), "klintcode-model-agent-probe-"));
mkdirSync(join(workspace, "src"), { recursive: true });
writeFileSync(
  join(workspace, "Cargo.toml"),
  `[package]
name = "model-agent-probe"
version = "0.1.0"
edition = "2024"
`,
);
writeFileSync(
  join(workspace, "src/lib.rs"),
  `/// Return the median without changing the input.
pub fn median(values: &[i32]) -> Option<f64> {
    if values.is_empty() {
        return Some(0.0);
    }
    let mut sorted = values.to_vec();
    sorted.sort();
    Some(f64::from(sorted[sorted.len() / 2]))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input_has_no_median() {
        assert_eq!(median(&[]), None);
    }

    #[test]
    fn odd_input_uses_the_middle_value() {
        assert_eq!(median(&[9, 1, 4]), Some(4.0));
    }

    #[test]
    fn even_input_averages_the_two_middle_values() {
        assert_eq!(median(&[1, 2, 3, 10]), Some(2.5));
    }

    #[test]
    fn input_is_not_modified() {
        let values = [3, 1, 2];
        let _ = median(&values);
        assert_eq!(values, [3, 1, 2]);
    }
}
`,
);

const task = `Fix the Rust median function in this isolated workspace.
All existing tests must pass. Preserve the public signature and do not add dependencies.`;

async function complete(messages, tools) {
  const body = {
    model,
    messages,
    temperature: 0,
    top_p: 1,
    max_tokens: 2048,
    stream: false,
  };
  if (tools) {
    body.tools = tools;
    body.tool_choice = "auto";
  }
  const response = await fetch(chatUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Model request failed: HTTP ${response.status} ${await response.text()}`);
  }
  const result = await response.json();
  const choice = result.choices?.[0];
  if (!choice?.message) {
    throw new Error("Model response did not contain a message");
  }
  return { choice, usage: result.usage };
}

function parseJsonContent(content) {
  const cleaned = (content ?? "")
    .trim()
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/, "")
    .replace(/\s*```$/, "");
  return JSON.parse(cleaned);
}

function safePath(path) {
  const absolute = resolve(workspace, path);
  if (absolute !== workspace && !absolute.startsWith(`${workspace}${sep}`)) {
    throw new Error(`Path escapes isolated workspace: ${path}`);
  }
  return absolute;
}

function listFiles(directory = ".") {
  const root = safePath(directory);
  const files = [];
  function visit(current) {
    for (const entry of readdirSync(current).sort()) {
      if (entry === "target") continue;
      const path = join(current, entry);
      if (statSync(path).isDirectory()) {
        visit(path);
      } else {
        files.push(relative(workspace, path));
      }
    }
  }
  visit(root);
  return files;
}

let testsPassed = false;
let planStatuses;
function executeTool(name, args) {
  if (name !== "update_plan" && planStatuses.get(args.step_id) !== "in_progress") {
    return {
      ok: false,
      error: `Plan step ${args.step_id} must be marked in_progress before using ${name}`,
    };
  }
  switch (name) {
    case "update_plan": {
      const index = plan.steps.findIndex((step) => step.id === args.step_id);
      const current = planStatuses.get(args.step_id);
      if (args.status === "in_progress") {
        const incompleteEarlier = plan.steps
          .slice(0, index)
          .find((step) => planStatuses.get(step.id) !== "completed");
        const otherCurrent = plan.steps.find(
          (step) =>
            step.id !== args.step_id && planStatuses.get(step.id) === "in_progress",
        );
        if (incompleteEarlier || otherCurrent || current === "completed") {
          return {
            ok: false,
            error: "Plan steps must enter progress in order and only one may be current",
          };
        }
        planStatuses.set(args.step_id, "in_progress");
      } else if (args.status === "completed") {
        if (current !== "in_progress") {
          return {
            ok: false,
            error: `Cannot complete ${args.step_id} from status ${current}`,
          };
        }
        planStatuses.set(args.step_id, "completed");
      }
      return {
        ok: true,
        step_id: args.step_id,
        status: planStatuses.get(args.step_id),
        detail: args.detail,
        plan_statuses: Object.fromEntries(planStatuses),
      };
    }
    case "list_files":
      return { ok: true, files: listFiles(args.directory ?? ".") };
    case "read_file":
      return { ok: true, path: args.path, content: readFileSync(safePath(args.path), "utf8") };
    case "write_file": {
      const path = safePath(args.path);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, args.content);
      return { ok: true, path: args.path, bytes_written: Buffer.byteLength(args.content) };
    }
    case "run_tests":
      try {
        const output = execFileSync("cargo", ["test", "--quiet"], {
          cwd: workspace,
          encoding: "utf8",
          timeout: 30_000,
          stdio: ["ignore", "pipe", "pipe"],
        });
        testsPassed = true;
        return { ok: true, command: "cargo test --quiet", output };
      } catch (error) {
        testsPassed = false;
        return {
          ok: false,
          command: "cargo test --quiet",
          stdout: error.stdout ?? "",
          stderr: error.stderr ?? error.message,
        };
      }
    default:
      throw new Error(`Unsupported tool: ${name}`);
  }
}

const planning = await complete([
  {
    role: "system",
    content: `Create a concrete execution plan for a coding agent.
Return JSON only with this schema:
{"goal":"string","steps":[{"id":"short-stable-id","title":"string","success_criteria":"string"}]}
Use 2-6 ordered steps. Do not solve the task and do not claim that tools have run.`,
  },
  { role: "user", content: task },
]);
const plan = parseJsonContent(planning.choice.message.content);
if (!Array.isArray(plan.steps) || plan.steps.length < 2) {
  throw new Error("Model did not produce a usable multi-step plan");
}
const planIds = new Set(plan.steps.map((step) => step.id));
planStatuses = new Map(plan.steps.map((step) => [step.id, "pending"]));

const stepId = {
  type: "string",
  description: "The id of the current step from the approved execution plan",
};
const tools = [
  {
    type: "function",
    function: {
      name: "update_plan",
      description: "Explicitly move one approved plan step into progress or mark it completed",
      parameters: {
        type: "object",
        properties: {
          step_id: stepId,
          status: {
            type: "string",
            enum: ["in_progress", "completed"],
          },
          detail: {
            type: "string",
            description: "Brief evidence or current action for the user-visible plan",
          },
        },
        required: ["step_id", "status", "detail"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "list_files",
      description: "List files in the isolated workspace",
      parameters: {
        type: "object",
        properties: {
          step_id: stepId,
          directory: { type: "string", description: "Workspace-relative directory" },
        },
        required: ["step_id"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_file",
      description: "Read a UTF-8 file from the isolated workspace",
      parameters: {
        type: "object",
        properties: {
          step_id: stepId,
          path: { type: "string", description: "Workspace-relative file path" },
        },
        required: ["step_id", "path"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "write_file",
      description: "Replace a UTF-8 file in the isolated workspace",
      parameters: {
        type: "object",
        properties: {
          step_id: stepId,
          path: { type: "string", description: "Workspace-relative file path" },
          content: { type: "string", description: "Complete replacement content" },
        },
        required: ["step_id", "path", "content"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "run_tests",
      description: "Run the fixed cargo test command in the isolated workspace",
      parameters: {
        type: "object",
        properties: { step_id: stepId },
        required: ["step_id"],
        additionalProperties: false,
      },
    },
  },
];

const messages = [
  {
    role: "system",
    content: `You are executing an approved coding plan in an isolated workspace.
Execute the plan in order. Make exactly one tool call per response.
Every tool call must include the current plan step id as step_id.
Before using another tool for a step, call update_plan to mark it in_progress.
After its success criteria are met, call update_plan again to mark it completed.
Never skip a plan step. For an analysis-only step, explicitly mark it in_progress and completed.
Inspect before editing, run tests after editing, and do not report completion until tests pass.
Approved plan:
${JSON.stringify(plan)}`,
  },
  { role: "user", content: task },
];
const toolEvents = [];
const usedStepIndexes = [];
let batchedToolTurns = 0;
let planRegressions = 0;
let finalMessage = "";
let executionUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };

for (let turn = 0; turn < 24; turn += 1) {
  const result = await complete(messages, tools);
  executionUsage.prompt_tokens += result.usage?.prompt_tokens ?? 0;
  executionUsage.completion_tokens += result.usage?.completion_tokens ?? 0;
  executionUsage.total_tokens += result.usage?.total_tokens ?? 0;
  const message = result.choice.message;
  messages.push(message);
  const calls = message.tool_calls ?? [];
  if (calls.length === 0) {
    finalMessage = message.content ?? "";
    break;
  }
  if (calls.length > 1) {
    batchedToolTurns += 1;
  }
  for (const [batchIndex, call] of calls.entries()) {
    const args = JSON.parse(call.function.arguments || "{}");
    if (!planIds.has(args.step_id)) {
      throw new Error(`Tool call used unknown plan step: ${args.step_id}`);
    }
    const stepIndex = plan.steps.findIndex((step) => step.id === args.step_id);
    if (usedStepIndexes.length > 0 && stepIndex < usedStepIndexes.at(-1)) {
      planRegressions += 1;
    }
    usedStepIndexes.push(stepIndex);
    let output;
    try {
      output = executeTool(call.function.name, args);
    } catch (error) {
      output = { ok: false, error: error.message };
    }
    toolEvents.push({
      turn: turn + 1,
      batch_index: batchIndex,
      batch_size: calls.length,
      step_id: args.step_id,
      tool: call.function.name,
      ok: output.ok,
    });
    messages.push({
      role: "tool",
      tool_call_id: call.id,
      name: call.function.name,
      content: JSON.stringify(output),
    });
  }
}

if (!testsPassed) {
  throw new Error("Agent loop ended without passing tests");
}
if (!finalMessage) {
  throw new Error("Agent loop did not produce a final response");
}
const incompleteSteps = plan.steps.filter(
  (step) => planStatuses.get(step.id) !== "completed",
);
if (incompleteSteps.length > 0) {
  throw new Error(
    `Agent loop ended with incomplete plan steps: ${incompleteSteps.map((step) => step.id).join(", ")}`,
  );
}

const report = {
  endpoint,
  model,
  workspace,
  task,
  plan,
  plan_statuses: Object.fromEntries(planStatuses),
  planning_usage: planning.usage,
  execution_usage: executionUsage,
  tool_events: toolEvents,
  batched_tool_turns: batchedToolTurns,
  plan_regressions: planRegressions,
  tests_passed: testsPassed,
  final_message: finalMessage,
  final_source: readFileSync(join(workspace, "src/lib.rs"), "utf8"),
};
const reportPath = join(workspace, "report.json");
writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({
  model,
  workspace,
  report: reportPath,
  plan_steps: plan.steps.length,
  tool_calls: toolEvents.length,
  batched_tool_turns: batchedToolTurns,
  plan_regressions: planRegressions,
  tests_passed: testsPassed,
  final_message: finalMessage,
}, null, 2));
