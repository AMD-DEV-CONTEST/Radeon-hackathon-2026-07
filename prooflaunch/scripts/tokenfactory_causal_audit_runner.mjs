import crypto from "node:crypto";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

import {
  callOfficial,
  fetchUsage,
  locateProfilePage,
} from "./tokenfactory_corpus_runner.mjs";


const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const CDP_URL = "http://127.0.0.1:9222";
const MODELS = Object.freeze([
  {
    model: "Qwen3.6-35B-A3B",
    role: "causal_training_architect",
    temperature: 0.15,
  },
  {
    model: "DeepSeek-V4-Flash",
    role: "adversarial_causal_reviewer",
    temperature: 0.05,
  },
  {
    model: "Qwen3.6-35B-A3B",
    role: "machine_acceptance_compiler",
    temperature: 0.0,
  },
]);


function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}


function promptFor(role, manifest, benchmark, transfer) {
  const shared = {
    todos: ["1203", "1204", "1205", "1206"],
    artifact_schema: manifest.schema,
    record_count: manifest.record_count,
    product_kinds: manifest.product_kinds,
    confounders: manifest.confounders,
    temporal_boundaries: manifest.temporal_boundaries,
    rights: manifest.rights,
    estimator_result: benchmark.result,
    estimator_acceptance: benchmark.acceptance,
    cold_start_result: transfer.result,
    truth_boundary: manifest.truth_boundary,
  };
  return [
    "You are reviewing a rights-bound causal-training kernel for a multimodal GTM agent.",
    `Role: ${role}.`,
    "Return strict JSON with keys role, verdict, defects, required_repairs, ablations,",
    "acceptance_tests, training_use_decision, and truth_boundary. Never claim observed",
    "business lift, Radeon execution, model fine-tuning, human preference, or production",
    "quality. Treat standalone IPW underperformance as a required negative result, not",
    "something to hide. training_use_decision must be evaluator_only_pending_terms because",
    "AMD output-training rights have not been captured. Assess leakage, positivity,",
    "propensity misspecification, outcome-model dependence, calibration, and cold-start",
    "transportability. Keep the answer under 3000 output tokens.",
    JSON.stringify(shared),
  ].join("\n\n");
}


async function main() {
  const projectRoot = path.resolve(process.argv[2] || process.cwd());
  const manifest = JSON.parse(
    await fs.readFile(
      path.join(projectRoot, "data/v10_causal_twin_timeseries/manifest.json"),
      "utf8",
    ),
  );
  const benchmark = JSON.parse(
    await fs.readFile(
      path.join(projectRoot, "evidence/v10/causal-twin-estimator-benchmark.json"),
      "utf8",
    ),
  );
  const transfer = JSON.parse(
    await fs.readFile(
      path.join(projectRoot, "data/v10_causal_twin_timeseries/cold-start-transfer.json"),
      "utf8",
    ),
  );
  const privateRoot = path.join(
    projectRoot,
    "data/tokenfactory_teacher_v10/_causal_twin_audit",
  );
  await fs.mkdir(privateRoot, { recursive: true });
  const browser = await chromium.connectOverCDP(CDP_URL);
  const page = await locateProfilePage(browser);
  const openingUsage = await fetchUsage(page);
  const calls = [];
  for (const spec of MODELS) {
    const prompt = promptFor(spec.role, manifest, benchmark, transfer);
    const result = await callOfficial(page, {
      model: spec.model,
      messages: [
        {
          role: "system",
          content:
            "Produce concise, falsifiable engineering review artifacts. Do not reveal hidden reasoning.",
        },
        { role: "user", content: prompt },
      ],
      temperature: spec.temperature,
      max_tokens: 3072,
      chat_template_kwargs: { enable_thinking: false },
    });
    const rawRecord = {
      schema: "ProofLaunchOfficialCausalTwinAuditEpisodeV1",
      role: spec.role,
      requested_model: spec.model,
      result,
      prompt_sha256: sha256(prompt),
      accepted_as_training_material: false,
      training_admission_reason: "AMD output-training terms not captured",
    };
    await fs.writeFile(
      path.join(privateRoot, `${spec.role}.json`),
      `${JSON.stringify(rawRecord, null, 2)}\n`,
      "utf8",
    );
    calls.push({
      role: spec.role,
      requested_model: spec.model,
      returned_model: result.model,
      http_status: result.http_status,
      ok: result.ok,
      response_id_present: Boolean(result.response_id),
      finish_reason: result.finish_reason,
      usage: result.usage,
      output_sha256: result.content ? sha256(result.content) : null,
      output_bytes: Buffer.byteLength(result.content || "", "utf8"),
      error_code: result.error_code,
      accepted_as_training_material: false,
    });
  }
  const closingUsage = await fetchUsage(page);
  const receipt = {
    schema: "ProofLaunchOfficialCausalTwinAuditReceiptV1",
    provider: "AMD Radeon Token Factory",
    official_endpoint: "https://developer.amd.com.cn/radeon/api/v1/chat/completions",
    todos: ["1203", "1204", "1205", "1206"],
    opening_usage: openingUsage,
    closing_usage: closingUsage,
    spend_delta_usd:
      closingUsage.daily_cost_used_usd - openingUsage.daily_cost_used_usd,
    calls,
    raw_output_directory: "private:data/tokenfactory_teacher_v10/_causal_twin_audit",
    credential_persisted: false,
    raw_output_published: false,
    output_training_rights_captured: false,
    accepted_as_training_material: false,
    truth_boundary:
      "This receipt proves official API review calls only. It does not prove Radeon-local inference, fine-tuning, business lift, or output-training rights.",
  };
  const receiptPath = path.join(
    projectRoot,
    "evidence/v10/causal-twin-official-api-audit.json",
  );
  await fs.writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  process.stdout.write(
    `${JSON.stringify({
      receipt: receiptPath,
      calls: calls.map((item) => ({
        role: item.role,
        model: item.returned_model,
        http_status: item.http_status,
        ok: item.ok,
        output_bytes: item.output_bytes,
      })),
      spend_delta_usd: receipt.spend_delta_usd,
      remaining_usd: closingUsage.daily_cost_remaining_usd,
      accepted_as_training_material: false,
    })}\n`,
  );
}


await main();
