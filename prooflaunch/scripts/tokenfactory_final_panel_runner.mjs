import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const PROJECT_ROOT = process.cwd();
const CDP_URL = "http://127.0.0.1:9222";
const CHAT_URL =
  "https://developer.amd.com.cn/radeon/api/v1/chat/completions";
const USAGE_URL =
  "https://developer.amd.com.cn/radeon/api/profile/model-usage?include_recent=false";
const PROFILE_FRAGMENT = "/radeon/profile";
const OUTPUT_ROOT = path.join(
  PROJECT_ROOT,
  "evidence",
  "v10",
  "tokenfactory-final-panel",
);
const STOP_REMAINING_USD = 0.0001;
const CONSERVATIVE_MAX_CALL_COST_USD = 0.003;

const PANELS = [
  "competition compliance and truth-claim red team",
  "training-corpus provenance and contamination audit",
  "multimodal curriculum and retention-gate audit",
  "multi-GPU ROCm stability and equivalence audit",
  "North American 4A strategy-transfer audit",
  "creative craft and cross-channel coherence audit",
  "incrementality, causal measurement, and negative-control audit",
  "GTM employee workflow and human-approval audit",
  "agent architecture, tool safety, and rollback audit",
  "adversarial evaluation and failure-taxonomy audit",
  "Radeon performance evidence and reproducibility audit",
  "product differentiation and blind-preference audit",
  "data rights, privacy, and brand-safety audit",
  "cost, latency, throughput, and operational-SLO audit",
  "demo narrative and judge-legibility audit",
  "open-source reuse, license, and integration-seam audit",
  "model calibration, abstention, and uncertainty audit",
  "campaign-world-model state and memory audit",
  "visual/audio retention and cross-modal regression audit",
  "final release-readiness and blocker-priority audit",
];

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

async function usage(page) {
  return page.evaluate(async (url) => {
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(`usage endpoint HTTP ${response.status}`);
    }
    const payload = await response.json();
    return {
      daily_cost_limit_usd: payload.daily_cost_limit_usd,
      daily_cost_used_usd: payload.daily_cost_used_usd,
      daily_cost_remaining_usd: payload.daily_cost_remaining_usd,
      daily_reset_at: payload.daily_reset_at,
      today_requests: payload.today?.requests ?? null,
      today_total_tokens: payload.today?.total_tokens ?? null,
    };
  }, USAGE_URL);
}

async function call(page, body) {
  return page.evaluate(async ({ chatUrl, requestBody }) => {
    const keyNode = Array.from(document.querySelectorAll("[aria-label]")).find(
      (element) =>
        String(element.getAttribute("aria-label") || "").startsWith("rc-"),
    );
    const apiKey = keyNode?.getAttribute("aria-label");
    if (!apiKey) {
      throw new Error("Radeon Model API key is absent from authenticated DOM");
    }
    const startedAt = performance.now();
    const response = await fetch(chatUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(requestBody),
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      payload = {};
    }
    const message = payload?.choices?.[0]?.message || {};
    return {
      ok: response.ok,
      http_status: response.status,
      response_id: payload?.id || null,
      model: payload?.model || requestBody.model,
      content: typeof message.content === "string" ? message.content : "",
      reasoning_present:
        typeof message.reasoning === "string" && message.reasoning.length > 0,
      finish_reason: payload?.choices?.[0]?.finish_reason || null,
      usage: payload?.usage || {},
      error_message: String(
        payload?.error?.message || payload?.message || "",
      ).slice(0, 400) || null,
      duration_ms: Math.round(performance.now() - startedAt),
    };
  }, { chatUrl: CHAT_URL, requestBody: body });
}

const rules = JSON.parse(
  await fs.readFile(
    path.join(
      PROJECT_ROOT,
      "evidence",
      "OFFICIAL_TRACK1_RULES_AUDIT_2026-07-30.json",
    ),
    "utf8",
  ),
);
const fourA = JSON.parse(
  await fs.readFile(
    path.join(
      PROJECT_ROOT,
      "evidence",
      "v10",
      "four-a-transfer-corpus-validation.json",
    ),
    "utf8",
  ),
);
const original = JSON.parse(
  await fs.readFile(
    path.join(
      PROJECT_ROOT,
      "evidence",
      "v10",
      "tokenfactory-corpus-validation.json",
    ),
    "utf8",
  ),
);
const frozenContext = JSON.stringify(
  {
    official_track: rules.track,
    model_policy: rules.trackRequirements.modelPolicy,
    judging: rules.judging,
    original_corpus: {
      status: original.status,
      expected_batches_per_stage: original.expected_batches_per_stage,
      stage_valid_counts: original.stage_valid_counts,
      issue_count: original.issue_count,
    },
    four_a_corpus: {
      status: fourA.status,
      expected_batch_count_per_stage: fourA.expected_batch_count_per_stage,
      valid_counts: fourA.valid_counts,
      reference_bound_synthesis_records:
        fourA.reference_bound_synthesis_records,
      hold_synthesis_records: fourA.hold_synthesis_records,
      issue_count: fourA.issue_count,
    },
    truth_boundary: [
      "Teacher-corpus validation is not proof of model training.",
      "No real local Radeon key-inference receipt exists yet.",
      "No campaign-effectiveness or blind-preference claim may be promoted without observed evidence.",
      "Third-party online APIs are not competition-core eligible.",
    ],
  },
  null,
  2,
);

await fs.mkdir(OUTPUT_ROOT, { recursive: true });
const browser = await chromium.connectOverCDP(CDP_URL);
const page = browser
  .contexts()
  .flatMap((context) => context.pages())
  .find((candidate) => candidate.url().includes(PROFILE_FRAGMENT));
if (!page) {
  throw new Error("authenticated Radeon profile page is not open");
}

const openingUsage = await usage(page);
const records = [];
for (let index = 0; index < PANELS.length; index += 1) {
  const before = await usage(page);
  if (
    before.daily_cost_remaining_usd - STOP_REMAINING_USD <
    CONSERVATIVE_MAX_CALL_COST_USD
  ) {
    break;
  }
  const lens = PANELS[index];
  const messages = [
    {
      role: "system",
      content:
        "You are an independent release-gate auditor. Use only the supplied frozen facts. " +
        "Do not claim training, Radeon execution, campaign lift, preference wins, or TODO completion " +
        "without matching observed evidence. Return strict JSON only with keys: panel, verdict, " +
        "observed_strengths, critical_blockers, falsification_tests, prioritized_actions, " +
        "claims_that_must_remain_on_hold. Arrays must contain concrete, non-duplicative items.",
    },
    {
      role: "user",
      content:
        `Panel lens: ${lens}\n\nFrozen evidence summary:\n${frozenContext}\n\n` +
        "Audit this release against the official Track 1 boundary. Distinguish corpus integrity " +
        "from trained-model evidence and local Radeon evidence. Give the most decision-useful " +
        "release blockers and tests; do not reward aspiration.",
    },
  ];
  const request = {
    model: "Qwen3.6-35B-A3B",
    messages,
    temperature: 0.1,
    max_tokens: 4096,
    stream: false,
  };
  let result = await call(page, request);
  if (!result.ok || !result.content.trim()) {
    result = await call(page, {
      ...request,
      model: "DeepSeek-V4-Flash",
      max_tokens: 3072,
    });
  }
  const record = {
    schema: "ProofLaunchTokenFactoryFinalPanelRecordV1",
    panel_index: index + 1,
    panel: lens,
    generated_at: new Date().toISOString(),
    provider: "amd_radeon_token_factory",
    requested_model: request.model,
    model: result.model,
    http_status: result.http_status,
    status:
      result.ok && result.content.trim() ? "observed_advisory" : "blocked",
    request_sha256: sha256(JSON.stringify(messages)),
    output_sha256: sha256(result.content),
    output: result.content,
    response_id: result.response_id,
    finish_reason: result.finish_reason,
    usage: result.usage,
    duration_ms: result.duration_ms,
    credential: {
      source: "authenticated_browser_dom",
      persisted: false,
      redacted: true,
    },
    hidden_reasoning_persisted: false,
    competition_core_eligible: false,
    truth_boundary:
      "This is an official Token Factory advisory audit, not local Radeon inference, model training, or release proof.",
  };
  records.push(record);
  await fs.writeFile(
    path.join(
      OUTPUT_ROOT,
      `${String(index + 1).padStart(2, "0")}-${lens
        .replace(/[^a-z0-9]+/gi, "-")
        .replace(/^-|-$/g, "")
        .toLowerCase()}.json`,
    ),
    `${JSON.stringify(record, null, 2)}\n`,
    "utf8",
  );
  process.stdout.write(
    `${JSON.stringify({
      event: "final_panel_progress",
      panel: index + 1,
      status: record.status,
      remaining_usd: (await usage(page)).daily_cost_remaining_usd,
    })}\n`,
  );
}
const closingUsage = await usage(page);
const receipt = {
  schema: "ProofLaunchTokenFactoryFinalPanelReceiptV1",
  status: records.length > 0 ? "completed" : "not_started",
  panel_count: records.length,
  observed_advisory_count: records.filter(
    (record) => record.status === "observed_advisory",
  ).length,
  blocked_count: records.filter((record) => record.status === "blocked").length,
  opening_usage: openingUsage,
  closing_usage: closingUsage,
  credential_persisted: false,
  hidden_reasoning_persisted: false,
  competition_core_eligible: false,
  truth_boundary:
    "These panel outputs are advisory only; all release claims remain governed by observed local validators and the missing Radeon execution receipt.",
};
await fs.writeFile(
  path.join(OUTPUT_ROOT, "receipt.json"),
  `${JSON.stringify(receipt, null, 2)}\n`,
  "utf8",
);
console.log("FINAL_PANEL_RECEIPT", JSON.stringify(receipt));
