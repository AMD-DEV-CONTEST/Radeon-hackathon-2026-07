#!/usr/bin/env node
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import {
  access,
  copyFile,
  mkdir,
  readFile,
  stat,
  writeFile
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { promisify } from "node:util";

import { resolveC0bOutDir } from "./resolve-out-dir.mjs";
import { evaluatePinnedRuntime } from "./runtime-checks.mjs";

const execFileAsync = promisify(execFile);
const root = fileURLToPath(new URL("../../../", import.meta.url));
const outDir = resolveC0bOutDir(root);
const rawDir = path.join(outDir, "raw");
const outPath = path.join(rawDir, "runtime-pin-verification.json");

if (process.env.PRIVATEPLATE_I_CONFIRM_RADEON_RUN !== "yes") {
  throw new Error(
    "Runtime verification is an on-instance pre-start step and requires the owner's current-run confirmation."
  );
}

const profiles = JSON.parse(
  await readFile(path.join(root, "scripts/c0/stage-b/model-profiles.json"), "utf8")
);
const pin = JSON.parse(
  await readFile(path.join(root, "scripts/c0/stage-b/runtime-pin.json"), "utf8")
);
const environment = JSON.parse(
  await readFile(path.join(outDir, "environment.json"), "utf8")
);

let profileId = process.env.PRIVATEPLATE_MODEL_PROFILE;
if (profiles.aliases?.[profileId]) profileId = profiles.aliases[profileId];
const profile = profiles.profiles?.[profileId];
const candidatePin = pin.candidates?.[profileId];
if (!profile || !candidatePin) {
  throw new Error(`Unknown or unpinned model profile: ${profileId ?? "missing"}`);
}

await mkdir(rawDir, { recursive: true });

const imageDigest = process.env.PRIVATEPLATE_IMAGE_DIGEST ?? "";
const imageReceipt = await captureImageMetadataReceipt(
  process.env.PRIVATEPLATE_IMAGE_METADATA_RECEIPT,
  imageDigest
);
const pythonBin = process.env.PRIVATEPLATE_PYTHON || "python3";
const probeErrors = [];
let runtime = {};
try {
  runtime = await probeRuntime(pythonBin);
} catch (error) {
  runtime.probe_error = String(error?.message ?? error);
  probeErrors.push(`runtime_probe: ${runtime.probe_error}`);
}
runtime.rocm = await readRocmVersion();

let cliText = "";
try {
  const { stdout, stderr } = await execFileAsync(
    pythonBin,
    ["-m", "vllm.entrypoints.openai.api_server", "--help"],
    { timeout: 120_000, maxBuffer: 8 * 1024 * 1024 }
  );
  cliText = `${stdout}\n${stderr}`;
} catch (error) {
  probeErrors.push(`vllm_cli_probe: ${String(error?.message ?? error)}`);
}
const evaluation = evaluatePinnedRuntime({
  pin,
  profile,
  candidatePin,
  runtime,
  environment,
  imageDigest,
  imageReceipt,
  cliHelp: cliText
});
evaluation.errors.push(...probeErrors);
if (probeErrors.length > 0) evaluation.status = "FAIL";

const payload = {
  schema_version: "2.0",
  stage: "C0-B",
  phase: "PRESTART",
  collected_at_utc: new Date().toISOString(),
  profile_id: profileId,
  runtime_pin_path: "scripts/c0/stage-b/runtime-pin.json",
  runtime_pin: {
    python: pin.python,
    node: pin.node,
    vllm: pin.vllm,
    torch: pin.torch,
    transformers: pin.transformers,
    compressed_tensors: pin.compressed_tensors,
    rocm: pin.rocm,
    hardware: pin.hardware
  },
  runtime,
  image: {
    digest: imageDigest || null,
    metadata_receipt: imageReceipt
  },
  checks: evaluation.checks,
  status: evaluation.status,
  errors: evaluation.errors,
  claim_boundary:
    "PASS only proves that the live pre-start software, hardware, image metadata, and selected local profile match the pinned formal environment. It does not prove model quality."
};

await writeFile(outPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(
  JSON.stringify(
    {
      status: payload.status,
      phase: payload.phase,
      profile_id: profileId,
      wrote: outPath,
      errors: payload.errors
    },
    null,
    2
  )
);
if (payload.status !== "PASS") process.exitCode = 2;

async function probeRuntime(python) {
  const script = `
import importlib.metadata as metadata
import json
import sys

info = {
    "python": {
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "patch": sys.version_info.micro,
        "full": sys.version,
    }
}
try:
    import importlib.metadata as _md
    import vllm
    try:
      info["vllm"] = _md.version("vllm")
    except Exception:
      info["vllm"] = getattr(vllm, "__version__", "unknown")
except Exception as exc:
    info["vllm_error"] = str(exc)
try:
    import torch
    info["torch"] = torch.__version__
    info["hip"] = getattr(torch.version, "hip", None)
    info["cuda_available_flag"] = bool(torch.cuda.is_available())
    info["device_count"] = int(torch.cuda.device_count())
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        info["device0"] = torch.cuda.get_device_name(0)
        info["device0_total_memory_bytes"] = int(props.total_memory)
        info["device0_compute_units"] = int(props.multi_processor_count)
        info["device0_gfx"] = getattr(props, "gcnArchName", None)
except Exception as exc:
    info["torch_error"] = str(exc)
try:
    import transformers
    info["transformers"] = transformers.__version__
except Exception as exc:
    info["transformers_error"] = str(exc)
try:
    info["compressed_tensors"] = metadata.version("compressed-tensors")
except Exception as exc:
    info["compressed_tensors_error"] = str(exc)
print(json.dumps(info))
`;
  const { stdout } = await execFileAsync(python, ["-c", script], {
    timeout: 120_000,
    maxBuffer: 2 * 1024 * 1024
  });
  return JSON.parse(stdout);
}

async function readRocmVersion() {
  const candidates = [
    "/opt/rocm/.info/version",
    "/opt/rocm/.info/version-dev"
  ];
  for (const candidate of candidates) {
    try {
      const value = (await readFile(candidate, "utf8")).trim();
      const match = value.match(/\d+\.\d+\.\d+/);
      if (match) return match[0];
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  return null;
}

async function captureImageMetadataReceipt(source, digest) {
  if (!source) {
    return {
      status: "MISSING",
      path: null,
      sha256: null,
      size_bytes: null,
      contains_digest: false
    };
  }
  const sourcePath = path.resolve(source);
  await access(sourcePath);
  const bytes = await readFile(sourcePath);
  const extension = /^\.[a-z0-9]{1,8}$/i.test(path.extname(sourcePath))
    ? path.extname(sourcePath).toLowerCase()
    : ".txt";
  const destination = path.join(
    rawDir,
    `image-metadata-receipt${extension}`
  );
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  try {
    const existing = await readFile(destination);
    const existingSha = createHash("sha256").update(existing).digest("hex");
    if (existingSha !== sha256) {
      throw new Error("Refusing to replace an existing image metadata receipt.");
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    await copyFile(sourcePath, destination);
  }
  const fileStat = await stat(destination);
  return {
    status: "CAPTURED",
    path: path.relative(outDir, destination),
    sha256,
    size_bytes: fileStat.size,
    contains_digest: Boolean(digest) && bytes.toString("utf8").includes(digest),
    recorded_at_utc: new Date().toISOString()
  };
}
