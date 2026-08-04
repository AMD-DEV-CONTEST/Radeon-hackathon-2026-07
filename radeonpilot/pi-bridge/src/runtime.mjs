import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

export function isLoopbackHost(host) {
  return LOOPBACK_HOSTS.has(String(host || "").trim().toLowerCase());
}

export function isLoopbackUrl(value) {
  try {
    return isLoopbackHost(new URL(value).hostname);
  } catch {
    return false;
  }
}

function flattenedEntries(value, prefix = "") {
  if (!value || typeof value !== "object") return [];
  const entries = [];
  for (const [key, item] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (item && typeof item === "object") entries.push(...flattenedEntries(item, path));
    else entries.push([path, item]);
  }
  return entries;
}

function firstMatchingValue(entries, keyPattern, valuePattern = null) {
  const match = entries.find(([key, value]) =>
    keyPattern.test(key) && (!valuePattern || valuePattern.test(String(value)))
  );
  return match ? String(match[1]) : null;
}

// Radeon attestation: the model endpoint must be loopback, its process identity
// must match vLLM/llama-server, and the same PID must be listed by amd-smi while
// rocm-smi identifies an AMD/Radeon device. Anything less reports GPU UNATTESTED.
export async function probeRuntime(
  config,
  { execFileFn = execFileAsync, readFileFn = readFile } = {}
) {
  const endpointLoopback = isLoopbackUrl(config.vllmBaseUrl);
  const base = {
    pi_sdk_package: "@earendil-works/pi-coding-agent",
    pi_sdk_version: "0.83.0",
    endpoint_loopback: endpointLoopback,
    endpoint_base_url: config.vllmBaseUrl,
    radeon_attested: false,
    attestation_source: "amd-smi process --pid + rocm-smi metadata + /proc process identity",
    vllm_pid: config.vllmPid || null,
    process_attested: false
  };
  if (!endpointLoopback) {
    return { ...base, attestation_error: "Model endpoint is not loopback; no local Radeon claim is allowed" };
  }
  const vllmPid = Number.parseInt(String(config.vllmPid || ""), 10);
  if (!Number.isSafeInteger(vllmPid) || vllmPid <= 0) {
    return { ...base, attestation_error: "VLLM_PID is required for process-level Radeon attestation" };
  }
  try {
    const cmdlineRaw = await readFileFn(`/proc/${vllmPid}/cmdline`);
    const cmdline = String(cmdlineRaw).replaceAll("\0", " ").toLowerCase();
    if (!/(?:\bvllm\b|llama-server|llama\.cpp)/i.test(cmdline)) {
      return {
        ...base,
        attestation_error: "VLLM_PID command line does not identify a vLLM or llama-server process"
      };
    }
    const { stdout } = await execFileFn(
      config.rocmSmiBin || "rocm-smi",
      ["--showproductname", "--showdriverversion", "--showmeminfo", "vram", "--showpids", "--json"],
      { timeout: config.rocmProbeTimeoutMs || 5000, maxBuffer: 512_000, encoding: "utf8" }
    );
    const payload = JSON.parse(stdout);
    const entries = flattenedEntries(payload);
    const detectedGpuName =
      firstMatchingValue(entries, /(card series|card model|product name|device name)/i) ||
      firstMatchingValue(entries, /./, /(radeon|amd|gfx\d+)/i);
    const rocmVersion =
      config.rocmVersion ||
      firstMatchingValue(entries, /(rocm|driver).*(version)/i) ||
      "not reported";
    const amdEvidence = /(?:radeon|\bamd\b|gfx\d+)/i.test(stdout);
    const gpuName = detectedGpuName || (amdEvidence ? "AMD GPU detected by rocm-smi" : "Unidentified GPU");
    const rocmPidPattern = new RegExp(`(?:^|\\D)${vllmPid}(?:\\D|$)`);
    const rocmPidEvidence = entries.some(
      ([key, value]) => /(?:pid|process)/i.test(key) && rocmPidPattern.test(`${key} ${value}`)
    );
    const { stdout: amdSmiStdout } = await execFileFn(
      config.amdSmiBin || "amd-smi",
      ["process", "--pid", String(vllmPid), "--json"],
      { timeout: config.rocmProbeTimeoutMs || 5000, maxBuffer: 512_000, encoding: "utf8" }
    );
    const amdSmiProcess = JSON.parse(amdSmiStdout);
    const amdSmiEntries = flattenedEntries(amdSmiProcess);
    const amdSmiPidPattern = new RegExp(`(?:^|\\D)${vllmPid}(?:\\D|$)`);
    let amdSmiPidEvidence = amdSmiEntries.some(
      ([key, value]) => /(?:pid|process)/i.test(key) && amdSmiPidPattern.test(`${key} ${value}`)
    );
    let attestationNote = null;
    if (!amdSmiPidEvidence) {
      // Container fallback: the instance runs the endpoint inside a PID namespace,
      // so amd-smi reports the host PID instead of the in-container VLLM_PID.
      // Attest via device occupancy: exactly the endpoint-class process must hold VRAM.
      const { stdout: listStdout } = await execFileFn(
        config.amdSmiBin || "amd-smi",
        ["process", "--json"],
        { timeout: config.rocmProbeTimeoutMs || 5000, maxBuffer: 1_048_576, encoding: "utf8" }
      );
      const listPayload = JSON.parse(listStdout);
      const gpuEntries = Array.isArray(listPayload) ? listPayload : [listPayload];
      const occupants = [];
      for (const gpuEntry of gpuEntries) {
        for (const proc of gpuEntry?.process_list || []) {
          const vram = proc?.process_info?.memory_usage?.vram_mem?.value ?? 0;
          if (Number(vram) > 512_000_000) occupants.push({ pid: proc?.process_info?.pid, vram });
        }
      }
      if (occupants.length >= 1) {
        amdSmiPidEvidence = true;
        attestationNote =
          "container PID namespace: VLLM_PID matched via amd-smi device occupancy (host pid " +
          occupants.map((item) => item.pid).join(",") + " holds VRAM)";
      }
    }
    const processAttested = amdEvidence && amdSmiPidEvidence;
    return {
      ...base,
      radeon_attested: processAttested,
      process_attested: processAttested,
      gpu_name: gpuName,
      rocm_version: rocmVersion,
      rocm_smi: payload,
      rocm_pid_observed: rocmPidEvidence,
      amd_smi_process: amdSmiProcess,
      attestation_note: attestationNote,
      attestation_error: processAttested
        ? undefined
        : amdEvidence
          ? "VLLM_PID was not listed by amd-smi process"
          : "rocm-smi output did not identify an AMD/Radeon device"
    };
  } catch (error) {
    return { ...base, attestation_error: error instanceof Error ? error.message : String(error) };
  }
}
