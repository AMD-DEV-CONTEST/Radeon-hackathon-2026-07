import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  evaluateCollectionEvidence,
  validateBaseline
} from "./collection-evaluation.mjs";
import {
  evaluatePinnedRuntime,
  listHubCacheRoots,
  resolveHubCache,
  resolveModelSnapshotDir
} from "./runtime-checks.mjs";
import { writeCollectionSummary } from "./collection-summary.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));

test("pinned runtime requires every exact version, parser, hardware field, and image receipt", () => {
  const input = runtimeInput();
  const result = evaluatePinnedRuntime(input);
  assert.equal(result.status, "PASS");

  const wrong = evaluatePinnedRuntime({
    ...input,
    runtime: { ...input.runtime, transformers: "5.5.4" }
  });
  assert.equal(wrong.status, "FAIL");
  assert.ok(wrong.errors.some((value) => value.startsWith("transformers:")));
});

test("HF cache resolution honors HF_HUB_CACHE and expands HF_HOME to hub", () => {
  assert.equal(
    resolveHubCache({
      HF_HUB_CACHE: "/cache/direct",
      HF_HOME: "/cache/home"
    }),
    "/cache/direct"
  );
  assert.equal(resolveHubCache({ HF_HOME: "/cache/home" }), "/cache/home/hub");
  assert.equal(
    resolveHubCache({ HUGGINGFACE_HUB_CACHE: "/legacy/flat" }),
    "/legacy/flat"
  );
});

test("model snapshot resolves hub layout and legacy flat HF_HOME layout", async () => {
  const base = await mkdtemp(path.join(tmpdir(), "hf-cache-"));
  try {
    const hubRoot = path.join(base, "hub");
    const flatRoot = base;
    const rev = "rev-abc";
    const modelId = "Qwen/Qwen2.5-14B-Instruct";
    const weight = "model-00001-of-00008.safetensors";

    // Standard hub layout (Gemma-style).
    const gemmaSnap = path.join(
      hubRoot,
      "models--google--gemma-4-12B-it-qat-w4a16-ct",
      "snapshots",
      rev
    );
    await mkdir(gemmaSnap, { recursive: true });
    await writeFile(path.join(gemmaSnap, "model.safetensors"), "gemma");

    // Legacy flat layout written when HUGGINGFACE_HUB_CACHE=$HF_HOME.
    const qwenSnap = path.join(
      flatRoot,
      "models--Qwen--Qwen2.5-14B-Instruct",
      "snapshots",
      rev
    );
    await mkdir(qwenSnap, { recursive: true });
    await writeFile(path.join(qwenSnap, weight), "qwen");

    // HOME is still listed as a fallback after HF_HOME roots.
    const env = { HF_HOME: base, HOME: "/unused" };
    const roots = listHubCacheRoots(env);
    assert.equal(roots[0], path.resolve(hubRoot));
    assert.equal(roots[1], path.resolve(flatRoot));
    assert.ok(roots.includes(path.resolve("/unused/.cache/huggingface/hub")));

    assert.equal(
      resolveModelSnapshotDir({
        env,
        modelId: "google/gemma-4-12B-it-qat-w4a16-ct",
        revision: rev,
        weightFiles: ["model.safetensors"]
      }),
      path.resolve(gemmaSnap)
    );

    assert.equal(
      resolveModelSnapshotDir({
        env,
        modelId,
        revision: rev,
        weightFiles: [weight]
      }),
      path.resolve(qwenSnap)
    );

    // Prefer hub over flat when both exist for the same model.
    const dualHub = path.join(
      hubRoot,
      "models--Qwen--Qwen2.5-14B-Instruct",
      "snapshots",
      rev
    );
    await mkdir(dualHub, { recursive: true });
    await writeFile(path.join(dualHub, weight), "qwen-hub");
    assert.equal(
      resolveModelSnapshotDir({
        env,
        modelId,
        revision: rev,
        weightFiles: [weight]
      }),
      path.resolve(dualHub)
    );
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

test("free Global instance evidence completes without credit or Destroy receipts", () => {
  const input = collectionInput();
  const freeInstance = evaluateCollectionEvidence({
    ...input,
    session: {
      account_channel: "GLOBAL",
      profile_url: "https://radeon-global.anruicloud.com/",
      storage_mode: "PERSISTENT_PVC",
      model_directory: "none",
      instance_id: "instance-1",
      credits_before: null,
      credits_after: null,
      destroy_status: "NOT_REQUIRED_FREE_INSTANCE",
      ended_at_utc: "2026-07-26T00:00:00Z"
    },
    receiptVerification: {
      status: "NOT_REQUIRED",
      failures: []
    }
  });
  assert.equal(freeInstance.capture_status, "PASS");
  assert.equal(freeInstance.status, "EVIDENCE_COMPLETE");

  const complete = evaluateCollectionEvidence(input);
  assert.equal(complete.status, "EVIDENCE_COMPLETE");

  const incomplete = evaluateCollectionEvidence({
    ...input,
    session: { ...input.session, ended_at_utc: null }
  });
  assert.equal(incomplete.status, "EVIDENCE_FINALIZATION_FAILED");
});

test("missing gate or performance value fails the collection", () => {
  const input = collectionInput();
  const gateFailure = evaluateCollectionEvidence({
    ...input,
    toolSummary: { ...input.toolSummary, privacy_gate: "MISSING" }
  });
  assert.equal(gateFailure.status, "COLLECTION_FAILED");

  const productFailure = evaluateCollectionEvidence({
    ...input,
    productAgent: { ...input.productAgent, status: "FAIL", failed_count: 1 }
  });
  assert.equal(productFailure.status, "COLLECTION_FAILED");
  assert.ok(
    productFailure.capture_failures.includes("product_agent:status")
  );

  const publicGoldenFailure = evaluateCollectionEvidence({
    ...input,
    publicGolden: {
      ...input.publicGolden,
      product_completion: { gate: "FAIL" }
    }
  });
  assert.equal(publicGoldenFailure.status, "COLLECTION_FAILED");
  assert.ok(
    publicGoldenFailure.capture_failures.includes(
      "public_golden:product_completion"
    )
  );

  const invalidBaseline = {
    ...input.baseline,
    warm_tokens_per_sec: { p50: null, p90: null, n: 0 }
  };
  assert.ok(validateBaseline(invalidBaseline).includes("warm_tokens_per_sec"));
  const performanceFailure = evaluateCollectionEvidence({
    ...input,
    baseline: invalidBaseline
  });
  assert.equal(performanceFailure.status, "COLLECTION_FAILED");
});

test("failure summary records product-agent failure and the sealed run log", async () => {
  const evidenceRoot = path.join(root, "benchmarks/c0/stage-b");
  const outDir = await mkdtemp(
    path.join(evidenceRoot, "privateplate-failure-summary-test-")
  );
  try {
    await mkdir(path.join(outDir, "raw"), { recursive: true });
    await writeJson(path.join(outDir, "tool-calling-summary.json"), {
      overall_gate: "PASS"
    });
    await writeJson(path.join(outDir, "product-agent-e2e-summary.json"), {
      status: "FAIL",
      failed_count: 1
    });
    await writeJson(path.join(outDir, "collection-summary.json"), {
      capture_status: "PASS",
      finalization_status: "PASS"
    });
    await writeFile(path.join(outDir, "raw/run-all.log"), "complete log\n");

    const { spawnSync } = await import("node:child_process");
    const result = spawnSync(
      process.execPath,
      [path.join(root, "scripts/c0/stage-b/write-failure-summary.mjs")],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          PRIVATEPLATE_C0B_OUT_DIR: outDir,
          PRIVATEPLATE_RUN_ID: path.basename(outDir),
          PRIVATEPLATE_OVERALL_EXIT: "2",
          PRIVATEPLATE_FAILURE_REASON: "",
          PRIVATEPLATE_TOOL_STEP_STATUS: "0",
          PRIVATEPLATE_PRODUCT_AGENT_STEP_STATUS: "2",
          PRIVATEPLATE_PUBLIC_GOLDEN_STEP_STATUS: "2",
          PRIVATEPLATE_BASELINE_STEP_STATUS: "0",
          PRIVATEPLATE_SESSION_STEP_STATUS: "0",
          PRIVATEPLATE_ARTIFACT_STEP_STATUS: "0"
        }
      }
    );
    assert.equal(result.status, 2, result.stdout + result.stderr);

    const summary = JSON.parse(
      await readFile(path.join(outDir, "raw/failure-summary.json"), "utf8")
    );
    assert.equal(summary.step_status.product_agent, "2");
    assert.equal(summary.step_status.public_golden, "2");
    assert.equal(summary.files_present.product_agent_summary, true);
    assert.equal(summary.files_present.run_all_log, true);
    assert.ok(summary.failures.includes("product_agent_e2e_failed"));
    assert.ok(summary.failures.includes("step_product_agent_exit_2"));
  } finally {
    await rm(outDir, { recursive: true, force: true });
  }
});

test("historical China account metadata cannot pass a new formal collection", () => {
  const input = collectionInput();
  const result = evaluateCollectionEvidence({
    ...input,
    session: {
      ...input.session,
      account_channel: "CHINA_MAINLAND",
      profile_url: "https://developer.amd.com.cn/radeon/profile"
    }
  });

  assert.equal(result.status, "COLLECTION_FAILED");
  assert.ok(result.capture_failures.includes("session:account_profile"));
});

test("collection summary re-hashes copied operator receipts", async () => {
  const outDir = await mkdtemp(path.join(tmpdir(), "privateplate-summary-"));
  try {
    const input = collectionInput();
    const receiptDir = path.join(outDir, "raw", "operator-receipts");
    await mkdir(receiptDir, { recursive: true });
    const operatorReceipts = {};
    for (const name of ["credits_before", "destroy", "credits_after"]) {
      const bytes = Buffer.from(`${name}-original`);
      const fileName = `${name}.txt`;
      await writeFile(path.join(receiptDir, fileName), bytes);
      operatorReceipts[name] = {
        status: "CAPTURED",
        path: `raw/operator-receipts/${fileName}`,
        sha256: createHash("sha256").update(bytes).digest("hex"),
        size_bytes: bytes.length
      };
    }
    await writeJson(path.join(outDir, "tool-calling-summary.json"), input.toolSummary);
    await writeJson(
      path.join(outDir, "product-agent-e2e-summary.json"),
      input.productAgent
    );
    await writeJson(
      path.join(outDir, "public-golden-summary.json"),
      input.publicGolden
    );
    await writeJson(path.join(outDir, "baseline-results.json"), input.baseline);
    await writeJson(path.join(outDir, "environment.json"), input.environment);
    await writeJson(path.join(outDir, "cloud-session.json"), {
      ...input.session,
      operator_receipts: operatorReceipts
    });
    await writeJson(
      path.join(outDir, "raw/model-artifact-verification.json"),
      input.artifact
    );
    await writeJson(
      path.join(outDir, "raw/runtime-pin-verification.json"),
      input.runtimePin
    );
    const env = {
      PRIVATEPLATE_TOOL_STEP_STATUS: "0",
      PRIVATEPLATE_PRODUCT_AGENT_STEP_STATUS: "0",
      PRIVATEPLATE_PUBLIC_GOLDEN_STEP_STATUS: "0",
      PRIVATEPLATE_BASELINE_STEP_STATUS: "0",
      PRIVATEPLATE_SESSION_STEP_STATUS: "0",
      PRIVATEPLATE_ARTIFACT_STEP_STATUS: "0"
    };
    const complete = await writeCollectionSummary({ outDir, env });
    assert.equal(complete.status, "EVIDENCE_COMPLETE");

    await writeFile(
      path.join(receiptDir, "destroy.txt"),
      "tampered"
    );
    const tampered = await writeCollectionSummary({ outDir, env });
    assert.equal(tampered.status, "EVIDENCE_FINALIZATION_FAILED");
  } finally {
    await rm(outDir, { recursive: true, force: true });
  }
});

function runtimeInput() {
  const profile = {
    model_id: "model",
    revision: "a".repeat(40),
    tool_call_parser: "gemma4",
    reasoning_parser: "gemma4",
    quantization: { vllm_quantization_arg: "compressed-tensors" },
    chat_template: { sha256: "b".repeat(64) },
    kv_cache_memory_bytes: 8589934592,
    license: "apache-2.0",
    license_link: "https://example.test/license"
  };
  const candidatePin = {
    model_id: profile.model_id,
    revision: profile.revision,
    tool_call_parser: "gemma4",
    reasoning_parser: "gemma4",
    quantization: "compressed-tensors",
    chat_template_sha256: profile.chat_template.sha256,
    kv_cache_memory_bytes: profile.kv_cache_memory_bytes
  };
  return {
    pin: {
      python: { major: 3, minor: 12 },
      node: { major_min: 22, minor_min: 13 },
      vllm: {
        exact_version: "0.25.1+rocm723",
        required_cli_flags: [
          "--tool-call-parser",
          "--reasoning-parser",
          "--kv-cache-memory-bytes",
          "--attention-backend",
          "--chat-template",
          "--enable-auto-tool-choice"
        ]
      },
      torch: {
        exact_base_version: "2.11.0",
        hip_version_prefix: "7.2"
      },
      transformers: { exact_version: "5.14.1" },
      compressed_tensors: { exact_version: "0.17.0" },
      rocm: { exact_version: "7.2.3" },
      hardware: {
        gfx_architecture: "gfx1100",
        compute_units: 96,
        min_total_memory_bytes: 50_000_000_000,
        max_total_memory_bytes: 52_000_000_000,
        expected_gpu_count: 1
      },
      image: {
        digest_pattern: "^sha256:[0-9a-f]{64}$",
        receipt_must_contain_digest: true
      }
    },
    profile,
    candidatePin,
    runtime: {
      python: { major: 3, minor: 12, patch: 10 },
      vllm: "0.25.1+rocm723",
      torch: "2.11.0+rocm7.2.3",
      hip: "7.2.3",
      transformers: "5.14.1",
      compressed_tensors: "0.17.0",
      rocm: "7.2.3",
      cuda_available_flag: true,
      device_count: 1
    },
    environment: {
      node_version: "v22.14.0",
      hardware: {
        gfx_architecture: "gfx1100",
        compute_units: 96,
        total_memory_bytes: 51_522_830_336
      }
    },
    imageDigest: `sha256:${"c".repeat(64)}`,
    imageReceipt: {
      status: "CAPTURED",
      sha256: "d".repeat(64),
      size_bytes: 100,
      contains_digest: true
    },
    cliHelp:
      "--tool-call-parser gemma4 --reasoning-parser gemma4 --kv-cache-memory-bytes --attention-backend --chat-template --enable-auto-tool-choice"
  };
}

function collectionInput() {
  const request = {
    ttft_ms: 100,
    total_ms: 1_000,
    prompt_tokens: 10,
    completion_tokens: 20,
    tokens_per_sec: 22,
    usage_reported: true,
    tool_call_count: 1
  };
  return {
    steps: {
      tool_gate: 0,
      product_agent: 0,
      public_golden: 0,
      baseline: 0,
      session_metadata: 0,
      artifact_verification: 0
    },
    toolSummary: {
      overall_gate: "PASS",
      model_capability_gate: "PASS",
      production_safety_gate: "PASS",
      privacy_gate: "PASS",
      effective_policy_gate: "PASS",
      regression_gate: { overall_gate: "PASS" },
      holdout_gate: { overall_gate: "PASS" },
      combined_gate: { overall_gate: "PASS" }
    },
    productAgent: {
      status: "PASS",
      sample_count: 2,
      failed_count: 0
    },
    publicGolden: {
      status: "PASS",
      sample_count: 36,
      model_capability: { gate: "PASS" },
      product_completion: { gate: "PASS" },
      safety: { gate: "PASS" }
    },
    baseline: {
      measurement_status: "PASS",
      workload: {
        kind: "product_tool_routing_prompt",
        tool_count: 5
      },
      benchmark_configuration: {
        warm_run_count: 5,
        kv_cache_memory_bytes: 8589934592
      },
      first_baseline_request_after_readiness_check: request,
      warm_runs: Array.from({ length: 5 }, () => ({ ...request })),
      warm_ttft_ms: { p50: 100, p90: 110, n: 5 },
      warm_tokens_per_sec: { p50: 22, p90: 24, n: 5 },
      peak_vram: {
        status: "CAPTURED",
        peak_used_bytes: 20_000_000_000,
        total_bytes: 51_000_000_000,
        sample_count: 10,
        sampling_failures: 0
      }
    },
    session: {
      account_channel: "GLOBAL",
      profile_url: "https://radeon-global.anruicloud.com/",
      storage_mode: "PERSISTENT_PVC",
      model_directory: "none",
      instance_id: "instance-1",
      credits_before: "10",
      credits_after: "9",
      destroy_status: "DESTROYED",
      ended_at_utc: "2026-07-26T00:00:00Z"
    },
    environment: {
      evidence_eligible: true,
      source_integrity_verified: true
    },
    artifact: { status: "PASS", phase: "POSTSTART" },
    runtimePin: { status: "PASS", phase: "PRESTART" },
    receiptVerification: { status: "PASS", failures: [] }
  };
}

async function writeJson(filePath, value) {
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
