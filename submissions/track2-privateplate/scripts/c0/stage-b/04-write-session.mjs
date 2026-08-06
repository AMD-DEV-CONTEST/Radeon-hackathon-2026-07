#!/usr/bin/env node
import { createHash } from "node:crypto";
import {
  access,
  copyFile,
  mkdir,
  readFile,
  rename,
  stat,
  writeFile
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  resolveAccountProfile,
  resolveTemplateProfile
} from "./account-profile.mjs";
import { writeCollectionSummary } from "./collection-summary.mjs";
import { assertVerifiedRadeonEnvironment } from "./evidence-guard.mjs";
import { resolveC0bOutDir } from "./resolve-out-dir.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const outDir = resolveC0bOutDir(root);
const outPath = path.join(outDir, "cloud-session.json");
const collectionSummaryPath = path.join(outDir, "collection-summary.json");

await mkdir(outDir, { recursive: true });
const environment = await assertVerifiedRadeonEnvironment(
  path.join(outDir, "environment.json")
);
const existing = await readOptionalJson(outPath);
const accountProfile = resolveAccountProfile({
  accountChannel:
    process.env.PRIVATEPLATE_ACCOUNT_CHANNEL ?? existing?.account_channel,
  profileUrl: process.env.PRIVATEPLATE_PROFILE_URL ?? existing?.profile_url,
  requireCurrent: existing == null
});
const templateProfile = resolveTemplateProfile({
  storageMode:
    process.env.PRIVATEPLATE_STORAGE_MODE ??
    existing?.storage_mode ??
    environment.storage_mode,
  modelDirectory:
    process.env.PRIVATEPLATE_MODEL_DIRECTORY ??
    existing?.model_directory ??
    environment.model_directory
});
const toolSummary =
  (await readOptionalJson(path.join(outDir, "tool-calling-summary.json"))) ??
  existing?.tool_calling ??
  null;
const activeModel =
  process.env.PRIVATEPLATE_MODEL_ACTIVE ??
  (await readOptionalText(path.join(outDir, "raw/active-model.txt"))) ??
  existing?.model_active ??
  null;
const destroyStatus =
  process.env.PRIVATEPLATE_DESTROY_STATUS ??
  existing?.destroy_status ??
  "NOT_REQUIRED_FREE_INSTANCE";
if (
  ![
    "NOT_REQUIRED_FREE_INSTANCE",
    "PENDING_USER_DESTROY",
    "DESTROYED"
  ].includes(destroyStatus)
) {
  throw new Error(
    "PRIVATEPLATE_DESTROY_STATUS must be NOT_REQUIRED_FREE_INSTANCE, PENDING_USER_DESTROY, or DESTROYED."
  );
}

const instanceId =
  process.env.PRIVATEPLATE_INSTANCE_ID ??
  existing?.instance_id ??
  environment.instance_id ??
  null;
const creditsBefore =
  process.env.PRIVATEPLATE_CREDITS_BEFORE ??
  existing?.credits_before ??
  environment.credits_before ??
  null;
const creditsAfter =
  process.env.PRIVATEPLATE_CREDITS_AFTER ??
  existing?.credits_after ??
  null;
if (!nonEmpty(instanceId)) {
  throw new Error("Formal session evidence requires instance_id.");
}

const operatorReceipts = {
  ...(existing?.operator_receipts ?? {})
};
operatorReceipts.credits_before = await mergeReceipt({
  name: "credits-before",
  source: process.env.PRIVATEPLATE_CREDITS_BEFORE_RECEIPT,
  existing: operatorReceipts.credits_before
});
operatorReceipts.destroy = await mergeReceipt({
  name: "destroy",
  source: process.env.PRIVATEPLATE_DESTROY_RECEIPT,
  existing: operatorReceipts.destroy
});
operatorReceipts.credits_after = await mergeReceipt({
  name: "credits-after",
  source: process.env.PRIVATEPLATE_CREDITS_AFTER_RECEIPT,
  existing: operatorReceipts.credits_after
});

const now = new Date().toISOString();
const payload = {
  ...existing,
  schema_version: "3.2",
  stage: "C0-B",
  provider_mode: "local_vllm_radeon",
  remote_api: false,
  evidence_eligible: true,
  account_channel: accountProfile.account_channel,
  profile_url: accountProfile.profile_url,
  storage_mode: templateProfile.storage_mode,
  model_directory: templateProfile.model_directory,
  instance_id: instanceId,
  resource_type:
    process.env.PRIVATEPLATE_RESOURCE_TYPE ??
    existing?.resource_type ??
    "gpu_notebook",
  credits_before: creditsBefore,
  credits_after: creditsAfter,
  billing_mode:
    process.env.PRIVATEPLATE_BILLING_MODE ??
    existing?.billing_mode ??
    "FREE_INSTANCE_OWNER_CONFIRMED",
  operator_receipts: operatorReceipts,
  started_at_utc:
    process.env.PRIVATEPLATE_SESSION_STARTED_AT ??
    existing?.started_at_utc ??
    environment.collected_at_utc ??
    null,
  collection_completed_at_utc:
    existing?.collection_completed_at_utc ?? now,
  ended_at_utc:
    destroyStatus !== "PENDING_USER_DESTROY"
      ? process.env.PRIVATEPLATE_SESSION_ENDED_AT ??
        existing?.ended_at_utc ??
        now
      : null,
  destroy_status: destroyStatus,
  model_active: activeModel,
  node_version: environment.node_version,
  git_commit: environment.git_commit ?? existing?.git_commit ?? null,
  git_dirty: environment.git_dirty ?? existing?.git_dirty ?? null,
  source_integrity_verified:
    environment.source_integrity_verified ??
    existing?.source_integrity_verified ??
    false,
  source_integrity_mode:
    environment.source_integrity_mode ??
    existing?.source_integrity_mode ??
    null,
  source_manifest_sha256:
    environment.source_manifest_sha256 ??
    existing?.source_manifest_sha256 ??
    null,
  source_file_count:
    environment.source_file_count ?? existing?.source_file_count ?? null,
  tool_calling: toolSummary,
  operator_checklist: [
    "Copy this run directory back to the local repository",
    "Confirm collection-summary.json status is EVIDENCE_COMPLETE"
  ],
  notes:
    "The current Global instance is owner-confirmed free to keep running. Destroy and credit receipts are optional metadata, not model-quality gates."
};

await writeJsonAtomic(outPath, payload);
let collectionStatus = null;
if (await exists(collectionSummaryPath)) {
  const summary = await writeCollectionSummary({ outDir });
  collectionStatus = summary.status;
  if (summary.status !== "EVIDENCE_COMPLETE") {
    process.exitCode = 2;
  }
}

// Re-inventory after session metadata changes so the catalog is not stale.
let inventoryStatus = null;
try {
  const { spawnSync } = await import("node:child_process");
  const inv = spawnSync(
    process.execPath,
    [path.join(root, "scripts/c0/stage-b/write-evidence-inventory.mjs")],
    {
      cwd: root,
      env: {
        ...process.env,
        PRIVATEPLATE_C0B_OUT_DIR: outDir,
        PRIVATEPLATE_RUN_ID: process.env.PRIVATEPLATE_RUN_ID ?? path.basename(outDir)
      },
      encoding: "utf8"
    }
  );
  inventoryStatus = inv.status === 0 ? "REFRESHED" : "FAIL";
  if (inv.status !== 0) {
    console.error(inv.stdout + inv.stderr);
    process.exitCode = 2;
  }
} catch (error) {
  inventoryStatus = "ERROR";
  console.error(String(error?.message ?? error));
  process.exitCode = 2;
}

console.log(
  JSON.stringify(
    {
      wrote: outPath,
      destroy_status: payload.destroy_status,
      collection_status: collectionStatus,
      evidence_inventory: inventoryStatus,
      note:
        "Evidence inventory refreshed after session metadata update."
    },
    null,
    2
  )
);

async function mergeReceipt({ name, source, existing: existingReceipt }) {
  if (!source) return existingReceipt ?? { status: "NOT_REQUIRED" };
  const sourcePath = path.resolve(source);
  const bytes = await readFile(sourcePath);
  if (bytes.length === 0) {
    throw new Error(`${name} receipt is empty.`);
  }
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  const extension = /^\.[a-z0-9]{1,8}$/i.test(path.extname(sourcePath))
    ? path.extname(sourcePath).toLowerCase()
    : ".bin";
  const receiptDir = path.join(outDir, "raw", "operator-receipts");
  const destination = path.join(receiptDir, `${name}${extension}`);
  await mkdir(receiptDir, { recursive: true });

  if (path.resolve(sourcePath) !== path.resolve(destination)) {
    try {
      const current = await readFile(destination);
      const currentSha = createHash("sha256").update(current).digest("hex");
      if (currentSha !== sha256) {
        throw new Error(`Refusing to replace the existing ${name} receipt.`);
      }
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      await copyFile(sourcePath, destination);
    }
  }
  const destinationStat = await stat(destination);
  return {
    status: "CAPTURED",
    path: path.relative(outDir, destination),
    sha256,
    size_bytes: destinationStat.size,
    recorded_at_utc: new Date().toISOString()
  };
}

async function readOptionalJson(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function readOptionalText(filePath) {
  try {
    const value = (await readFile(filePath, "utf8")).trim();
    return value || null;
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function exists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

function nonEmpty(value) {
  return typeof value === "string" && value.trim().length > 0;
}

async function writeJsonAtomic(filePath, value) {
  const tempPath = `${filePath}.${process.pid}.tmp`;
  await writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(tempPath, filePath);
}
