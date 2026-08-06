import { readFile } from "node:fs/promises";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

export function assertLoopbackProvider(baseUrl) {
  const url = new URL(baseUrl);
  const hostname = url.hostname;
  if (url.protocol !== "http:" || !LOOPBACK_HOSTS.has(hostname)) {
    throw new Error("C0-B evidence requires an HTTP loopback vLLM endpoint.");
  }
  return hostname;
}

export async function assertVerifiedRadeonEnvironment(environmentPath) {
  const environment = JSON.parse(await readFile(environmentPath, "utf8"));
  const nodeVersionValid = isSupportedNodeVersion(environment.node_version);
  const sourceIntegrityValid = hasVerifiedSourceIntegrity(environment);
  const verified =
    environment.evidence_eligible === true &&
    typeof environment.gpu_name === "string" &&
    /AMD|Radeon/i.test(environment.gpu_name) &&
    typeof environment.driver === "string" &&
    environment.driver.length > 0 &&
    environment.rocm_verified === true &&
    environment.node_preflight === "PASS" &&
    nodeVersionValid &&
    typeof environment.git_commit === "string" &&
    /^[0-9a-f]{40}$/i.test(environment.git_commit) &&
    environment.git_dirty === false &&
    sourceIntegrityValid;

  if (!verified) {
    throw new Error(
      "C0-B evidence requires verified Radeon/ROCm, Node.js >=22.13, an exact clean Git commit and re-checkable source integrity in environment.json from step 00."
    );
  }

  return environment;
}

function hasVerifiedSourceIntegrity(environment) {
  const commonFieldsValid =
    environment.source_integrity_verified === true &&
    Number.isInteger(environment.source_file_count) &&
    environment.source_file_count > 0;
  if (!commonFieldsValid) return false;

  if (environment.source_provenance === "git") {
    return (
      environment.source_integrity_mode === "git" &&
      environment.source_manifest_sha256 === null
    );
  }
  if (environment.source_provenance === "packed_clean_commit") {
    return (
      environment.source_integrity_mode === "packed_manifest" &&
      typeof environment.source_manifest_sha256 === "string" &&
      /^[0-9a-f]{64}$/i.test(environment.source_manifest_sha256)
    );
  }
  return false;
}

function isSupportedNodeVersion(value) {
  const match = /^v?(\d+)\.(\d+)\./.exec(String(value ?? ""));
  if (!match) return false;
  const major = Number(match[1]);
  const minor = Number(match[2]);
  return major > 22 || (major === 22 && minor >= 13);
}
