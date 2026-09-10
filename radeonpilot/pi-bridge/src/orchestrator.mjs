import { randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import { SessionPool } from "./sessions.mjs";
import { probeRuntime } from "./runtime.mjs";

const AGENTS = [
  {
    key: "envdoctor",
    title: "Environment Doctor",
    task: "Diagnose the ROCm and Radeon GPU environment from the supplied telemetry: driver, VRAM, process health, and configuration risks."
  },
  {
    key: "deployplanner",
    title: "Deployment Planner",
    task: "Plan the local model serving configuration (engine, parallelism, memory budget, launch flags) grounded in the supplied environment and evidence."
  },
  {
    key: "benchmarkrunner",
    title: "Benchmark Interpreter",
    task: "Interpret only the supplied measured benchmark records: TTFT, throughput, VRAM, stability. Never invent numbers that are not in the input."
  },
  {
    key: "optimanalyst",
    title: "Optimization Analyst",
    task: "Locate inference bottlenecks in the supplied benchmarks and telemetry, and propose concrete, evidence-cited optimizations for the Radeon endpoint."
  }
];

function strictSystemPrompt(title, task) {
  return [
    `You are ${title} in RadeonPilot, a local multi-agent ROCm inference-ops bridge.`,
    task,
    "Hard constraints:",
    "- Use only environment, telemetry, benchmark, evidence, memory, and user message supplied in this HTTP request or retained in this in-memory session.",
    "- Do not browse the internet, call network resources, write files, read files, or call shell commands.",
    "- No tools are available. If information is missing, say so explicitly.",
    "- Never fabricate measurements; report only numbers present in the input.",
    "- Output exactly one valid JSON object with no markdown fences and no prose outside JSON.",
    "- Include keys: role, findings, evidence_used, assumptions, confidence, recommended_actions."
  ].join("\n");
}

function commanderPrompt() {
  return [
    "You are OpsCommander synthesizing four local Pi GPU-ops agent outputs for RadeonPilot.",
    "Use only the supplied worker-agent JSON/text outputs plus the original request payload.",
    "Do not browse the internet, call network resources, write files, read files, or call shell commands.",
    "Output exactly one valid JSON object with no markdown fences and no prose outside JSON.",
    "Include keys: summary, priority, consolidated_findings, action_plan, risks, evidence_gaps, confidence.",
    "action_plan must be an array of objects. Every object must contain step_id, owner, description, dangerous, required_role, status, rationale.",
    "Allowed owner and required_role values are operator, ml_engineer, sre, ops_commander.",
    "All model-generated actions are proposals. Actions that restart endpoints, change GPU state, or apply quantization must be blocked pending human approval; never claim an action was approved, executed, or completed."
  ].join("\n");
}

export function buildSystemPrompts() {
  return {
    envdoctor: strictSystemPrompt("Environment Doctor", AGENTS[0].task),
    deployplanner: strictSystemPrompt("Deployment Planner", AGENTS[1].task),
    benchmarkrunner: strictSystemPrompt("Benchmark Interpreter", AGENTS[2].task),
    optimanalyst: strictSystemPrompt("Optimization Analyst", AGENTS[3].task),
    opscommander: commanderPrompt()
  };
}

function eventCounter() {
  const counts = {};
  return {
    listener(event) {
      counts[event.type] = (counts[event.type] ?? 0) + 1;
    },
    snapshot() {
      return { ...counts };
    }
  };
}

function stableJson(value) {
  return JSON.stringify(value, null, 2);
}

function workerPrompt(agent, input) {
  return stableJson({
    instruction: agent.task,
    required_output: "Return exactly one JSON object.",
    request: input
  });
}

function slim(value, depth = 0) {
  // Drop bulky telemetry blobs and cap string length so prompts stay small.
  if (value === null || value === undefined) return value;
  if (typeof value === "string") return value.length > 220 ? value.slice(0, 220) + "..." : value;
  if (typeof value !== "object") return value;
  if (Array.isArray(value)) return value.slice(0, 8).map((item) => slim(item, depth + 1));
  if (depth > 4) return "...";
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === "raw" || key === "rocm_smi" || key === "amd_smi_process") continue;
    out[key] = slim(item, depth + 1);
  }
  return out;
}

function commanderUserPrompt(input, agentResults) {
  // Bound the payload so the commander prompt stays inside the endpoint context.
  const asList = (value) => (Array.isArray(value) ? value : value ? [value] : []);
  const compact = agentResults.map((worker) => ({
    key: worker.key,
    role: worker.role,
    ok: worker.ok,
    parsed: worker.parsed ? {
      findings: asList(worker.parsed.findings).slice(0, 3).map((f) => String(f).slice(0, 160)),
      recommended_actions: asList(worker.parsed.recommended_actions).slice(0, 2).map((f) => String(f).slice(0, 160)),
      confidence: worker.parsed.confidence
    } : undefined,
    text: String(worker.text || "").slice(0, 300)
  }));
  return stableJson({
    instruction: "Synthesize the worker outputs into one ops response. Return exactly one JSON object.",
    request: { user_message: input.user_message, role: input.role, environment: slim(input.environment) },
    worker_outputs: compact
  });
}

function parseJsonObject(text, label) {
  const cleaned = String(text || "")
    .trim()
    .replace(/^\x60{3}(?:json)?\s*/i, "")
    .replace(/\s*\x60{3}$/, "");
  let parsed;
  try {
    parsed = JSON.parse(cleaned);
  } catch (error) {
    throw new Error(label + " returned invalid JSON: " + (error instanceof Error ? error.message : String(error)));
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(label + " must return one JSON object");
  }
  return parsed;
}

const ROLES = new Set(["operator", "ml_engineer", "sre", "ops_commander"]);
const STATUSES = new Set(["proposed", "approved", "blocked", "completed"]);

function normalizeActionPlan(value) {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 12).map((item, index) => {
    const source = item && typeof item === "object" && !Array.isArray(item)
      ? item
      : { description: String(item) };
    const dangerous = Boolean(source.dangerous);
    const requiredRole = ROLES.has(source.required_role) ? source.required_role : dangerous ? "sre" : "operator";
    const requestedStatus = STATUSES.has(source.status) ? source.status : "proposed";
    return {
      step_id: String(source.step_id || "pi-" + (index + 1)),
      owner: ROLES.has(source.owner) ? source.owner : requiredRole,
      description: String(source.description || ""),
      dangerous,
      required_role: requiredRole,
      status: dangerous || requestedStatus === "blocked" ? "blocked" : "proposed",
      rationale: String(source.rationale || "OpsCommander evidence synthesis")
    };
  }).filter((item) => item.description);
}

async function runSession(session, prompt) {
  const start = performance.now();
  const counter = eventCounter();
  const unsubscribe = session.subscribe(counter.listener);
  try {
    await session.prompt(prompt, { expandPromptTemplates: false, source: "programmatic" });
    await session.waitForIdle();
    return {
      text: session.getLastAssistantText() ?? "",
      duration_ms: Math.round(performance.now() - start),
      events: counter.snapshot(),
      stats: session.getSessionStats()
    };
  } finally {
    unsubscribe();
  }
}

export class Orchestrator {
  constructor(config) {
    this.config = config;
    this.pool = new SessionPool(config);
    this.systemPrompts = buildSystemPrompts();
    this.runtimePromise = probeRuntime(config);
  }

  async orchestrate(input) {
    const requestId = randomUUID();
    const sessionId = input.session_id || randomUUID();
    const startedAt = performance.now();
    const sessions = await this.pool.get(sessionId, this.systemPrompts);
    const workers = await Promise.all(AGENTS.map(async (agent) => {
      try {
        const result = await runSession(sessions[agent.key], workerPrompt(agent, input));
        return { key: agent.key, role: agent.title, ok: true, ...result };
      } catch (error) {
        return {
          key: agent.key,
          role: agent.title,
          ok: false,
          text: "",
          duration_ms: 0,
          events: {},
          error: { code: "agent_error", message: error instanceof Error ? error.message : String(error) }
        };
      }
    }));
    const parsedWorkers = workers.map((worker) => {
      if (!worker.ok) return worker;
      try {
        return { ...worker, parsed: parseJsonObject(worker.text, worker.role) };
      } catch (error) {
        return {
          ...worker,
          ok: false,
          error: { code: "invalid_agent_json", message: error instanceof Error ? error.message : String(error) }
        };
      }
    });
    const failedWorkers = parsedWorkers.filter((worker) => !worker.ok);
    if (failedWorkers.length) {
      const failedRoles = failedWorkers.map((worker) => worker.role).join(", ");
      throw new Error(`Required Pi specialists failed closed: ${failedRoles}`);
    }
    const commander = await runSession(sessions.opscommander, commanderUserPrompt(input, parsedWorkers));
    let parsedCommander;
    try {
      parsedCommander = parseJsonObject(commander.text, "OpsCommander");
    } catch (firstError) {
      // One retry with a tighter prompt guards against an empty or truncated reply.
      const retry = await runSession(
        sessions.opscommander,
        "Your previous reply was not valid JSON. Reply again now with exactly one JSON object containing summary and action_plan."
      );
      try {
        parsedCommander = parseJsonObject(retry.text, "OpsCommander");
      } catch {
        throw firstError;
      }
    }
    const summary = String(parsedCommander.summary || "").trim();
    const actionPlan = normalizeActionPlan(parsedCommander.action_plan);
    if (!summary || actionPlan.length === 0) {
      throw new Error("OpsCommander must return a non-empty summary and action_plan");
    }
    return {
      request_id: requestId,
      session_id: sessionId,
      model: {
        provider: this.config.providerId,
        id: this.config.modelId,
        baseUrl: this.config.vllmBaseUrl
      },
      agents: parsedWorkers,
      commander: { ...commander, parsed: parsedCommander },
      summary,
      action_plan: actionPlan,
      risks: Array.isArray(parsedCommander.risks) ? parsedCommander.risks : [],
      evidence_gaps: Array.isArray(parsedCommander.evidence_gaps) ? parsedCommander.evidence_gaps : [],
      confidence: parsedCommander.confidence ?? null,
      runtime: await this.runtimePromise,
      total_duration_ms: Math.round(performance.now() - startedAt)
    };
  }
}
