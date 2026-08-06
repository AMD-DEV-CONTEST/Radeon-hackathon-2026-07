#!/usr/bin/env node
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  assertLoopbackProvider,
  assertVerifiedRadeonEnvironment
} from "./evidence-guard.mjs";
import {
  resolveAccountProfile,
  resolveTemplateProfile
} from "./account-profile.mjs";
import { verifyRecordedSource } from "./source-integrity.mjs";

import { resolveC0bOutDir } from "./resolve-out-dir.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const environmentPath = path.join(resolveC0bOutDir(root), "environment.json");
const environment = await assertVerifiedRadeonEnvironment(environmentPath);
const sourceIntegrity = await verifyRecordedSource(root, environmentPath);
const accountProfile = resolveAccountProfile({
  accountChannel: environment.account_channel,
  profileUrl: environment.profile_url,
  requireCurrent: true
});
const templateProfile = resolveTemplateProfile({
  storageMode: environment.storage_mode,
  modelDirectory: environment.model_directory
});
const baseUrl =
  process.env.PRIVATEPLATE_VLLM_BASE_URL ?? "http://127.0.0.1:8000/v1";
assertLoopbackProvider(baseUrl);

console.log(
  JSON.stringify(
    {
      status: "PASS",
      account_channel: accountProfile.account_channel,
      profile_url: accountProfile.profile_url,
      ...templateProfile,
      gpu_name: environment.gpu_name,
      node_version: environment.node_version,
      git_commit: environment.git_commit,
      git_dirty: environment.git_dirty,
      source_integrity_mode: sourceIntegrity.mode,
      source_manifest_sha256: sourceIntegrity.manifest_sha256,
      provider_host: new URL(baseUrl).hostname
    },
    null,
    2
  )
);
