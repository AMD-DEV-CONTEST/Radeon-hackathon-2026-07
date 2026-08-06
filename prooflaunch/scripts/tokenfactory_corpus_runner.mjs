import crypto from "node:crypto";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");


const CDP_URL = "http://127.0.0.1:9222";
const CHAT_URL =
  "https://developer.amd.com.cn/radeon/api/v1/chat/completions";
const USAGE_URL =
  "https://developer.amd.com.cn/radeon/api/profile/model-usage?include_recent=false";
const PROFILE_FRAGMENT = "/radeon/profile";
const TASK_PATTERN =
  /^(\d{4})\s+\[D\/A\/I\/E\](?:\[([TPX])\])?\s+(.+?)[。.]?\s*$/;
const BATCH_SIZE = 2;
const SAFE_RPM = 12;
const MAX_IN_FLIGHT = 6;
const MAX_PIPELINE_BATCHES = SAFE_RPM * 3;
const START_INTERVAL_MS = Math.ceil(60000 / SAFE_RPM);
const DEFAULT_STOP_REMAINING_USD = 0.0001;
const CONSERVATIVE_MAX_CALL_COST_USD = 0.003;
const MINIMUM_HEALTHY_CHUNK_PASS_RATE = 0.5;
const QUALITY_PROTOCOL_VERSION = "frontier-20-lens-v3";
const SYNTHESIS_REQUIRED_FIELDS = Object.freeze([
  "todo_id",
  "dependencies",
  "D",
  "A",
  "I",
  "E",
  "implementation_steps",
  "test_ids",
  "acceptance_metrics",
  "budget",
  "stop_rule",
  "rollback",
  "evidence_class",
  "radeon_action",
  "external_blockers",
  "current_status",
]);
const FOUR_A_TRANSFER_REQUIRED_FIELDS = Object.freeze([
  "todo_id",
  "reference_case_ids",
  "observed_evidence",
  "strategic_transfer",
  "creative_mechanism",
  "channel_and_craft",
  "effectiveness_test",
  "negative_control",
  "what_not_to_copy",
  "rights_partition",
  "admission_status",
]);
const FOUR_A_REFERENCE_CASE_IDS = new Set([
  "os26-ce001g",
  "os26-fi093m",
  "os26-ce002g",
  "os26-ce003g",
  "os26-ce014m",
  "os26-ce010b",
  "os26-ce021m",
  "os26-mi026b",
  "os26-mi003g",
  "os26-be037m",
  "os26-dm049m",
  "os26-dm000g",
  "os26-mi042m",
  "OS26_CE001G",
  "OS26_FI093M",
  "OS26_CE002G",
  "OS26_CE003G",
  "OS26_CE014M",
  "OS26_CE010B",
  "OS26_CE021M",
  "OS26_MI026B",
  "OS26_MI003G",
  "OS26_BE037M",
  "OS26_DM049M",
  "OS26_DM000G",
  "OS26_MI042M",
]);

const FRONTIER_QUALITY_PROTOCOL = [
  "Apply the frozen 20-lens public-method protocol across all 1500 tasks. Research lenses:",
  "world/latent-state modelling, search and self-improvement, spatial intelligence,",
  "sparse hardware-aware specialization, native multimodal curricula, rich-feedback",
  "adaptation, offline/interactive learning, and multidimensional reproducible evaluation.",
  "Product lenses: durable state, bounded specialists, direct manipulation, end-to-end",
  "content supply chains, sandboxed tools, explicit approval, rollback, and observed GTM",
  "outcomes. These are transferable public methods, never endorsements or simulated personas.",
  "For each task: (1) name the mature upstream mechanism to reuse, its pinned source/license",
  "and the integration seam; (2) freeze the strongest relevant baseline; (3) state the",
  "non-obvious mechanism delta and why it is not generic multi-agent orchestration, prompt",
  "wrapping, routine LoRA/SFT, more tokens, or UI veneer; (4) define an ablation, negative",
  "control, adversarial case, metric, cost, stop rule, and rollback; (5) name the user-visible",
  "4A GTM behavior whose difference can be judged blind. Score technical delta, GTM craft",
  "delta, falsifiability, and multi-GPU Radeon feasibility/equivalence from 0-5. A proposal below 16/20",
  "or below 3 on any axis must be HOLD/REJECT and repaired, not marketed as innovation.",
  "Compliance, provenance, safety, and administrative tasks may be classified as",
  "non-innovation foundations; execute them rigorously but do not game the innovation score",
  "by adding irrelevant machinery. The 16/20 gate applies only when promoting a mechanism",
  "as a breakthrough.",
  "Placeholder repositories, revisions, licenses, datasets, metrics, and source URLs are",
  "invalid evidence. If a required authoritative source is not supplied, explicitly mark",
  "the record HOLD for source capture; do not award a passing innovation score. Self-scoring",
  "is only a proposal for later blinded review, never proof that the gate passed.",
  "Never force novelty where evidence is weak. A falsified bet with sealed negative evidence",
  "is higher quality than an unfalsifiable 'wow' claim.",
].join(" ");

const OFFICIAL_TRACK_CONTEXT = [
  "Authoritative frozen sources already captured by the project:",
  "https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md and",
  "https://modelscope.cn/events/299/比赛介绍.",
  "Local audit evidence/OFFICIAL_TRACK1_RULES_AUDIT_2026-07-30.json binds the raw",
  "official repository to Git commit 67b26aba27ff24e20b7a42232c86182d0f249a4f, the",
  "README bytes to SHA-256 0aff99d7aa46390c614107027487afe4e9399a7e1a28aae7f9bd83effea560e6",
  "and the ModelScope competition payload to SHA-256",
  "75941378bc87da6da15ca2c7e7c22e476acefdebbd0e0b739d3e0aab3629c2d1.",
  "Observed administration: register through the published Luma flow by",
  "2026-08-05 23:59 UTC+8; submit by 2026-08-06 23:59 UTC+8; each team has at most",
  "three members; participants must join the AMD Developer Program.",
  "Observed Track 1 deliverables: English submission materials; Project Profile PDF with",
  "background, users/scenarios, architecture, model/algorithm and Radeon/ROCm adaptation;",
  "complete source; README with environment/startup/dependencies; recommended 3-5 minute",
  "actual-operation and actual-Radeon demo; one PPT or poster; fork the official repository",
  "and open an English PR titled in the Track 1, Team, application-name format.",
  "Observed scoring: 40 points workflow integrity, 20 innovation/fun, 20 practical or social",
  "value, and 20 Radeon clarity, stability, and diversity. At least one key inference must",
  "run locally on Radeon; the core workflow cannot rely only on a closed online API.",
  "The local audit still blocks the demo and PR until a real Radeon run exists. The official",
  "rules do not make Token Factory spend, KV-cache hits, LoRA, ControlNet, or distillation",
  "mandatory submission gates; do not invent such requirements.",
].join(" ");

const MULTI_GPU_CONTEXT = [
  "Frozen multi-GPU execution policy: all 1,500 TODOs bind to one supervisor-owned",
  "multi-GPU DAG; 1,100 compute-bearing TODOs require real >=2-GPU ROCm/RCCL runtime,",
  "single-GPU equivalence, per-rank receipts, and measured efficiency. The other 400",
  "participate in dependency barriers and atomic commits without fake GPU work. Training",
  "uses DDP after memory-fit preflight and FSDP2 only as the verified memory fallback;",
  "device_map=auto is forbidden for training. World size and global batch are frozen, rank",
  "loss or duplicate/missing shards aborts, and dependency-ordered training stages remain",
  "sequential while ranks shard work inside a stage. The current authenticated template",
  "output reports torch.cuda.device_count() == 1, so all direct multi-GPU claims remain",
  "not_started until a different >=2-GPU Radeon environment passes the RCCL preflight.",
].join(" ");

const FOUR_A_DISTILLATION_CONTEXT = [
  "Frozen public research references, captured 2026-07-30 from The One Club for",
  "Creativity and stored without raw campaign assets:",
  "OS26_CE001G Can't Unsee It by Rethink Toronto for Kraft Heinz,",
  "https://www.oneclub.org/awards/theoneshow/-award/63776/cant-unsee-it/;",
  "OS26_CE002G Preserved Promos by VML New York for Ziploc,",
  "https://www.oneclub.org/awards/theoneshow/-award/63777/preserved-promos/;",
  "OS26_CE003G U up? by Rethink Toronto for IKEA,",
  "https://www.oneclub.org/awards/theoneshow/-award/63778/u-upa/;",
  "OS26_CE014M See My Name by Rethink Toronto for Molson Coors,",
  "https://www.oneclub.org/awards/theoneshow/-award/63789/see-my-name/;",
  "OS26_CE010B Kleenex Score by VML New York, /-award/63852/kleenex-score/;",
  "OS26_FI093M Kyikatejê by Area 23 New York, /-award/64206/kyikatej/;",
  "OS26_CE021M Kyle F*cking Connor by Courage Toronto, /-award/64451/kyle-fcking-connor/;",
  "OS26_MI026B The Count by FCB Canada Toronto, /-award/64548/the-count/;",
  "OS26_MI003G 18 Months by Klick Health Toronto, /-award/64525/18-months/;",
  "OS26_BE037M Someday by TBWA Media Arts Lab Los Angeles, /-award/63629/someday/;",
  "OS26_DM049M Abracadabra: From Fan to Featured by McCann New York,",
  "/-award/64031/abracadabra-from-fan-to-featured/;",
  "OS26_DM000G Vaseline Verified by Ogilvy New York, /-award/63982/vaseline-verified/;",
  "OS26_MI042M Wake Up by Droga5 New York, /-award/64564/wake-up/.",
  "Every relative locator above resolves under https://www.oneclub.org/awards/theoneshow",
  "These thirteen 16-layer abstractions cover all ten frozen reference agencies. Their",
  "mechanisms include: convert a brand promise into transaction infrastructure; align",
  "need-state timing and conversion; turn sponsorship inventory into system improvement;",
  "turn distinctive brand memory into participatory recognition; build a trusted",
  "micro-utility at the moment an adjacent need becomes predictable;",
  "make a missing institutional role an accountable support pathway; encode cultural",
  "permission into an operating system; translate an institutional milestone into the",
  "next human outcome; make an invisible process legible through respectful temporal",
  "metaphor; make product value felt through participatory entertainment; turn a sponsored",
  "moment into a governed participation ladder; return domain authority as a transparent",
  "verification loop; and externalize category passivity so product behavior resolves it.",
  "Treat these",
  "as source-bound research abstractions, never templates to copy. Campaign titles, exact",
  "copy, brand identities, offers, layouts, footage, audio, garment designs, and distinctive",
  "execution remain non-transferable reference specifics. Award status is not causal",
  "business-effect proof. Public metadata does not authorize training. The complete gate",
  "requires 300 distinct cases, 30 per each of ten date-pinned North-American reference",
  "agencies, at least five channels per agency, all sixteen distillation layers, zero",
  "identity duplicates, and zero sealed-evaluation overlap. Current seed evidence is below",
  "that gate, so every output remains research_only or HOLD.",
].join(" ");

const STAGES = Object.freeze({
  architect: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.25,
    prerequisites: [],
    instruction:
      "Act as a frontier multimodal systems architect. For every task, produce a " +
      "strict D/A/I/E execution specification: upstream reuse/distillation, falsifiable " +
      "academic hypothesis and controls, genuinely differentiating mechanism, exact " +
      "implementation artifact, named automated test, metric, stop/elimination rule, " +
      "Radeon constraint, dependency, and truth boundary. Do not claim the task is " +
      "complete. Prefer concrete interfaces, schemas, commands, and failure cases.",
  },
  research: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.2,
    prerequisites: [],
    instruction:
      "Act as a skeptical 2026 research lead. For every task, identify reusable open " +
      "implementations, the most relevant public research mechanism, license/ROCm risks, " +
      "a frozen baseline, ablations, negative controls, falsifiers, data requirements, " +
      "and the smallest experiment that can disprove the proposed innovation. Never " +
      "invent a paper result, revision, benchmark score, human rating, or Radeon trace.",
  },
  critic: {
    model: "DeepSeek-V4-Flash",
    maxTokens: 2048,
    temperature: 0.1,
    prerequisites: ["architect", "research"],
    instruction:
      "Act as an adversarial reviewer. Compare the two candidate plans task by task. " +
      "Find missing D/A/I/E axes, unverifiable claims, fake completion risks, duplicated " +
      "work, weak baselines, leakage, license issues, impossible multi-GPU Radeon/RCCL assumptions, " +
      "and ambiguous acceptance criteria. Return precise required corrections and a " +
      "pass/block decision for execution readiness only, never for task completion.",
  },
  implementer: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.15,
    prerequisites: ["critic"],
    instruction:
      "Act as the implementation lead. Repair every issue in the adversarial review and " +
      "produce a build-ready specification for each task: typed contract, file/module, " +
      "algorithm, deterministic fixture, positive and negative tests, evidence locator, " +
      "runtime budget, rollback, and explicit closure condition. Separate local mechanism " +
      "proof from trained-model, human, business, 4K, and Radeon outcome evidence.",
  },
  verifier: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0,
    prerequisites: ["implementer"],
    instruction:
      "Act as a deterministic evidence verifier. For every task, convert the implementation " +
      "plan into a machine-checkable acceptance checklist with exact inputs, assertions, " +
      "negative tests, hashes/receipts, leakage checks, quota limits, and fail-closed " +
      "conditions. Return one compact record per todo_id. Mark any criterion that requires " +
      "external human, training, business, 4K, or Radeon observation as externally blocked " +
      "rather than inferred.",
  },
  four_a_critic: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.25,
    prerequisites: ["implementer", "verifier"],
    instruction:
      "Act as a North American 4A GTM product and craft reviewer. For every task, test " +
      "whether the mechanism changes real agency work, improves strategy/creative craft, " +
      "preserves claims and brand, and can be judged blind. Specify the user-visible " +
      "behavior, expert rubric, failure examples, publishability gate, and evidence needed. " +
      "Reject feature theater and unobserved uplift claims.",
  },
  synthesis: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.1,
    prerequisites: ["implementer", "verifier", "four_a_critic"],
    instruction:
      "Act as the final execution compiler. Synthesize the supplied implementation, " +
      "verification, and 4A reviews into one lossless record per task. Each record must " +
      "contain todo_id, dependencies, D, A, I, E, implementation_steps, test_ids, " +
      "acceptance_metrics, budget, stop_rule, rollback, evidence_class, radeon_action, " +
      "external_blockers, and a truthful current_status that remains not_started or " +
      "in_progress until named evidence exists. Return strict JSON only as " +
      "{\"records\":[...]} with no Markdown fence or prose. Do not output hidden reasoning.",
  },
  frontier_judge: {
    model: "DeepSeek-V4-Flash",
    maxTokens: 2048,
    temperature: 0.05,
    prerequisites: ["synthesis"],
    instruction:
      "Act as an independent frontier admission judge. Red-team every synthesized task " +
      "against the 20-lens protocol. Reject generic agent orchestration, routine prompt/SFT/" +
      "LoRA work presented as novelty, unpinned or invented sources, circular self-scores, " +
      "unmeasured 4A/product claims, missing ablations, impossible multi-GPU Radeon/RCCL budgets, " +
      "and evidence-class substitution. Return exact blocking defects, required repair, " +
      "and ADMIT_FOR_EXECUTION or REJECT. Admission never means task completion.",
  },
  final_repair: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.05,
    prerequisites: ["synthesis", "frontier_judge"],
    instruction:
      "Act as the final fail-closed execution-record repairer. Apply every independent " +
      "judge correction. Preserve rejected or externally blocked bets as HOLD semantics " +
      "inside current_status not_started; never delete a falsifier or invent a source. " +
      "Return strict JSON only as {\"records\":[...]} with one record per task and fields " +
      "todo_id, dependencies, D, A, I, E, implementation_steps, test_ids, " +
      "acceptance_metrics, budget, stop_rule, rollback, evidence_class, radeon_action, " +
      "external_blockers, current_status. No Markdown fence, prose, or hidden reasoning.",
  },
  four_a_deep_strategy: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.2,
    prerequisites: ["final_repair"],
    instruction:
      "Act as a senior 4A strategy distiller. For each TODO, bind one or more supplied " +
      "reference case IDs only when the mechanism genuinely applies. Separate observed " +
      "source facts from inference. Reconstruct the business problem, audience job, " +
      "evidence tension, rejected obvious route, strategy choice, Big-Idea mechanism, " +
      "and brand role. State the exact GTM transfer and what must not be copied. If none " +
      "of the three references fits, return HOLD_FOR_MORE_SOURCES rather than force-fit.",
  },
  four_a_deep_craft: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.2,
    prerequisites: ["final_repair", "four_a_deep_strategy"],
    instruction:
      "Act as an executive creative director and production systems lead. For each TODO, " +
      "turn the strategy transfer into a channel system, experience/tool mechanism, craft " +
      "grammar, multimodal artifact contract, production constraints, accessibility and " +
      "brand gates. Include at least one anti-pattern and a blind craft comparison. Never " +
      "reproduce reference copy, layouts, identities, footage, audio, offers, or branded " +
      "objects; distill decision grammar only.",
  },
  four_a_deep_effectiveness: {
    model: "DeepSeek-V4-Flash",
    maxTokens: 2048,
    temperature: 0.05,
    prerequisites: [
      "final_repair",
      "four_a_deep_strategy",
      "four_a_deep_craft",
    ],
    instruction:
      "Act as an adversarial effectiveness and causal-inference reviewer. For each TODO, " +
      "separate award recognition and reported outcomes from causal evidence. Specify the " +
      "unit, treatment, counterfactual, negative control, guardrails, sample-size input, " +
      "stopping rule, attribution limits, failure modes, and evidence that would falsify " +
      "the transfer. Reject proxy-only uplift and simulated 4A scores.",
  },
  four_a_deep_synthesis: {
    model: "Qwen3.6-35B-A3B",
    maxTokens: 2048,
    temperature: 0.05,
    prerequisites: [
      "four_a_deep_strategy",
      "four_a_deep_craft",
      "four_a_deep_effectiveness",
    ],
    instruction:
      "Compile the three specialist reviews into strict JSON {\"records\":[...]}, exactly " +
      "one record per TODO and in input order. Each record must contain todo_id, " +
      "reference_case_ids, observed_evidence, strategic_transfer, creative_mechanism, " +
      "channel_and_craft, effectiveness_test, negative_control, what_not_to_copy, " +
      "rights_partition, admission_status. rights_partition must be research_reference; " +
      "admission_status must be research_only or hold. Never call this training evidence, " +
      "Radeon execution, human preference, effectiveness proof, or task closure.",
  },
});


function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}


async function parseTasks(projectRoot) {
  const sourcePath = path.join(
    projectRoot,
    "docs",
    "CORTEX_X_V10_1500_TODO.md",
  );
  const source = await fs.readFile(sourcePath, "utf8");
  const parsedTasks = source
    .split(/\r?\n/)
    .map((line) => line.trim())
    .map((line) => TASK_PATTERN.exec(line))
    .filter(Boolean)
    .map((match) => ({
      todo_id: match[1],
      breakthrough_axis: match[2] || null,
      requirement: match[3],
    }));
  if (parsedTasks.length !== 1500) {
    throw new Error(
      `expected 1500 canonical tasks, found ${parsedTasks.length}`,
    );
  }
  for (let index = 0; index < parsedTasks.length; index += 1) {
    const expected = String(index + 1).padStart(4, "0");
    if (parsedTasks[index].todo_id !== expected) {
      throw new Error(
        `non-contiguous task sequence at ${expected}: ${parsedTasks[index].todo_id}`,
      );
    }
  }
  const manifestPath = path.join(
    projectRoot,
    "evidence",
    "v10",
    "program-manifest.json",
  );
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  const manifestById = new Map(
    manifest.todos.map((task) => [task.todo_id, task]),
  );
  const tasks = parsedTasks.map((task) => {
    const programTask = manifestById.get(task.todo_id);
    if (!programTask) {
      throw new Error(`program manifest omits task ${task.todo_id}`);
    }
    return {
      ...task,
      workstream_id: programTask.workstream_id,
      workstream_title: programTask.workstream_title,
      execution_wave: programTask.execution_wave,
      dependency_workstreams: programTask.dependency_workstreams,
      current_status: programTask.status,
    };
  });
  return {
    tasks,
    sourcePath,
    sourceSha256: sha256(source),
  };
}


export async function locateProfilePage(browser) {
  const pages = browser.contexts().flatMap((context) => context.pages());
  const page = pages.find((candidate) =>
    candidate.url().includes(PROFILE_FRAGMENT),
  );
  if (!page) {
    throw new Error("authenticated Radeon profile page is not open");
  }
  return page;
}


export async function fetchUsage(page) {
  const maxAttempts = 6;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await page.evaluate(async (usageUrl) => {
        const response = await fetch(usageUrl, { credentials: "same-origin" });
        if (!response.ok) {
          throw new Error(`usage endpoint returned HTTP ${response.status}`);
        }
        const payload = await response.json();
        return {
          rpm_limit: payload.rpm_limit,
          daily_cost_limit_usd: payload.daily_cost_limit_usd,
          daily_cost_used_usd: payload.daily_cost_used_usd,
          daily_cost_remaining_usd: payload.daily_cost_remaining_usd,
          daily_reset_timezone: payload.daily_reset_timezone,
          daily_reset_at: payload.daily_reset_at,
          today_requests: payload.today?.requests ?? null,
          today_errors: payload.today?.errors ?? null,
          today_total_tokens: payload.today?.total_tokens ?? null,
        };
      }, USAGE_URL);
    } catch (error) {
      const message = String(error?.message || error);
      const transientNavigation =
        message.includes("Execution context was destroyed") ||
        message.includes("Cannot find context with specified id") ||
        message.includes("Target page, context or browser has been closed") ||
        message.includes("Failed to fetch") ||
        message.includes("NetworkError") ||
        message.includes("usage endpoint returned HTTP 429") ||
        message.includes("usage endpoint returned HTTP 502") ||
        message.includes("usage endpoint returned HTTP 503") ||
        message.includes("usage endpoint returned HTTP 504");
      if (!transientNavigation || attempt === maxAttempts) {
        throw error;
      }
      await page.waitForTimeout(attempt * 500);
    }
  }
  throw new Error("usage fetch exhausted recovery attempts");
}


export async function callOfficial(page, payload) {
  return page.evaluate(async ({ chatUrl, body }) => {
    const keyNode = Array.from(document.querySelectorAll("[aria-label]")).find(
      (element) =>
        String(element.getAttribute("aria-label") || "").startsWith("rc-"),
    );
    const apiKey = keyNode?.getAttribute("aria-label");
    if (!apiKey) {
      throw new Error("Radeon Model API key is not present in the profile DOM");
    }
    const started = performance.now();
    let response;
    try {
      response = await fetch(chatUrl, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(body),
      });
    } catch (error) {
      return {
        ok: false,
        http_status: 0,
        response_id: null,
        model: body.model,
        content: "",
        reasoning_present: false,
        finish_reason: null,
        usage: {},
        error_code: "network_error",
        error_message: String(error?.message || error).slice(0, 400),
        duration_ms: Math.round(performance.now() - started),
      };
    }
    let result = null;
    try {
      result = await response.json();
    } catch {
      result = {};
    }
    const message = result?.choices?.[0]?.message || {};
    return {
      ok: response.ok,
      http_status: response.status,
      response_id: result?.id || null,
      model: result?.model || body.model,
      content: typeof message.content === "string" ? message.content : "",
      reasoning_present:
        typeof message.reasoning === "string" && message.reasoning.length > 0,
      finish_reason: result?.choices?.[0]?.finish_reason || null,
      usage: result?.usage || {},
      error_code: result?.error?.code || result?.code || null,
      error_message: String(
        result?.error?.message || result?.message || "",
      ).slice(0, 400) || null,
      duration_ms: Math.round(performance.now() - started),
    };
  }, { chatUrl: CHAT_URL, body: payload });
}


async function readPrerequisites(outputRoot, batchId, prerequisites) {
  const values = {};
  for (const prerequisite of prerequisites) {
    const filePath = path.join(
      outputRoot,
      prerequisite,
      `${batchId}.json`,
    );
    const payload = JSON.parse(await fs.readFile(filePath, "utf8"));
    if (payload.status !== "passed" || !payload.output) {
      throw new Error(
        `prerequisite ${prerequisite}/${batchId} is not passed`,
      );
    }
    values[prerequisite] = payload.output;
  }
  return values;
}


function buildPrompt(stageName, stage, batch, prerequisites) {
  const taskSpecificContext = batch.every(
    (task) => task.workstream_id === 1,
  )
    ? "This batch directly implements the official-rules workstream."
    : "Treat the official rules above as the global non-substitutable floor for this " +
      "batch. No additional authoritative task-specific source is supplied. Where an " +
      "exact revision, license, dataset, rule, or observed metric is required, define " +
      "the source-capture step and remain HOLD instead of substituting a placeholder.";
  const fourAContext = stageName.startsWith("four_a_deep_")
    ? ` ${FOUR_A_DISTILLATION_CONTEXT}`
    : "";
  const scopedContext = (
    `${OFFICIAL_TRACK_CONTEXT} ${MULTI_GPU_CONTEXT} ${taskSpecificContext}` +
    fourAContext
  );
  const strictJsonContract = ["synthesis", "final_repair"].includes(stageName)
    ? (
        "Strict JSON contract: the top level must be {\"records\":[...]}. Every " +
        "record must use exactly these case-sensitive keys: todo_id, dependencies, D, " +
        "A, I, E, implementation_steps, test_ids, acceptance_metrics, budget, " +
        "stop_rule, rollback, evidence_class, radeon_action, external_blockers, " +
        "current_status. Never emit aliases such as \"Radeon action\" or \"external " +
        "blockers\". current_status must be exactly \"not_started\" or \"in_progress\"; " +
        "represent HOLD reasons inside external_blockers, not as a status value."
      )
    : stageName === "four_a_deep_synthesis"
      ? (
          "Strict JSON contract: the top level must be {\"records\":[...]}. Every " +
          "record must use exactly these case-sensitive keys: todo_id, " +
          "reference_case_ids, observed_evidence, strategic_transfer, " +
          "creative_mechanism, channel_and_craft, effectiveness_test, " +
          "negative_control, what_not_to_copy, rights_partition, admission_status. " +
          "rights_partition must equal research_reference and admission_status must " +
          "equal research_only or hold."
        )
      : "No additional strict-JSON schema applies to this stage.";
  return [
    "ProofLaunch Cortex-X V10 canonical task batch follows.",
    "The global truth rule is strict: a plan is not completion; only source-bound " +
      "implementation plus named passing tests and required external evidence can close a task.",
    `Stage: ${stageName}`,
    `Stage instruction: ${stage.instruction}`,
    `Mandatory quality protocol (${QUALITY_PROTOCOL_VERSION}): ${FRONTIER_QUALITY_PROTOCOL}`,
    `Authoritative scoped context: ${scopedContext}`,
    strictJsonContract,
    "Interpret each requirement inside its supplied workstream. In competition-rule " +
      "workstreams, the Chinese verb 冻结 means capture and version an authoritative rule " +
      "with source evidence; it does not mean invent a registration service, database, " +
      "Redis lock, product endpoint, or benchmark result. Never invent an existing module, " +
      "upstream revision, paper, metric, API, or organization. If an authoritative source " +
      "is unavailable, specify the exact external evidence gap and fail closed.",
    "Canonical tasks:",
    JSON.stringify(batch, null, 2),
    "Prior stage material:",
    JSON.stringify(prerequisites, null, 2),
    `Coverage contract: return exactly ${batch.length} compact records in this exact ` +
      `order: ${batch.map((task) => task.todo_id).join(", ")}. Begin each record with ` +
      "its literal four-digit todo_id. " +
      "Cover every listed ID before expanding any one record. " +
      "Never end after only the first task.",
    "Return a complete, task-by-task deliverable. Preserve every todo_id exactly. " +
      "Use at most 850 output tokens per task. Prefer compact field:value records; omit " +
      "boilerplate and code blocks unless code is the required artifact. Never reveal hidden " +
      "chain-of-thought; provide concise decision rationale and evidence requirements.",
  ].join("\n\n");
}


function outputQualityViolations(result, stageName, batch) {
  const output = String(result.content || "");
  const violations = [];
  if (result.http_status !== 200) {
    violations.push("upstream_http_error");
  }
  if (!output.trim()) {
    violations.push("empty_visible_output");
  }
  if (result.finish_reason === "length") {
    violations.push("truncated_output");
  }
  if (
    !["synthesis", "final_repair", "four_a_deep_synthesis"].includes(stageName) &&
    batch.some((task) => !output.includes(task.todo_id))
  ) {
    violations.push("missing_todo_coverage");
  }
  if (stageName === "architect" || stageName === "research") {
    if (/<official[_ -]?(org|repo)>/i.test(output)) {
      violations.push("placeholder_official_source");
    }
    if (/license[^\n]{0,120}\b(inferred|assumed)\b/i.test(output)) {
      violations.push("inferred_license");
    }
    if (/revised score[^\n]{0,120}\b(pass|16|17|18|19|20)\b/i.test(output)) {
      violations.push("score_gate_gaming");
    }
  }
  if (
    (stageName === "synthesis" || stageName === "final_repair") &&
    output.trim()
  ) {
    try {
      const parsed = JSON.parse(output);
      const records = Array.isArray(parsed?.records) ? parsed.records : [];
      const expectedIds = batch.map((task) => task.todo_id);
      const observedIds = records.map((record) => record?.todo_id);
      if (
        records.length !== batch.length ||
        JSON.stringify(observedIds) !== JSON.stringify(expectedIds)
      ) {
        violations.push("synthesis_todo_coverage");
      }
      if (
        records.some((record) =>
          SYNTHESIS_REQUIRED_FIELDS.some(
            (field) => !(field in (record || {})),
          ),
        )
      ) {
        violations.push("synthesis_missing_fields");
      }
      if (
        records.some(
          (record) =>
            !["not_started", "in_progress"].includes(
              record?.current_status,
            ),
        )
      ) {
        violations.push("synthesis_invalid_status");
      }
    } catch {
      violations.push("synthesis_invalid_json");
    }
  }
  if (stageName === "four_a_deep_synthesis" && output.trim()) {
    try {
      const parsed = JSON.parse(output);
      const records = Array.isArray(parsed?.records) ? parsed.records : [];
      const expectedIds = batch.map((task) => task.todo_id);
      const observedIds = records.map((record) => record?.todo_id);
      if (
        records.length !== batch.length ||
        JSON.stringify(observedIds) !== JSON.stringify(expectedIds)
      ) {
        violations.push("four_a_transfer_todo_coverage");
      }
      if (
        records.some((record) =>
          FOUR_A_TRANSFER_REQUIRED_FIELDS.some(
            (field) => !(field in (record || {})),
          ),
        )
      ) {
        violations.push("four_a_transfer_missing_fields");
      }
      if (
        records.some(
          (record) =>
            record?.rights_partition !== "research_reference" ||
            !["research_only", "hold"].includes(record?.admission_status),
        )
      ) {
        violations.push("four_a_transfer_invalid_admission");
      }
      if (
        records.some(
          (record) =>
            !Array.isArray(record?.reference_case_ids) ||
            record.reference_case_ids.some(
              (caseId) => !FOUR_A_REFERENCE_CASE_IDS.has(caseId),
            ),
        )
      ) {
        violations.push("four_a_transfer_unbound_reference");
      }
    } catch {
      violations.push("four_a_transfer_invalid_json");
    }
  }
  return violations;
}


async function runBoundedRateLimited(items, handler) {
  const results = new Array(items.length);
  let cursor = 0;
  let nextStartAt = Date.now();

  async function worker() {
    while (true) {
      const itemIndex = cursor;
      cursor += 1;
      if (itemIndex >= items.length) {
        return;
      }
      const now = Date.now();
      const startAt = Math.max(now, nextStartAt);
      nextStartAt = startAt + START_INTERVAL_MS;
      const delay = startAt - now;
      if (delay > 0) {
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
      results[itemIndex] = await handler(items[itemIndex], itemIndex);
    }
  }

  const workerCount = Math.min(MAX_IN_FLIGHT, items.length);
  await Promise.all(
    Array.from({ length: workerCount }, () => worker()),
  );
  return results;
}


function normalizeStructuredOutput(content, stageName) {
  const rawOutput = String(content || "");
  const rawOutputSha256 = sha256(rawOutput);
  if (
    !["synthesis", "final_repair", "four_a_deep_synthesis"].includes(stageName)
  ) {
    return {
      output: rawOutput,
      rawOutputSha256,
      normalizations: [],
    };
  }
  try {
    const parsed = JSON.parse(rawOutput);
    const records = Array.isArray(parsed?.records) ? parsed.records : [];
    const normalizations = [];
    for (const record of records) {
      if (!record || typeof record !== "object" || Array.isArray(record)) {
        continue;
      }
      for (const [alias, canonical] of [
        ["Radeon action", "radeon_action"],
        ["external blockers", "external_blockers"],
      ]) {
        if (alias in record && !(canonical in record)) {
          record[canonical] = record[alias];
          delete record[alias];
          normalizations.push({
            todo_id: record.todo_id || null,
            operation: "rename_key_only",
            from: alias,
            to: canonical,
          });
        }
      }
    }
    return {
      output: JSON.stringify(parsed),
      rawOutputSha256,
      normalizations,
    };
  } catch {
    return {
      output: rawOutput,
      rawOutputSha256,
      normalizations: [],
    };
  }
}


async function runOne({
  page,
  projectRoot,
  outputRoot,
  sourceSha256,
  stageName,
  stage,
  batchIndex,
  batch,
  stopRemainingUsd,
}) {
  const batchId =
    `${String(batchIndex * BATCH_SIZE + 1).padStart(4, "0")}-` +
    `${String(batchIndex * BATCH_SIZE + batch.length).padStart(4, "0")}`;
  const stageDirectory = path.join(outputRoot, stageName);
  const outputPath = path.join(stageDirectory, `${batchId}.json`);
  await fs.mkdir(stageDirectory, { recursive: true });
  let priorQualityViolations = [];
  let priorRepairHints = [];
  try {
    const existing = JSON.parse(await fs.readFile(outputPath, "utf8"));
    if (
      existing.status === "passed" &&
      existing.output &&
      existing.quality_protocol === QUALITY_PROTOCOL_VERSION
    ) {
      return {
        batch_id: batchId,
        status: "skipped_existing",
        model: existing.model,
        output_sha256: existing.output_sha256,
      };
    }
    priorQualityViolations = Array.isArray(
      existing.quality_violations,
    )
      ? existing.quality_violations
      : [];
    if (
      priorQualityViolations.includes("synthesis_missing_fields") &&
      typeof existing.output === "string"
    ) {
      try {
        const parsed = JSON.parse(existing.output);
        const records = Array.isArray(parsed?.records)
          ? parsed.records
          : [];
        for (const record of records) {
          const missing = SYNTHESIS_REQUIRED_FIELDS.filter(
            (field) => !(field in (record || {})),
          );
          if (missing.length) {
            priorRepairHints.push(
              `todo ${record?.todo_id || "unknown"} must add exact keys: ` +
                missing.join(", "),
            );
          }
        }
      } catch {
        priorRepairHints.push(
          "The previous output could not be parsed while locating missing fields.",
        );
      }
    }
    if (
      priorQualityViolations.includes("synthesis_invalid_json") &&
      typeof existing.output === "string"
    ) {
      try {
        JSON.parse(existing.output);
      } catch (error) {
        priorRepairHints.push(
          `Previous JSON parser error: ${String(error?.message || error).slice(0, 240)}`,
        );
      }
    }
  } catch {
    // Missing or invalid output is rebuilt.
  }

  const usageBefore = await fetchUsage(page);
  if (usageBefore.daily_cost_remaining_usd <= stopRemainingUsd) {
    return {
      batch_id: batchId,
      status: "stopped_budget",
      remaining_usd: usageBefore.daily_cost_remaining_usd,
    };
  }
  const prerequisites = await readPrerequisites(
    outputRoot,
    batchId,
    stage.prerequisites,
  );
  const correctionContext = priorQualityViolations.length
    ? stageName === "four_a_deep_synthesis"
      ? [
          "A prior attempt was rejected by the deterministic 4A transfer validator for:",
          priorQualityViolations.join(", "),
          priorRepairHints.join(" "),
          "Return a fresh strict JSON object with exactly {\"records\":[...]} and no",
          "Markdown fence or prose. Emit exactly one record per supplied TODO in input",
          "order. Every record must contain exactly these required keys: todo_id,",
          "reference_case_ids, observed_evidence, strategic_transfer,",
          "creative_mechanism, channel_and_craft, effectiveness_test, negative_control,",
          "what_not_to_copy, rights_partition, admission_status.",
          "reference_case_ids must be an array containing only IDs from the frozen",
          "13-case context, or an empty array when no case fits. Never use paper names,",
          "rule files, benchmark IDs, repositories, or invented annual IDs as case IDs.",
          "rights_partition must equal research_reference. admission_status must equal",
          "research_only or hold. Escape JSON according to RFC 8259.",
        ].join(" ")
      : [
        "A prior attempt was rejected by the deterministic validator for:",
        priorQualityViolations.join(", "),
        priorRepairHints.join(" "),
        "Return a fresh corrected response; do not copy the rejected serialization.",
        "Construct the complete object skeleton with every required key before writing",
        "any field value. E and implementation_steps must both be non-empty in every",
        "record. If the prior error was invalid JSON, use plain language values and",
        "emit no backslash characters anywhere in the response.",
        "For strict JSON, escape every backslash and quote according to RFC 8259.",
        "current_status may only be not_started or in_progress; put every HOLD or",
        "completion caveat inside external_blockers.",
        ].join(" ")
    : "";
  const prompt = [
    buildPrompt(stageName, stage, batch, prerequisites),
    correctionContext,
  ].filter(Boolean).join("\n\n");
  const remainingForCall = Math.max(
    0,
    usageBefore.daily_cost_remaining_usd - stopRemainingUsd,
  );
  const qwenOutputRateUsdPerToken = 0.000001;
  const effectiveModel = priorQualityViolations.includes(
    "upstream_http_error",
  )
    ? stage.model === "Qwen3.6-35B-A3B"
      ? "DeepSeek-V4-Flash"
      : "Qwen3.6-35B-A3B"
    : stage.model;
  const requestTemperature = priorQualityViolations.length
    ? Math.max(stage.temperature, 0.20)
    : stage.temperature;
  const adaptiveMaxTokens =
    effectiveModel === "Qwen3.6-35B-A3B"
      ? Math.max(
          512,
          Math.min(
            stage.maxTokens,
            Math.floor(
              (remainingForCall * 0.90) / qwenOutputRateUsdPerToken,
            ),
          ),
        )
      : stage.maxTokens;
  const request = {
    model: effectiveModel,
    messages: [
      {
        role: "system",
        content:
          "You produce source-bound, falsifiable multimodal GTM engineering artifacts. " +
          "Never convert a plan, simulated metric, or self-review into a completion claim.",
      },
      { role: "user", content: prompt },
    ],
    temperature: requestTemperature,
    max_tokens: adaptiveMaxTokens,
    chat_template_kwargs: {
      enable_thinking: false,
    },
  };
  const result = await callOfficial(page, request);
  const normalized = normalizeStructuredOutput(
    result.content,
    stageName,
  );
  result.content = normalized.output;
  const qualityViolations = outputQualityViolations(
    result,
    stageName,
    batch,
  );
  const record = {
    schema: "ProofLaunchTokenFactoryTeacherEpisodeV1",
    status:
      result.ok && qualityViolations.length === 0 ? "passed" : "blocked",
    stage: stageName,
    quality_protocol: QUALITY_PROTOCOL_VERSION,
    batch_id: batchId,
    todo_ids: batch.map((task) => task.todo_id),
    provider: "amd_radeon_token_factory",
    endpoint: CHAT_URL,
    model: result.model,
    requested_model: stage.model,
    official_failover_from:
      effectiveModel === stage.model ? null : stage.model,
    source_todo_sha256: sourceSha256,
    request_sha256: sha256(prompt),
    four_a_context_sha256: stageName.startsWith("four_a_deep_")
      ? sha256(FOUR_A_DISTILLATION_CONTEXT)
      : null,
    max_tokens: adaptiveMaxTokens,
    temperature: requestTemperature,
    http_status: result.http_status,
    response_id: result.response_id,
    finish_reason: result.finish_reason,
    usage: result.usage,
    duration_ms: result.duration_ms,
    error_code: result.error_code,
    error_message: result.error_message,
    quality_violations: qualityViolations,
    prior_quality_violations: priorQualityViolations,
    prior_repair_hints: priorRepairHints,
    output: result.content,
    raw_output_sha256: normalized.rawOutputSha256,
    output_normalizations: normalized.normalizations,
    output_sha256: result.content ? sha256(result.content) : null,
    hidden_reasoning_persisted: false,
    credential: {
      persisted: false,
      redacted: true,
      source: "authenticated Radeon profile DOM",
    },
    competition_core_eligible: false,
    evidence_class: "external_teacher_advisory",
    truth_boundary:
      "Teacher output is training/development material, not local Radeon execution and not TODO closure evidence by itself.",
    generated_at: new Date().toISOString(),
  };
  await fs.writeFile(
    outputPath,
    `${JSON.stringify(record, null, 2)}\n`,
    "utf8",
  );
  return {
    batch_id: batchId,
    status: record.status,
    model: record.model,
    http_status: record.http_status,
    finish_reason: record.finish_reason,
    completion_tokens: record.usage?.completion_tokens ?? null,
    output_sha256: record.output_sha256,
    duration_ms: record.duration_ms,
  };
}


export async function runCorpusChunk({
  projectRoot,
  stageName,
  startBatch = 0,
  batchCount = 6,
  stopRemainingUsd = DEFAULT_STOP_REMAINING_USD,
} = {}) {
  if (!projectRoot) {
    throw new Error("projectRoot is required");
  }
  const stage = STAGES[stageName];
  if (!stage) {
    throw new Error(`unknown stage: ${stageName}`);
  }
  const parsed = await parseTasks(projectRoot);
  const allBatches = [];
  for (let index = 0; index < parsed.tasks.length; index += BATCH_SIZE) {
    allBatches.push(parsed.tasks.slice(index, index + BATCH_SIZE));
  }
  if (
    !Number.isInteger(startBatch) ||
    startBatch < 0 ||
    startBatch >= allBatches.length
  ) {
    throw new Error(
      `startBatch is outside the ${allBatches.length}-batch corpus`,
    );
  }
  if (!Number.isInteger(batchCount) || batchCount <= 0) {
    throw new Error("batchCount must be a positive integer");
  }
  const selected = allBatches.slice(
    startBatch,
    Math.min(allBatches.length, startBatch + batchCount),
  );
  const outputRoot = path.join(
    projectRoot,
    "data",
    "tokenfactory_teacher_v10",
  );
  const browser = await chromium.connectOverCDP(CDP_URL);
  const page = await locateProfilePage(browser);
  const usageBefore = await fetchUsage(page);
  const results = await runBoundedRateLimited(
    selected,
    (batch, offset) =>
      runOne({
        page,
        projectRoot,
        outputRoot,
        sourceSha256: parsed.sourceSha256,
        stageName,
        stage,
        batchIndex: startBatch + offset,
        batch,
        stopRemainingUsd,
      }),
  );
  const usageAfter = await fetchUsage(page);
  return {
    schema: "ProofLaunchTokenFactoryCorpusChunkReceiptV1",
    stage: stageName,
    start_batch: startBatch,
    requested_batches: selected.length,
    passed: results.filter((item) => item.status === "passed").length,
    skipped_existing: results.filter(
      (item) => item.status === "skipped_existing",
    ).length,
    blocked: results.filter((item) => item.status === "blocked").length,
    stopped_budget: results.filter(
      (item) => item.status === "stopped_budget",
    ).length,
    results,
    usage_before: usageBefore,
    usage_after: usageAfter,
    spend_delta_usd:
      usageAfter.daily_cost_used_usd - usageBefore.daily_cost_used_usd,
    output_root: outputRoot,
    credential_persisted: false,
    hidden_reasoning_persisted: false,
  };
}


export async function getCorpusState({ projectRoot } = {}) {
  if (!projectRoot) {
    throw new Error("projectRoot is required");
  }
  const browser = await chromium.connectOverCDP(CDP_URL);
  const page = await locateProfilePage(browser);
  const outputRoot = path.join(
    projectRoot,
    "data",
    "tokenfactory_teacher_v10",
  );
  const stages = {};
  for (const stageName of Object.keys(STAGES)) {
    let files = [];
    try {
      files = (await fs.readdir(path.join(outputRoot, stageName))).filter(
        (name) => name.endsWith(".json"),
      );
    } catch {
      files = [];
    }
    stages[stageName] = files.length;
  }
  return {
    schema: "ProofLaunchTokenFactoryCorpusStateV1",
    total_canonical_tasks: 1500,
    batch_size: BATCH_SIZE,
    total_batches_per_stage: Math.ceil(1500 / BATCH_SIZE),
    safe_rpm: SAFE_RPM,
    stages,
    usage: await fetchUsage(page),
    output_root: outputRoot,
  };
}


async function outputIsPassed(outputRoot, stageName, batchIndex, batch) {
  const batchId =
    `${String(batchIndex * BATCH_SIZE + 1).padStart(4, "0")}-` +
    `${String(batchIndex * BATCH_SIZE + batch.length).padStart(4, "0")}`;
  try {
    const payload = JSON.parse(
      await fs.readFile(
        path.join(outputRoot, stageName, `${batchId}.json`),
        "utf8",
      ),
    );
    return (
      payload.status === "passed" &&
      Boolean(payload.output) &&
      payload.quality_protocol === QUALITY_PROTOCOL_VERSION
    );
  } catch {
    return false;
  }
}


export async function runCorpusStage({
  projectRoot,
  stageName,
  startBatch = 0,
  endBatch = null,
  chunkSize = 20,
  retryPasses = 2,
  stopRemainingUsd = DEFAULT_STOP_REMAINING_USD,
  stopBeforeResetMs = 180000,
  progress = true,
} = {}) {
  if (!projectRoot) {
    throw new Error("projectRoot is required");
  }
  const stage = STAGES[stageName];
  if (!stage) {
    throw new Error(`unknown stage: ${stageName}`);
  }
  if (
    !Number.isInteger(chunkSize) ||
    chunkSize < 1 ||
    chunkSize > MAX_PIPELINE_BATCHES
  ) {
    throw new Error(
      `chunkSize must be between 1 and ${MAX_PIPELINE_BATCHES}`,
    );
  }
  const parsed = await parseTasks(projectRoot);
  const allBatches = [];
  for (let index = 0; index < parsed.tasks.length; index += BATCH_SIZE) {
    allBatches.push(parsed.tasks.slice(index, index + BATCH_SIZE));
  }
  const finalBatch =
    endBatch === null ? allBatches.length : Math.min(endBatch, allBatches.length);
  if (
    !Number.isInteger(startBatch) ||
    !Number.isInteger(finalBatch) ||
    startBatch < 0 ||
    startBatch >= finalBatch
  ) {
    throw new Error("invalid stage batch range");
  }
  const outputRoot = path.join(
    projectRoot,
    "data",
    "tokenfactory_teacher_v10",
  );
  const browser = await chromium.connectOverCDP(CDP_URL);
  const page = await locateProfilePage(browser);
  const openingUsage = await fetchUsage(page);
  const expectedResetAt = openingUsage.daily_reset_at;
  const resetEpochMs = Date.parse(expectedResetAt);
  const attempted = [];
  let stoppedReason = null;

  for (let pass = 0; pass <= retryPasses; pass += 1) {
    const missing = [];
    for (let index = startBatch; index < finalBatch; index += 1) {
      if (
        !(await outputIsPassed(
          outputRoot,
          stageName,
          index,
          allBatches[index],
        ))
      ) {
        missing.push(index);
      }
    }
    if (!missing.length) {
      break;
    }
    for (let cursor = 0; cursor < missing.length; cursor += chunkSize) {
      const usageBefore = await fetchUsage(page);
      if (usageBefore.daily_reset_at !== expectedResetAt) {
        stoppedReason = "daily_window_reset_changed";
        break;
      }
      if (
        Date.now() >= resetEpochMs - stopBeforeResetMs
      ) {
        stoppedReason = "protected_reset_boundary";
        break;
      }
      if (usageBefore.daily_cost_remaining_usd <= stopRemainingUsd) {
        stoppedReason = "daily_budget_exhausted";
        break;
      }
      const spendableUsd = Math.max(
        0,
        usageBefore.daily_cost_remaining_usd - stopRemainingUsd,
      );
      const budgetSafeCallCount = Math.floor(
        spendableUsd / CONSERVATIVE_MAX_CALL_COST_USD,
      );
      if (budgetSafeCallCount < 1) {
        stoppedReason = "daily_budget_settlement_guard";
        break;
      }
      const indices = missing.slice(
        cursor,
        cursor + Math.min(chunkSize, budgetSafeCallCount),
      );
      const results = await runBoundedRateLimited(
        indices,
        (batchIndex) =>
          runOne({
            page,
            projectRoot,
            outputRoot,
            sourceSha256: parsed.sourceSha256,
            stageName,
            stage,
            batchIndex,
            batch: allBatches[batchIndex],
            stopRemainingUsd,
          }),
      );
      attempted.push(...results);
      const usageAfter = await fetchUsage(page);
      const chunkPassed = results.filter(
        (item) => item.status === "passed",
      ).length;
      if (progress) {
        process.stdout.write(
          `${JSON.stringify({
            event: "tokenfactory_corpus_progress",
            stage: stageName,
            pass,
            batch_cursor: indices[indices.length - 1] + 1,
            total_batches: finalBatch - startBatch,
            chunk_passed: chunkPassed,
            chunk_blocked: results.filter(
              (item) => item.status === "blocked",
            ).length,
            today_requests: usageAfter.today_requests,
            today_errors: usageAfter.today_errors,
            today_tokens: usageAfter.today_total_tokens,
            used_usd: usageAfter.daily_cost_used_usd,
            remaining_usd: usageAfter.daily_cost_remaining_usd,
            reset_at: usageAfter.daily_reset_at,
          })}\n`,
        );
      }
      if (
        results.length >= 20 &&
        chunkPassed / results.length < MINIMUM_HEALTHY_CHUNK_PASS_RATE
      ) {
        stoppedReason = "quality_circuit_breaker";
        break;
      }
    }
    if (stoppedReason) {
      break;
    }
  }

  let passed = 0;
  for (let index = startBatch; index < finalBatch; index += 1) {
    if (
      await outputIsPassed(
        outputRoot,
        stageName,
        index,
        allBatches[index],
      )
    ) {
      passed += 1;
    }
  }
  const closingUsage = await fetchUsage(page);
  return {
    schema: "ProofLaunchTokenFactoryCorpusStageReceiptV1",
    stage: stageName,
    range: [startBatch, finalBatch],
    passed_batches: passed,
    expected_batches: finalBatch - startBatch,
    attempted_requests: attempted.length,
    blocked_attempts: attempted.filter(
      (item) => item.status === "blocked",
    ).length,
    stopped_reason: stoppedReason,
    opening_usage: openingUsage,
    closing_usage: closingUsage,
    credential_persisted: false,
    hidden_reasoning_persisted: false,
  };
}
