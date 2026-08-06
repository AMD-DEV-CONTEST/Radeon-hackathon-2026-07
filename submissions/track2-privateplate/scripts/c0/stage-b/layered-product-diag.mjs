#!/usr/bin/env node
/**
 * Layered product diagnostic v2 (protocol / tool / args / domain / product).
 *
 * - Does NOT score with v1 tool names (compose_family_meal etc.).
 * - Saves redacted raw function calls, schema errors, retries, ModelSteps,
 *   ToolTrace, TaskOutcome per turn.
 *
 * Usage:
 *   PRIVATEPLATE_I_CONFIRM_RADEON_RUN=yes \
 *   PRIVATEPLATE_MODEL_ACTIVE=... \
 *   PRIVATEPLATE_RAG_OFFLINE=yes \
 *   node scripts/c0/stage-b/layered-product-diag.mjs
 */
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

export const LAYERED_DIAG_SCHEMA = "layered-diag-2.0";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const baseUrl = process.env.PRIVATEPLATE_VLLM_BASE_URL ?? "http://127.0.0.1:8000/v1";
const model =
  process.env.PRIVATEPLATE_MODEL_ACTIVE ??
  process.env.PRIVATEPLATE_MODEL ??
  "";
if (!model) throw new Error("PRIVATEPLATE_MODEL_ACTIVE required");
if (process.env.PRIVATEPLATE_I_CONFIRM_RADEON_RUN !== "yes") {
  throw new Error("Set PRIVATEPLATE_I_CONFIRM_RADEON_RUN=yes");
}

const runId =
  process.env.PRIVATEPLATE_RUN_ID ??
  `layered-diag-v2-${new Date().toISOString().replace(/[:.]/g, "").slice(0, 15)}`;
const outDir =
  process.env.PRIVATEPLATE_C0B_OUT_DIR ??
  path.join(root, "benchmarks/c0/stage-b", runId);
await mkdir(outDir, { recursive: true });

async function importDist(rel) {
  return import(pathToFileURL(path.join(root, rel)).href);
}

const agentRuntime = await importDist("packages/agent-runtime/dist/index.js");
const domainPkg = await importDist("packages/domain/dist/index.js");
const { PrivatePlateAgent, OpenAiCompatibleToolProvider } = agentRuntime;
const { PrivatePlateDomain } = domainPkg;

/** @type {Array<{role?:string, content?:unknown, tool_calls?:unknown}>} */
let capturedExchanges = [];

const provider = new OpenAiCompatibleToolProvider({
  baseUrl,
  model,
  timeoutMs: Number(process.env.PRIVATEPLATE_REQUEST_TIMEOUT_MS ?? 180_000),
  fetchImpl: async (url, init) => {
    const started = Date.now();
    const res = await fetch(url, init);
    const clone = res.clone();
    let requestBody = null;
    let responseBody = null;
    try {
      requestBody = init?.body ? JSON.parse(String(init.body)) : null;
    } catch {
      requestBody = String(init?.body ?? "").slice(0, 2000);
    }
    try {
      responseBody = await clone.json();
    } catch {
      responseBody = await clone.text().catch(() => null);
    }
    capturedExchanges.push({
      url: String(url),
      status: res.status,
      latency_ms: Date.now() - started,
      request: redactPayload(requestBody),
      response: redactPayload(responseBody)
    });
    return res;
  }
});

/** v2-only scenarios — never expect v1 tools. */
const scenarios = [
  {
    id: "L1-plan-no-chicken",
    turns: [
      {
        text: "规划午餐，不要鸡腿。我们三个人一起吃。",
        expect_tools: ["finalize_meal_plan"],
        optional_tools: ["get_day_context", "find_dish_candidates"]
      }
    ]
  },
  {
    id: "L2-inspect-day",
    turns: [
      {
        text: "查看今天的家庭额度、库存和成员情况。",
        expect_tools: ["get_day_context"]
      }
    ]
  },
  {
    id: "L3-plan-then-handoff",
    turns: [
      {
        text: "中午我们三个人吃什么？不要鸡腿。",
        expect_tools: ["finalize_meal_plan"],
        optional_tools: ["get_day_context", "find_dish_candidates"]
      },
      {
        text: "发给保姆",
        expect_tools: ["preview_caregiver_task"],
        optional_tools: [
          "get_day_context",
          "find_dish_candidates",
          "finalize_meal_plan"
        ]
      }
    ]
  },
  {
    id: "L4-rag-disclosure",
    turns: [
      {
        text: "任务卡能不能写疾病名？为什么要最小披露？",
        expect_tools: ["retrieve_local_knowledge"]
      }
    ]
  },
  {
    id: "L5-restock-tofu",
    turns: [
      {
        text: "刚买了两盒豆腐，帮我记入库。",
        expect_tools: ["preview_inventory_change"]
      }
    ]
  }
];

function redactPayload(value) {
  if (value == null) return value;
  if (typeof value === "string") {
    return value.length > 4000 ? `${value.slice(0, 4000)}…` : value;
  }
  if (Array.isArray(value)) return value.map(redactPayload);
  if (typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      if (/token|authorization|api[_-]?key|password/i.test(k)) {
        out[k] = "[redacted]";
      } else {
        out[k] = redactPayload(v);
      }
    }
    return out;
  }
  return value;
}

function extractFunctionCalls(exchanges) {
  const calls = [];
  for (const ex of exchanges) {
    const choices = ex.response?.choices;
    if (!Array.isArray(choices)) continue;
    for (const ch of choices) {
      const msg = ch.message ?? ch.delta ?? {};
      const tcs = msg.tool_calls ?? msg.function_call;
      if (Array.isArray(tcs)) {
        for (const tc of tcs) {
          calls.push({
            id: tc.id ?? null,
            name: tc.function?.name ?? tc.name ?? null,
            arguments: safeParse(tc.function?.arguments ?? tc.arguments)
          });
        }
      } else if (tcs && typeof tcs === "object") {
        calls.push({
          id: null,
          name: tcs.name ?? null,
          arguments: safeParse(tcs.arguments)
        });
      }
    }
  }
  return calls;
}

function safeParse(v) {
  if (v == null) return null;
  if (typeof v === "object") return redactPayload(v);
  try {
    return redactPayload(JSON.parse(String(v)));
  } catch {
    return String(v).slice(0, 2000);
  }
}

function toolsExecuted(toolTrace) {
  return (toolTrace ?? []).filter((t) => t.ok).map((t) => t.tool);
}

function toolsAttempted(toolTrace) {
  return (toolTrace ?? []).map((t) => t.tool);
}

function detectProtocolFailure(turn) {
  const answer = String(turn.answer ?? "");
  const reasons = [];
  if (/未通过结构协议|结构协议|安全停止|原生 function call/.test(answer)) {
    reasons.push("answer_mentions_protocol_stop");
  }
  if (turn.phase === "SAFE_STOP" || turn.phase === "ERROR") {
    reasons.push(`phase_${turn.phase}`);
  }
  for (const step of turn.modelSteps ?? []) {
    if (step.format_retry_reasons?.length) {
      reasons.push(`format_retry:${step.format_retry_reasons.join("|")}`);
    }
  }
  const mt = turn.modelTrace;
  if (mt?.format_retry_reasons?.length) {
    reasons.push(`trace_format_retry:${mt.format_retry_reasons.join("|")}`);
  }
  return [...new Set(reasons)];
}

function scoreTurn(turnSpec, turn) {
  const executed = toolsExecuted(turn.toolTrace);
  const attempted = toolsAttempted(turn.toolTrace);
  const protocolReasons = detectProtocolFailure(turn);
  const expect = turnSpec.expect_tools ?? [];

  // Recovered protocol: tools succeeded and no hard ERROR stop.
  const hardStop =
    turn.phase === "ERROR" ||
    turn.phase === "SAFE_STOP" ||
    /未通过结构协议/.test(String(turn.answer ?? ""));
  const hadRetry = protocolReasons.some((r) => r.includes("format_retry"));
  const protocol_ok = !hardStop;

  const tool_ok =
    protocol_ok &&
    expect.every((t) => executed.includes(t) || attempted.includes(t));

  const failedTools = (turn.toolTrace ?? []).filter((t) => !t.ok);
  const args_ok =
    tool_ok &&
    !failedTools.some((t) => t.code === "VALIDATION_ERROR");

  const domain_ok =
    args_ok &&
    expect.every((t) =>
      (turn.toolTrace ?? []).some((x) => x.tool === t && x.ok)
    );

  const product_ok = domain_ok && turn.validationOk !== false;

  const layers = {
    protocol_ok,
    tool_ok: Boolean(tool_ok),
    args_ok: Boolean(args_ok),
    domain_ok: Boolean(domain_ok),
    product_ok: Boolean(product_ok),
    protocol_recovered_after_retry: hadRetry && protocol_ok && executed.length > 0
  };

  let primary_fail = null;
  for (const key of [
    "protocol_ok",
    "tool_ok",
    "args_ok",
    "domain_ok",
    "product_ok"
  ]) {
    if (!layers[key]) {
      primary_fail = key.replace(/_ok$/, "");
      break;
    }
  }

  return {
    ...layers,
    primary_fail,
    protocol_reasons: protocolReasons,
    executed_tools: executed,
    attempted_tools: attempted,
    expected_tools: expect,
    phase: turn.phase,
    validationOk: turn.validationOk === true,
    answer_preview: String(turn.answer ?? "").slice(0, 400),
    failed_tools: failedTools.map((t) => ({ tool: t.tool, code: t.code ?? null })),
    taskOutcome: turn.taskOutcome ?? null,
    modelSteps: turn.modelSteps ?? null,
    toolTrace: turn.toolTrace ?? null
  };
}

const caseRows = [];
console.log(
  JSON.stringify({ start: true, schema: LAYERED_DIAG_SCHEMA, model, baseUrl, outDir }, null, 2)
);

for (const scenario of scenarios) {
  const domain = await PrivatePlateDomain.create(":memory:");
  const agent = new PrivatePlateAgent(domain, `layered-${scenario.id}`, provider);
  const turns = [];
  for (const turnSpec of scenario.turns) {
    capturedExchanges = [];
    const t0 = performance.now();
    let turn;
    let error = null;
    try {
      turn = await agent.handleUserMessage(turnSpec.text);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      turn = {
        phase: "ERROR",
        answer: error,
        toolTrace: [],
        modelSteps: [],
        validationOk: false,
        taskOutcome: null
      };
    }
    const score = scoreTurn(turnSpec, turn);
    const function_calls = extractFunctionCalls(capturedExchanges);
    turns.push({
      user_text: turnSpec.text,
      latency_ms: Math.round(performance.now() - t0),
      error,
      function_calls,
      provider_exchanges: capturedExchanges,
      schema_errors: (turn.modelSteps ?? [])
        .flatMap((s) => s.format_retry_reasons ?? [])
        .filter(Boolean),
      ...score
    });
    console.log(
      `[${scenario.id}] primary=${score.primary_fail ?? "PASS"} tools=${score.executed_tools.join(",") || "-"} phase=${score.phase}`
    );
  }
  const primaries = turns.map((t) => t.primary_fail).filter(Boolean);
  caseRows.push({
    case_id: scenario.id,
    protocol: "v2",
    status: primaries.length === 0 ? "PASS" : "FAIL",
    primary_fails: primaries,
    turns
  });
  domain.close();
}

const failCount = caseRows.filter((c) => c.status !== "PASS").length;
const byLayer = { protocol: 0, tool: 0, args: 0, domain: 0, product: 0 };
for (const c of caseRows) {
  for (const t of c.turns) {
    if (t.primary_fail && byLayer[t.primary_fail] != null) byLayer[t.primary_fail] += 1;
  }
}

const summary = {
  schema_version: LAYERED_DIAG_SCHEMA,
  protocol: "v2",
  run_id: runId,
  model,
  base_url: baseUrl,
  status: failCount === 0 ? "PASS" : "FAIL",
  sample_count: caseRows.length,
  failed_cases: failCount,
  turn_primary_fail_counts: byLayer,
  claim_boundary:
    "v2-only scoring. Never uses v1 tool names. primary_fail = first broken layer among protocol→tool→args→domain→product. Raw exchanges redacted and stored in jsonl.",
  cases: caseRows.map((c) => ({
    case_id: c.case_id,
    status: c.status,
    primary_fails: c.primary_fails,
    turns: c.turns.map((t) => ({
      user_text: t.user_text,
      primary_fail: t.primary_fail,
      protocol_ok: t.protocol_ok,
      protocol_recovered_after_retry: t.protocol_recovered_after_retry,
      tool_ok: t.tool_ok,
      args_ok: t.args_ok,
      domain_ok: t.domain_ok,
      product_ok: t.product_ok,
      executed_tools: t.executed_tools,
      function_calls: t.function_calls,
      schema_errors: t.schema_errors,
      phase: t.phase,
      protocol_reasons: t.protocol_reasons,
      answer_preview: t.answer_preview,
      latency_ms: t.latency_ms,
      taskOutcome: t.taskOutcome
    }))
  }))
};

await writeFile(
  path.join(outDir, "layered-diag-summary.json"),
  `${JSON.stringify(summary, null, 2)}\n`
);
await writeFile(
  path.join(outDir, "layered-diag.jsonl"),
  `${caseRows.map((r) => JSON.stringify(r)).join("\n")}\n`
);
// Also dump full turns with modelSteps/toolTrace for offline debug
await writeFile(
  path.join(outDir, "layered-diag-full.json"),
  `${JSON.stringify({ schema_version: LAYERED_DIAG_SCHEMA, cases: caseRows }, null, 2)}\n`
);
console.log(JSON.stringify(summary, null, 2));
console.log(`wrote ${outDir}`);
if (failCount > 0) process.exitCode = 2;
