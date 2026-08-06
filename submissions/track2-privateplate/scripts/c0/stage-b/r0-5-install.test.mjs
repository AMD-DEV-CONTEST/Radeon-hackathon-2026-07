#!/usr/bin/env node
/**
 * Offline R0-5 tests: install plan, teardown scripts, inventory, failure summary.
 * Does not start Radeon or download models.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const stageB = path.join(root, "scripts/c0/stage-b");

test("verify-install-plan passes offline", () => {
  const result = spawnSync(process.execPath, [path.join(stageB, "verify-install-plan.mjs")], {
    cwd: root,
    encoding: "utf8"
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.status, "PASS");
  assert.equal(payload.radeon_status, "NOT_RUN");
  assert.ok(payload.checks.some((c) => c.name === "run_all_has_teardown_trap" && c.status === "PASS"));
  assert.ok(payload.checks.some((c) => c.name === "run_all_calls_install_runtime" && c.status === "PASS"));
});

test("install-runtime dry-run exits cleanly on non-Radeon host", () => {
  const result = spawnSync(
    "bash",
    [path.join(stageB, "00-install-runtime.sh"), "--dry-run"],
    { cwd: root, encoding: "utf8", env: { ...process.env, PRIVATEPLATE_INSTALL_DRY_RUN: "1" } }
  );
  // On macOS without torch/ROCm, dry-run still prints plan and writes a receipt.
  assert.ok(
    result.status === 0 || result.status === 2,
    `unexpected status ${result.status}\n${result.stdout}\n${result.stderr}`
  );
  assert.match(result.stdout + result.stderr, /dry_run=1|DRY_RUN|PLAN:/);
  assert.match(result.stdout + result.stderr, /vllm|transformers|compressed-tensors/i);
});

test("install-runtime refuses live install without confirmation", () => {
  const result = spawnSync("bash", [path.join(stageB, "00-install-runtime.sh")], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, PRIVATEPLATE_I_CONFIRM_RADEON_RUN: "" }
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr + result.stdout, /Refusing live runtime install/);
});

test("run-all refuses without confirmation and does not start radeon", () => {
  const result = spawnSync("bash", [path.join(stageB, "run-all.sh")], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, PRIVATEPLATE_I_CONFIRM_RADEON_RUN: "" }
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to run C0-B collection/);
});

test("failure summary + evidence inventory work on a fake run dir", async () => {
  const evidenceRoot = path.join(root, "benchmarks/c0/stage-b");
  const runId = `privateplate-r05test-${Date.now()}`;
  const outDir = path.join(evidenceRoot, runId);
  await mkdir(path.join(outDir, "raw"), { recursive: true });
  await writeFile(
    path.join(outDir, "environment.json"),
    JSON.stringify({ note: "fake for r0-5 offline test" }, null, 2) + "\n"
  );
  await writeFile(
    path.join(outDir, "raw/vllm-stop.json"),
    JSON.stringify({
      process_alive_after: false,
      stop_method: "sigterm"
    }) + "\n"
  );

  try {
    const fail = spawnSync(process.execPath, [path.join(stageB, "write-failure-summary.mjs")], {
      cwd: root,
      encoding: "utf8",
      env: {
        ...process.env,
        PRIVATEPLATE_RUN_ID: runId,
        PRIVATEPLATE_C0B_OUT_DIR: outDir,
        PRIVATEPLATE_OVERALL_EXIT: "2",
        PRIVATEPLATE_FAILURE_REASON: "offline_test_failure",
        PRIVATEPLATE_TOOL_STEP_STATUS: "2"
      }
    });
    assert.equal(fail.status, 2, fail.stdout + fail.stderr);
    const summary = JSON.parse(
      await readFile(path.join(outDir, "raw/failure-summary.json"), "utf8")
    );
    assert.equal(summary.status, "FAILED_OR_INCOMPLETE");
    assert.ok(summary.failures.includes("offline_test_failure"));
    assert.equal(summary.instance_lifecycle.status, "NOT_REQUIRED_FREE_INSTANCE");
    assert.match(summary.instance_lifecycle.note, /free to keep running/);

    const inv = spawnSync(process.execPath, [path.join(stageB, "write-evidence-inventory.mjs")], {
      cwd: root,
      encoding: "utf8",
      env: {
        ...process.env,
        PRIVATEPLATE_RUN_ID: runId,
        PRIVATEPLATE_C0B_OUT_DIR: outDir
      }
    });
    assert.equal(inv.status, 0, inv.stdout + inv.stderr);
    const inventory = JSON.parse(
      await readFile(path.join(outDir, "raw/evidence-inventory.json"), "utf8")
    );
    assert.ok(inventory.file_count >= 2);
    assert.ok(inventory.files.some((f) => f.path === "environment.json"));
    assert.ok(inventory.files.some((f) => f.path === "raw/failure-summary.json"));
    assert.match(inventory.catalog_sha256, /^[0-9a-f]{64}$/);
    const seal = JSON.parse(
      await readFile(path.join(outDir, "raw/evidence-inventory.sha256.json"), "utf8")
    );
    assert.match(seal.inventory_sha256, /^[0-9a-f]{64}$/);
    const rerun = spawnSync(
      process.execPath,
      [path.join(stageB, "write-evidence-inventory.mjs")],
      {
        cwd: root,
        encoding: "utf8",
        env: {
          ...process.env,
          PRIVATEPLATE_RUN_ID: runId,
          PRIVATEPLATE_C0B_OUT_DIR: outDir
        }
      }
    );
    assert.equal(rerun.status, 0, rerun.stdout + rerun.stderr);
    const rerunInventory = JSON.parse(
      await readFile(path.join(outDir, "raw/evidence-inventory.json"), "utf8")
    );
    assert.equal(
      rerunInventory.files.some(
        (f) => f.path === "raw/evidence-inventory.sha256.json"
      ),
      false
    );
  } finally {
    await rm(outDir, { recursive: true, force: true });
  }
});

test("stop-vllm is no-op safe without run id", () => {
  const result = spawnSync("bash", [path.join(stageB, "00-stop-vllm.sh")], {
    cwd: root,
    encoding: "utf8",
    env: {
      ...process.env,
      PRIVATEPLATE_RUN_ID: "",
      PRIVATEPLATE_C0B_OUT_DIR: ""
    }
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /nothing to stop|no run id/i);
});

test("stop-vllm on empty formal run dir writes stop receipt", async () => {
  const evidenceRoot = path.join(root, "benchmarks/c0/stage-b");
  const runId = `privateplate-r05stop-${Date.now()}`;
  const outDir = path.join(evidenceRoot, runId);
  await mkdir(path.join(outDir, "raw"), { recursive: true });
  try {
    const result = spawnSync("bash", [path.join(stageB, "00-stop-vllm.sh")], {
      cwd: root,
      encoding: "utf8",
      env: {
        ...process.env,
        PRIVATEPLATE_RUN_ID: runId,
        PRIVATEPLATE_C0B_OUT_DIR: outDir
      }
    });
    assert.equal(result.status, 0, result.stdout + result.stderr);
    const stop = JSON.parse(await readFile(path.join(outDir, "raw/vllm-stop.json"), "utf8"));
    assert.equal(stop.phase, "TEARDOWN");
    assert.equal(stop.process_alive_after, false);
    assert.match(stop.lifecycle_note, /vLLM service stop/);
  } finally {
    await rm(outDir, { recursive: true, force: true });
  }
});

test("parser policy forbids hermes on gemma and gemma parser on qwen", async () => {
  const plan = JSON.parse(await readFile(path.join(stageB, "install-plan.json"), "utf8"));
  assert.equal(plan.parser_policy.gemma4_profiles_must_use.forbid_hermes, true);
  assert.equal(plan.parser_policy.qwen_profiles_must_use.tool_call_parser, "hermes");
  assert.equal(plan.parser_policy.no_cross_parser_fallback, true);
  const profiles = JSON.parse(await readFile(path.join(stageB, "model-profiles.json"), "utf8"));
  const gemma = profiles.profiles[profiles.primary_profile];
  assert.equal(gemma.tool_call_parser, "gemma4");
  assert.notEqual(gemma.tool_call_parser, "hermes");
  assert.equal(profiles.profiles.qwen14.tool_call_parser, "hermes");
});

test("runtime-pin references install plan and stop script", async () => {
  const pin = JSON.parse(await readFile(path.join(stageB, "runtime-pin.json"), "utf8"));
  assert.equal(pin.install_plan_path, "scripts/c0/stage-b/install-plan.json");
  assert.equal(pin.install_script, "scripts/c0/stage-b/00-install-runtime.sh");
  assert.equal(pin.stop_script, "scripts/c0/stage-b/00-stop-vllm.sh");
  assert.equal(pin.vllm.exact_version, "0.25.1+rocm723");
  assert.ok(pin.vllm.wheel_url.includes("752a3a504485790a2e8491cacbb35c137339ad34"));
  assert.equal(pin.torch.exact_local_version, "2.11.0+gitd0c8b1f");
  assert.ok(String(pin.torch.wheel_url).includes("gitd0c8b1f"));
  assert.ok(Array.isArray(pin.torch.companion_wheel_urls));
  assert.ok(pin.torch.companion_wheel_urls.length >= 1);
});
