import { existsSync } from "node:fs";
import path from "node:path";

export function baseVersion(value) {
  const match = String(value ?? "").match(/^(\d+\.\d+\.\d+)/);
  return match?.[1] ?? null;
}

export function evaluatePinnedRuntime({
  pin,
  profile,
  candidatePin,
  runtime,
  environment,
  imageDigest,
  imageReceipt,
  cliHelp
}) {
  const checks = [];

  const check = (name, ok, actual, expected) => {
    checks.push({ name, status: ok ? "PASS" : "FAIL", actual, expected });
  };

  check(
    "profile_model_id",
    profile.model_id === candidatePin.model_id,
    profile.model_id,
    candidatePin.model_id
  );
  check(
    "profile_revision",
    Boolean(profile.revision) && profile.revision === candidatePin.revision,
    profile.revision ?? null,
    candidatePin.revision
  );
  check(
    "profile_tool_parser",
    profile.tool_call_parser === candidatePin.tool_call_parser,
    profile.tool_call_parser ?? null,
    candidatePin.tool_call_parser
  );
  check(
    "profile_reasoning_parser",
    (profile.reasoning_parser ?? null) ===
      (candidatePin.reasoning_parser ?? null),
    profile.reasoning_parser ?? null,
    candidatePin.reasoning_parser ?? null
  );
  check(
    "profile_quantization",
    (profile.quantization?.vllm_quantization_arg ?? null) ===
      (candidatePin.quantization ?? null),
    profile.quantization?.vllm_quantization_arg ?? null,
    candidatePin.quantization ?? null
  );
  check(
    "profile_chat_template",
    (profile.chat_template?.sha256 ?? null) ===
      (candidatePin.chat_template_sha256 ?? null),
    profile.chat_template?.sha256 ?? null,
    candidatePin.chat_template_sha256 ?? null
  );
  check(
    "fixed_kv_cache_memory",
    profile.kv_cache_memory_bytes === candidatePin.kv_cache_memory_bytes,
    profile.kv_cache_memory_bytes ?? null,
    candidatePin.kv_cache_memory_bytes
  );
  check(
    "license_spdx",
    typeof profile.license === "string" && profile.license.length > 0,
    profile.license ?? null,
    "non-empty SPDX identifier"
  );
  check(
    "license_link",
    /^https:\/\//.test(profile.license_link ?? ""),
    profile.license_link ?? null,
    "https URL"
  );

  check(
    "python",
    runtime.python?.major === pin.python.major &&
      runtime.python?.minor === pin.python.minor,
    runtime.python
      ? `${runtime.python.major}.${runtime.python.minor}.${runtime.python.patch}`
      : null,
    `${pin.python.major}.${pin.python.minor}.x`
  );
  const nodeVersion = parseMajorMinor(environment.node_version);
  check(
    "node",
    Boolean(nodeVersion) &&
      (nodeVersion.major > pin.node.major_min ||
        (nodeVersion.major === pin.node.major_min &&
          nodeVersion.minor >= pin.node.minor_min)),
    environment.node_version ?? null,
    `>=${pin.node.major_min}.${pin.node.minor_min}`
  );
  check(
    "vllm",
    runtime.vllm === pin.vllm.exact_version,
    runtime.vllm ?? null,
    pin.vllm.exact_version
  );
  check(
    "torch",
    baseVersion(runtime.torch) === pin.torch.exact_base_version,
    runtime.torch ?? null,
    `${pin.torch.exact_base_version}+ROCm build`
  );
  check(
    "torch_hip",
    typeof runtime.hip === "string" &&
      runtime.hip.startsWith(pin.torch.hip_version_prefix),
    runtime.hip ?? null,
    `${pin.torch.hip_version_prefix}.x`
  );
  check(
    "torch_device_available",
    runtime.cuda_available_flag === true,
    runtime.cuda_available_flag ?? null,
    true
  );
  check(
    "transformers",
    runtime.transformers === pin.transformers.exact_version,
    runtime.transformers ?? null,
    pin.transformers.exact_version
  );
  check(
    "compressed_tensors",
    runtime.compressed_tensors === pin.compressed_tensors.exact_version,
    runtime.compressed_tensors ?? null,
    pin.compressed_tensors.exact_version
  );
  const allowedRocm = Array.isArray(pin.rocm.allowed_versions)
    ? pin.rocm.allowed_versions
    : [pin.rocm.exact_version];
  check(
    "rocm",
    allowedRocm.includes(runtime.rocm),
    runtime.rocm ?? null,
    allowedRocm.join("|")
  );

  for (const flag of pin.vllm.required_cli_flags ?? []) {
    check(
      `vllm_cli_${flag.slice(2).replaceAll("-", "_")}`,
      cliHelp.includes(flag),
      cliHelp.includes(flag) ? flag : null,
      flag
    );
  }
  check(
    "vllm_tool_parser_registered",
    cliHelp.includes(candidatePin.tool_call_parser),
    candidatePin.tool_call_parser,
    `CLI help contains ${candidatePin.tool_call_parser}`
  );
  if (candidatePin.reasoning_parser) {
    check(
      "vllm_reasoning_parser_registered",
      cliHelp.includes(candidatePin.reasoning_parser),
      candidatePin.reasoning_parser,
      `CLI help contains ${candidatePin.reasoning_parser}`
    );
  }

  const hardware = environment.hardware ?? {};
  check(
    "hardware_gfx",
    hardware.gfx_architecture === pin.hardware.gfx_architecture,
    hardware.gfx_architecture ?? null,
    pin.hardware.gfx_architecture
  );
  check(
    "hardware_compute_units",
    hardware.compute_units === pin.hardware.compute_units,
    hardware.compute_units ?? null,
    pin.hardware.compute_units
  );
  check(
    "hardware_vram",
    Number.isFinite(hardware.total_memory_bytes) &&
      hardware.total_memory_bytes >= pin.hardware.min_total_memory_bytes &&
      hardware.total_memory_bytes <= pin.hardware.max_total_memory_bytes,
    hardware.total_memory_bytes ?? null,
    `${pin.hardware.min_total_memory_bytes}..${pin.hardware.max_total_memory_bytes}`
  );
  check(
    "hardware_gpu_count",
    runtime.device_count === pin.hardware.expected_gpu_count,
    runtime.device_count ?? null,
    pin.hardware.expected_gpu_count
  );

  const digestPattern = new RegExp(pin.image.digest_pattern);
  check(
    "image_digest",
    digestPattern.test(imageDigest ?? ""),
    imageDigest ?? null,
    pin.image.digest_pattern
  );
  check(
    "image_metadata_receipt",
    imageReceipt?.status === "CAPTURED" &&
      /^[0-9a-f]{64}$/.test(imageReceipt.sha256 ?? "") &&
      imageReceipt.size_bytes > 0,
    imageReceipt ?? null,
    "captured non-empty raw metadata with SHA-256"
  );
  if (pin.image.receipt_must_contain_digest) {
    check(
      "image_metadata_contains_digest",
      imageReceipt?.contains_digest === true,
      imageReceipt?.contains_digest ?? null,
      true
    );
  }

  return {
    status: checks.every((item) => item.status === "PASS") ? "PASS" : "FAIL",
    checks,
    errors: checks
      .filter((item) => item.status === "FAIL")
      .map(
        (item) =>
          `${item.name}: expected ${JSON.stringify(item.expected)}, got ${JSON.stringify(item.actual)}`
      )
  };
}

/**
 * Canonical Hugging Face hub cache root (where models--* lives).
 * Prefer explicit HF_HUB_CACHE / HUGGINGFACE_HUB_CACHE, else $HF_HOME/hub.
 */
export function resolveHubCache(env) {
  if (env.HF_HUB_CACHE) return env.HF_HUB_CACHE;
  if (env.HUGGINGFACE_HUB_CACHE) return env.HUGGINGFACE_HUB_CACHE;
  if (env.HF_HOME) return path.join(env.HF_HOME, "hub");
  return path.join(env.HOME || "/root", ".cache/huggingface/hub");
}

/**
 * Candidate roots that may hold models--{org}--{name}/snapshots/{rev}.
 * Historical oneclick / vLLM misconfigs wrote under $HF_HOME (no hub/).
 * Order: explicit env → standard hub → legacy flat HF_HOME.
 */
export function listHubCacheRoots(env = process.env) {
  const roots = [];
  const push = (value) => {
    if (!value || typeof value !== "string") return;
    const normalized = path.resolve(value);
    if (!roots.includes(normalized)) roots.push(normalized);
  };
  push(env.HF_HUB_CACHE);
  push(env.HUGGINGFACE_HUB_CACHE);
  if (env.HF_HOME) {
    push(path.join(env.HF_HOME, "hub"));
    push(env.HF_HOME);
  }
  const home = env.HOME || "/root";
  push(path.join(home, ".cache/huggingface/hub"));
  push(path.join(home, ".cache/huggingface"));
  return roots;
}

export function modelRepoCacheName(modelId) {
  return `models--${String(modelId).replaceAll("/", "--")}`;
}

/**
 * Resolve the snapshot directory for a pinned model revision.
 * Returns the first candidate that exists and contains at least one of the
 * declared weight basenames (or any snapshot entry if names omitted).
 *
 * @param {{
 *   env?: NodeJS.ProcessEnv,
 *   modelId: string,
 *   revision: string,
 *   weightFiles?: string[],
 *   existsSync?: (p: string) => boolean,
 * }} input
 */
export function resolveModelSnapshotDir(input) {
  const env = input.env ?? process.env;
  const repo = modelRepoCacheName(input.modelId);
  const weightFiles = input.weightFiles ?? [];
  const exists = input.existsSync ?? existsSync;

  const candidates = listHubCacheRoots(env).map((root) =>
    path.join(root, repo, "snapshots", input.revision)
  );

  for (const snapshotDir of candidates) {
    if (!exists(snapshotDir)) continue;
    if (weightFiles.length === 0) return snapshotDir;
    const hasAny = weightFiles.some((file) =>
      exists(path.join(snapshotDir, file))
    );
    if (hasAny) return snapshotDir;
  }

  // Fall back to the canonical hub path for error messages / NOT_PRESENT.
  return path.join(
    resolveHubCache(env),
    repo,
    "snapshots",
    input.revision
  );
}

function parseMajorMinor(value) {
  const match = String(value ?? "").match(/^v?(\d+)\.(\d+)/);
  if (!match) return null;
  return { major: Number(match[1]), minor: Number(match[2]) };
}
