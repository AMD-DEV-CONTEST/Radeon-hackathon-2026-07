import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  NativePiExportError,
  exportNativePiSample,
} from "../src/native_pi_export.mjs";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const TOOL_PARAMETERS = {
  read: {
    type: "object",
    properties: { path: { type: "string" } },
    required: ["path"],
    additionalProperties: false,
  },
  grep: {
    type: "object",
    properties: { pattern: { type: "string" }, path: { type: "string" } },
    required: ["pattern"],
    additionalProperties: false,
  },
  find: {
    type: "object",
    properties: { pattern: { type: "string" }, path: { type: "string" } },
    required: ["pattern"],
    additionalProperties: false,
  },
  ls: {
    type: "object",
    properties: { path: { type: "string" } },
    additionalProperties: false,
  },
  bash: {
    type: "object",
    properties: { command: { type: "string" }, timeout: { type: "number" } },
    required: ["command"],
    additionalProperties: false,
  },
};

function tools() {
  return Object.entries(TOOL_PARAMETERS).map(([name, parameters]) => ({
    type: "function",
    function: {
      name,
      description: `Native Pi ${name} tool.`,
      parameters,
    },
  }));
}

function fixture() {
  const system = "You are pi, a coding agent. Use the native tools and report observed evidence.";
  const instruction = "请在真实开发板上检查根分区容量，并依据返回结果作答。";
  const call = {
    id: "call_provider_real_7f3",
    type: "function",
    function: { name: "bash", arguments: JSON.stringify({ command: "df -h /" }) },
  };
  const firstMessages = [
    { role: "system", content: system },
    { role: "user", content: [{ type: "text", text: instruction }] },
  ];
  const finalInputMessages = [
    ...firstMessages,
    { role: "assistant", content: null, tool_calls: [call] },
    {
      role: "tool",
      tool_call_id: call.id,
      content: "Filesystem Size Used Avail Use% Mounted on\n/dev/root 29G 12G 16G 44% /",
    },
  ];
  const providerPayloads = [
    { model: "teacher", stream: true, messages: firstMessages, tools: tools() },
    { model: "teacher", stream: true, messages: finalInputMessages, tools: tools() },
  ];
  const piMessages = [
    { role: "user", content: [{ type: "text", text: instruction }], timestamp: 1 },
    {
      role: "assistant",
      content: [{ type: "toolCall", id: call.id, name: "bash", arguments: { command: "df -h /" } }],
      stopReason: "toolUse",
      timestamp: 2,
    },
    {
      role: "toolResult",
      toolCallId: call.id,
      toolName: "bash",
      content: [
        {
          type: "text",
          text: "Filesystem Size Used Avail Use% Mounted on\n/dev/root 29G 12G 16G 44% /",
        },
      ],
      isError: false,
      timestamp: 3,
    },
    {
      role: "assistant",
      content: [{ type: "text", text: "开发板根分区总容量 29G，已用 12G，可用 16G，使用率 44%。" }],
      stopReason: "stop",
      timestamp: 4,
    },
  ];
  return {
    task: {
      task_id: "agent_000001",
      profile: "agentic",
      split: "train",
      instruction,
      metadata: { source: "pi_native_board", semantic_group_id: "board_disk_capacity" },
    },
    providerPayloads,
    piMessages,
    policyAudit: [
      {
        tool_call_id: call.id,
        tool_name: "bash",
        decision: "allow",
        requested_arguments: { command: "df -h /" },
        effective_args: { command: "/immutable/native_board_cli --action disk_root" },
      },
    ],
    boardEvidence: [
      {
        schema_version: "rdk_pi_native_board_dispatch.v1",
        tool_call_id: call.id,
        dispatch_id: "a".repeat(32),
        requested_command: "df -h /",
        action: "disk_root",
        executed: true,
        transport: "ssh",
        evidence_source: "native_board_cli",
        status: "observed",
        exit_code: 0,
        timed_out: false,
        stdout_sha256: "b".repeat(64),
        stderr_sha256: "c".repeat(64),
        evidence_path: "/isolated/canary/board/a.json",
      },
    ],
    metadata: { run_id: "native-canary-test", pi_version: "0.83.0" },
  };
}

test("exports the provider-visible native Pi trajectory without remapping call ids", () => {
  const { sample, audit } = exportNativePiSample(fixture());
  assert.equal(sample.messages[0].content.startsWith("You are pi"), true);
  assert.deepEqual(
    sample.tools.map((tool) => tool.function.name),
    ["read", "grep", "find", "ls", "bash"],
  );
  assert.equal(sample.messages[2].tool_calls[0].id, "call_provider_real_7f3");
  assert.deepEqual(sample.messages[2].tool_calls[0].function.arguments, { command: "df -h /" });
  assert.equal(
    sample.messages[3].content,
    "Filesystem Size Used Avail Use% Mounted on\n/dev/root 29G 12G 16G 44% /",
  );
  assert.equal(sample.messages.at(-1).content, sample.outcome.final_answer);
  assert.equal(sample.metadata.behavior_origin, "pi-coding-agent-native");
  assert.equal(sample.metadata.provider_round_count, 2);
  assert.equal(audit.accepted, true);
  assert.match(audit.sample_sha256, /^[a-f0-9]{64}$/);
});

test("rejects dynamic provider tool schemas", () => {
  const input = fixture();
  input.providerPayloads[1].tools[0].function.description = "changed at round two";
  assert.throws(
    () => exportNativePiSample(input),
    (error) => error instanceof NativePiExportError && error.code === "dynamic_tool_schema",
  );
});

test("records an identical Pi provider retry as an HTTP attempt, not a causal round", () => {
  const input = fixture();
  input.providerPayloads.push(structuredClone(input.providerPayloads.at(-1)));
  const { sample } = exportNativePiSample(input);
  assert.equal(sample.metadata.provider_round_count, 2);
  assert.equal(sample.metadata.provider_request_attempt_count, 3);
  assert.equal(sample.metadata.provider_retry_attempt_count, 1);
});

test("rejects replayed reasoning, errors, and blocked policy decisions", () => {
  const developer = fixture();
  developer.providerPayloads[0].messages[0].role = "developer";
  assert.throws(
    () => exportNativePiSample(developer),
    (error) => error instanceof NativePiExportError && error.code === "developer_role",
  );

  const replayedThinking = fixture();
  replayedThinking.providerPayloads[1].messages[2].reasoning_content = "private chain";
  assert.throws(
    () => exportNativePiSample(replayedThinking),
    (error) => error instanceof NativePiExportError && error.code === "thinking_content",
  );

  const outputOnlyThinking = fixture();
  outputOnlyThinking.piMessages[1].content.unshift({ type: "thinking", thinking: "tool reasoning" });
  outputOnlyThinking.piMessages.at(-1).content.unshift({ type: "thinking", thinking: "final reasoning" });
  const { sample } = exportNativePiSample(outputOnlyThinking);
  assert.equal(sample.metadata.omitted_thinking_block_count, 2);
  assert.equal(sample.messages.some((message) => message.content.includes?.("reasoning")), false);

  const toolError = fixture();
  toolError.piMessages[2].isError = true;
  assert.throws(
    () => exportNativePiSample(toolError),
    (error) => error instanceof NativePiExportError && error.code === "tool_error",
  );

  const blocked = fixture();
  blocked.policyAudit[0].decision = "deny";
  blocked.policyAudit[0].blocked = true;
  assert.throws(
    () => exportNativePiSample(blocked),
    (error) => error instanceof NativePiExportError && error.code === "blocked_or_failed_policy",
  );
});

test("rejects board bash calls without exact SSH execution evidence", () => {
  const missing = fixture();
  missing.boardEvidence = [];
  assert.throws(
    () => exportNativePiSample(missing),
    (error) => error instanceof NativePiExportError && error.code === "board_evidence_count",
  );

  const wrongCommand = fixture();
  wrongCommand.boardEvidence[0].requested_command = "uptime";
  assert.throws(
    () => exportNativePiSample(wrongCommand),
    (error) => error instanceof NativePiExportError && error.code === "board_evidence_mismatch",
  );
});

test("independent native dataset validator accepts the exported sample and scans every artifact", () => {
  const temporaryRoot = mkdtempSync(resolve(tmpdir(), "native-pi-export-test-"));
  try {
    const input = fixture();
    input.providerPayloads.push(structuredClone(input.providerPayloads.at(-1)));
    const { sample } = exportNativePiSample(input);
    const datasetPath = resolve(temporaryRoot, "sample.jsonl");
    writeFileSync(datasetPath, `${JSON.stringify(sample)}\n`, "utf8");
    const result = spawnSync(
      resolve(PROJECT_ROOT, "scripts/python.sh"),
      [
        resolve(PROJECT_ROOT, "scripts/validate_native_pi_dataset.py"),
        datasetPath,
        "--schema",
        resolve(PROJECT_ROOT, "schemas/rdk_sft_sample.v1.schema.json"),
        "--scan-root",
        temporaryRoot,
      ],
      { cwd: PROJECT_ROOT, encoding: "utf8" },
    );
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    const audit = JSON.parse(result.stdout);
    assert.equal(audit.valid, true);
    assert.equal(audit.secret_scan.files, 1);
    assert.equal(audit.counts.rows, 1);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
});
