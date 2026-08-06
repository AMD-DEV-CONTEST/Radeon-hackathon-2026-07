#!/usr/bin/env bash
# Start local vLLM for an explicit model profile. Run only on the GPU instance.
# No default Qwen2.5-7B. No auto-fallback. No reuse of unknown vLLM servers.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PROFILES_FILE="${ROOT}/scripts/c0/stage-b/model-profiles.json"

if [[ -z "${PRIVATEPLATE_MODEL_PROFILE:-}" ]]; then
  echo "PRIVATEPLATE_MODEL_PROFILE is required (primary: gemma4-12b-qat-w4a16-ct or alias gemma4; secondary: qwen14)." >&2
  exit 1
fi

if [[ -z "${PRIVATEPLATE_RUN_ID:-}" ]]; then
  echo "PRIVATEPLATE_RUN_ID is required so each formal run has its own evidence directory." >&2
  exit 1
fi

for forbidden_override in \
  PRIVATEPLATE_MODEL_ID \
  PRIVATEPLATE_MODEL_REVISION \
  PRIVATEPLATE_CHAT_TEMPLATE_VARIANT \
  PRIVATEPLATE_ALLOW_MODEL_ID_OVERRIDE \
  PRIVATEPLATE_TENSOR_PARALLEL_SIZE; do
  if [[ -n "${!forbidden_override:-}" ]]; then
    echo "Formal C0-B refuses ${forbidden_override}; use the pinned model profile unchanged." >&2
    exit 1
  fi
done

# Fail closed on local artifact integrity before spending GPU time.
node "${ROOT}/scripts/c0/stage-b/validate-model-profile.mjs" >/dev/null

OUT_DIR="${ROOT}/benchmarks/c0/stage-b/${PRIVATEPLATE_RUN_ID}"
RAW_DIR="${OUT_DIR}/raw"
mkdir -p "${RAW_DIR}"

if [[ -f /opt/venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source /opt/venv/bin/activate
fi
export PATH="/opt/venv/bin:${PATH}"
PYTHON_BIN="${PRIVATEPLATE_PYTHON:-$(command -v python3)}"

PORT="${PRIVATEPLATE_VLLM_PORT:-8000}"
HOST="${PRIVATEPLATE_VLLM_HOST:-127.0.0.1}"
TP_SIZE=1

if [[ "${HOST}" != "127.0.0.1" ]]; then
  echo "C0-B vLLM must bind to 127.0.0.1; found PRIVATEPLATE_VLLM_HOST=${HOST}." >&2
  exit 1
fi

# Resolve alias (gemma4 -> gemma4-12b-qat-w4a16-ct) and load profile fields.
RESOLVED="$(
  node -e '
    const fs = require("node:fs");
    const crypto = require("node:crypto");
    const path = require("node:path");
    const root = process.argv[1];
    const profiles = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
    let id = process.argv[3];
    if (profiles.aliases?.[id]) id = profiles.aliases[id];
    const profile = profiles.profiles?.[id];
    if (!profile) {
      console.error("Unknown PRIVATEPLATE_MODEL_PROFILE:", process.argv[3]);
      process.exit(2);
    }
    const templateRel = profile.chat_template?.path || null;
    const templateSha = profile.chat_template?.sha256 || null;
    if (templateRel) {
      const abs = path.join(root, templateRel);
      const dig = crypto.createHash("sha256").update(fs.readFileSync(abs)).digest("hex");
      if (templateSha && dig !== templateSha) {
        console.error("Chat template sha256 mismatch for", templateRel);
        console.error("expected", templateSha);
        console.error("got", dig);
        process.exit(3);
      }
    }
    const out = {
      profile_id: id,
      role: profile.role || null,
      model_id: profile.model_id,
      revision: profile.revision || null,
      revision_pinned: Boolean(profile.revision_pinned),
      tool_call_parser: profile.tool_call_parser,
      reasoning_parser: profile.reasoning_parser || null,
      attention_backend: profile.attention_backend || "TRITON_ATTN",
      max_model_len: profile.max_model_len || 16384,
      kv_cache_memory_bytes: profile.kv_cache_memory_bytes,
      quantization_arg: profile.quantization?.vllm_quantization_arg || null,
      chat_template_rel: templateRel,
      chat_template_sha256: templateSha,
      enable_auto_tool_choice: profile.enable_auto_tool_choice !== false,
      weight_lfs_sha256: profile.weights?.files?.[0]?.lfs_sha256 || null,
      license: profile.license,
      license_link: profile.license_link
    };
    // Guardrails
    if (id.startsWith("gemma4") || id === "gemma4-12b-qat-w4a16-ct") {
      if (out.tool_call_parser !== "gemma4") process.exit(4);
      if (out.reasoning_parser !== "gemma4") process.exit(5);
      if (out.quantization_arg !== "compressed-tensors") process.exit(6);
      if (!out.revision) process.exit(7);
      if (!out.chat_template_rel) process.exit(8);
      if (out.model_id !== "google/gemma-4-12B-it-qat-w4a16-ct") process.exit(9);
    }
    if (id === "qwen14" && out.tool_call_parser !== "hermes") process.exit(10);
    process.stdout.write(JSON.stringify(out));
  ' "${ROOT}" "${PROFILES_FILE}" "${PRIVATEPLATE_MODEL_PROFILE}"
)"

PROFILE_ID="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).profile_id)' "${RESOLVED}")"
MODEL_ID="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).model_id)' "${RESOLVED}")"
REVISION="$(node -e 'const j=JSON.parse(process.argv[1]); process.stdout.write(j.revision||"")' "${RESOLVED}")"
PARSER="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).tool_call_parser)' "${RESOLVED}")"
REASONING_PARSER="$(node -e 'const j=JSON.parse(process.argv[1]); process.stdout.write(j.reasoning_parser||"")' "${RESOLVED}")"
ATTN="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).attention_backend)' "${RESOLVED}")"
MAX_LEN="$(node -e 'process.stdout.write(String(JSON.parse(process.argv[1]).max_model_len))' "${RESOLVED}")"
KV_CACHE_BYTES="$(node -e 'process.stdout.write(String(JSON.parse(process.argv[1]).kv_cache_memory_bytes))' "${RESOLVED}")"
QUANT_ARG="$(node -e 'const j=JSON.parse(process.argv[1]); process.stdout.write(j.quantization_arg||"")' "${RESOLVED}")"
CHAT_TEMPLATE_REL="$(node -e 'const j=JSON.parse(process.argv[1]); process.stdout.write(j.chat_template_rel||"")' "${RESOLVED}")"
CHAT_TEMPLATE_SHA="$(node -e 'const j=JSON.parse(process.argv[1]); process.stdout.write(j.chat_template_sha256||"")' "${RESOLVED}")"

RUNTIME_VERIFICATION="${RAW_DIR}/runtime-pin-verification.json"
node -e '
  const value = JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8"));
  if (value.status !== "PASS" || value.phase !== "PRESTART") {
    console.error("Pinned runtime pre-start verification did not pass.");
    process.exit(2);
  }
  if (value.profile_id !== process.argv[2]) {
    console.error("Runtime verification profile mismatch.");
    process.exit(3);
  }
  if (value.image?.digest !== process.env.PRIVATEPLATE_IMAGE_DIGEST) {
    console.error("Runtime verification image digest mismatch.");
    process.exit(4);
  }
' "${RUNTIME_VERIFICATION}" "${PROFILE_ID}"

LOG_FILE="${RAW_DIR}/vllm-server.log"
PID_FILE="${RAW_DIR}/vllm-server.pid"
MODELS_FILE="${RAW_DIR}/vllm-models.json"
BIND_FILE="${RAW_DIR}/vllm-bind.txt"
LAUNCH_FILE="${RAW_DIR}/vllm-launch.json"
FINGERPRINT_FILE="${RAW_DIR}/vllm-launch-fingerprint.txt"

printf 'host=%s\nport=%s\n' "${HOST}" "${PORT}" >"${BIND_FILE}"

read_versions() {
  "${PYTHON_BIN}" - <<'PY'
import json, sys
info = {}
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
except Exception as exc:
  info["torch_error"] = str(exc)
try:
  import transformers
  info["transformers"] = transformers.__version__
except Exception as exc:
  info["transformers_error"] = str(exc)
try:
  import importlib.metadata as metadata
  info["compressed_tensors"] = metadata.version("compressed-tensors")
except Exception as exc:
  info["compressed_tensors_error"] = str(exc)
info["python"] = sys.version
print(json.dumps(info, ensure_ascii=False))
PY
}

LAUNCH_CMDLINE=(
  "${PYTHON_BIN}" -m vllm.entrypoints.openai.api_server
  --model "${MODEL_ID}"
  --host "${HOST}"
  --port "${PORT}"
  --tensor-parallel-size "${TP_SIZE}"
  --max-model-len "${MAX_LEN}"
  --kv-cache-memory-bytes "${KV_CACHE_BYTES}"
  --attention-backend "${ATTN}"
  --enforce-eager
  --enable-auto-tool-choice
  --tool-call-parser "${PARSER}"
)

if [[ -n "${REVISION}" ]]; then
  LAUNCH_CMDLINE+=(--revision "${REVISION}")
fi
if [[ -n "${REASONING_PARSER}" ]]; then
  LAUNCH_CMDLINE+=(--reasoning-parser "${REASONING_PARSER}")
fi
if [[ -n "${QUANT_ARG}" ]]; then
  LAUNCH_CMDLINE+=(--quantization "${QUANT_ARG}")
fi

CHAT_TEMPLATE_ABS=""
if [[ -n "${CHAT_TEMPLATE_REL}" ]]; then
  CHAT_TEMPLATE_ABS="${ROOT}/${CHAT_TEMPLATE_REL}"
  if [[ ! -f "${CHAT_TEMPLATE_ABS}" ]]; then
    echo "Chat template missing: ${CHAT_TEMPLATE_ABS}" >&2
    exit 1
  fi
  LAUNCH_CMDLINE+=(--chat-template "${CHAT_TEMPLATE_ABS}")
fi

EXPECTED_FINGERPRINT="$(
  printf '%s\0' "${LAUNCH_CMDLINE[@]}" | sha256sum | awk '{print $1}'
)"
printf '%s\n' "${EXPECTED_FINGERPRINT}" >"${FINGERPRINT_FILE}"

fetch_models() {
  local curl_args=(-fsS)
  if [[ -n "${PRIVATEPLATE_VLLM_API_KEY:-}" ]]; then
    curl_args+=(-H "Authorization: Bearer ${PRIVATEPLATE_VLLM_API_KEY}")
  fi
  curl "${curl_args[@]}" "http://${HOST}:${PORT}/v1/models" -o "${MODELS_FILE}"
}

record_active_model() {
  local active_model
  active_model="$(
    node -e '
      const payload = JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8"));
      const ids = Array.isArray(payload.data)
        ? payload.data.map((item) => item?.id).filter((id) => typeof id === "string" && id.length > 0)
        : [];
      if (ids.length === 0) process.exit(2);
      const requested = process.argv[2];
      // vLLM may report the repo id or a local path ending with it.
      const ok = ids.includes(requested);
      if (!ok) {
        console.error("Active vLLM model does not match requested model:", requested, ids);
        process.exit(3);
      }
      process.stdout.write(requested);
    ' "${MODELS_FILE}" "${MODEL_ID}"
  )"
  printf '%s\n' "${active_model}" >"${RAW_DIR}/active-model.txt"
  echo "Active model reported by vLLM: ${active_model}"
}

record_process_commandline() {
  node -e '
    const crypto = require("node:crypto");
    const fs = require("node:fs");
    const pid = fs.readFileSync(process.argv[1], "utf8").trim();
    const bytes = fs.readFileSync(`/proc/${pid}/cmdline`);
    const args = bytes
      .toString("utf8")
      .split("\0")
      .filter(Boolean);
    const sha256 = crypto.createHash("sha256").update(bytes).digest("hex");
    fs.writeFileSync(
      process.argv[2],
      JSON.stringify(
        {
          pid: Number(pid),
          args,
          sha256,
          collected_at_utc: new Date().toISOString()
        },
        null,
        2
      ) + "\n"
    );
  ' "${PID_FILE}" "${RAW_DIR}/vllm-process-cmdline.json"
}

if fetch_models >/dev/null 2>&1; then
  if [[ ! -f "${PID_FILE}" || ! -f "${LAUNCH_FILE}" ]]; then
    echo "Refusing to reuse vLLM on ${HOST}:${PORT}: missing launch provenance for this run." >&2
    exit 1
  fi
  existing_fp="$(node -e 'const j=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")); process.stdout.write(j.launch_fingerprint||"")' "${LAUNCH_FILE}")"
  if [[ "${existing_fp}" != "${EXPECTED_FINGERPRINT}" ]]; then
    echo "Refusing to reuse vLLM: launch fingerprint mismatch." >&2
    echo "expected=${EXPECTED_FINGERPRINT}" >&2
    echo "found=${existing_fp}" >&2
    exit 1
  fi
  echo "vLLM already running with matching launch fingerprint for this run."
  record_process_commandline
  fetch_models
  record_active_model
  exit 0
fi

# Global oneclick notebooks often cannot reach huggingface.co directly.
# Prefer an explicit env, then the platform pid-1 defaults, then the China-reachable mirror.
if [[ -z "${HF_ENDPOINT:-}" && -r /proc/1/environ ]]; then
  HF_ENDPOINT="$(tr '\0' '\n' </proc/1/environ | sed -n 's/^HF_ENDPOINT=//p' | head -n 1 || true)"
fi
if [[ -z "${HF_HOME:-}" && -r /proc/1/environ ]]; then
  HF_HOME="$(tr '\0' '\n' </proc/1/environ | sed -n 's/^HF_HOME=//p' | head -n 1 || true)"
fi
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HUGGINGFACE_HUB_ENDPOINT="${HUGGINGFACE_HUB_ENDPOINT:-$HF_ENDPOINT}"
export HF_HOME="${HF_HOME:-/root/.cache/huggingface}"
# Canonical hub cache is $HF_HOME/hub (models--* lives there). Never default to
# $HF_HOME flat layout — that split Gemma under hub/ and Qwen under HF_HOME.
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HUB_CACHE}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
export VLLM_ATTENTION_BACKEND="${ATTN}"
echo "HF_ENDPOINT=${HF_ENDPOINT}"
echo "HF_HOME=${HF_HOME}"
echo "HF_HUB_CACHE=${HF_HUB_CACHE}"
echo "HUGGINGFACE_HUB_CACHE=${HUGGINGFACE_HUB_CACHE}"

VERSIONS_JSON="$(read_versions)"

node -e '
  const fs = require("node:fs");
  const resolved = JSON.parse(process.argv[1]);
  const launch = {
    schema_version: "2.0",
    profile_id: resolved.profile_id,
    role: resolved.role,
    model_id: resolved.model_id,
    revision: resolved.revision,
    revision_pinned: resolved.revision_pinned,
    tool_call_parser: resolved.tool_call_parser,
    reasoning_parser: resolved.reasoning_parser,
    quantization: resolved.quantization_arg,
    attention_backend: resolved.attention_backend,
    host: process.argv[2],
    port: Number(process.argv[3]),
    max_model_len: resolved.max_model_len,
    kv_cache_memory_bytes: resolved.kv_cache_memory_bytes,
    chat_template_path: resolved.chat_template_rel,
    chat_template_sha256: resolved.chat_template_sha256,
    license: resolved.license,
    license_link: resolved.license_link,
    weight_lfs_sha256_declared: resolved.weight_lfs_sha256,
    launch_fingerprint: process.argv[4],
    cmdline: JSON.parse(process.argv[5]),
    runtime_versions: JSON.parse(process.argv[6]),
    started_at_utc: new Date().toISOString(),
    image_digest: process.env.PRIVATEPLATE_IMAGE_DIGEST || null,
    notes: "Formal run launch record. Fail closed on profile/parser/revision/template mismatch. No auto-fallback."
  };
  fs.writeFileSync(process.argv[7], JSON.stringify(launch, null, 2) + "\n");
' \
  "${RESOLVED}" \
  "${HOST}" \
  "${PORT}" \
  "${EXPECTED_FINGERPRINT}" \
  "$(node -e 'process.stdout.write(JSON.stringify(process.argv.slice(1)))' "${LAUNCH_CMDLINE[@]}")" \
  "${VERSIONS_JSON}" \
  "${LAUNCH_FILE}"

echo "Starting vLLM profile=${PROFILE_ID} model=${MODEL_ID} revision=${REVISION:-none} parser=${PARSER} quant=${QUANT_ARG:-none}"
nohup env \
  HF_ENDPOINT="${HF_ENDPOINT}" \
  HUGGINGFACE_HUB_ENDPOINT="${HUGGINGFACE_HUB_ENDPOINT}" \
  HF_HOME="${HF_HOME}" \
  HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE}" \
  HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET}" \
  VLLM_ATTENTION_BACKEND="${VLLM_ATTENTION_BACKEND}" \
  "${LAUNCH_CMDLINE[@]}" \
  >"${LOG_FILE}" 2>&1 &
echo $! >"${PID_FILE}"
echo "vLLM pid=$(cat "${PID_FILE}") log=${LOG_FILE}"

wait_ready() {
  local deadline=$((SECONDS + ${PRIVATEPLATE_VLLM_READY_TIMEOUT_SEC:-3600}))
  while (( SECONDS < deadline )); do
    if fetch_models >/dev/null 2>&1; then
      echo "vLLM ready"
      return 0
    fi
    if [[ -f "${PID_FILE}" ]] && ! kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
      echo "vLLM process exited early; see ${LOG_FILE}" >&2
      return 1
    fi
    sleep 5
  done
  echo "Timed out waiting for vLLM" >&2
  return 1
}

if ! wait_ready; then
  echo "Model profile ${PROFILE_ID} failed to become ready. No fallback will be attempted." >&2
  node -e '
    const fs = require("node:fs");
    fs.writeFileSync(process.argv[1], JSON.stringify({
      status: "FAIL",
      profile_id: process.argv[2],
      model_id: process.argv[3],
      revision: process.argv[4] || null,
      failed_at_utc: new Date().toISOString(),
      reason: "vllm_ready_timeout_or_exit",
      log: "raw/vllm-server.log",
      fallback_attempted: false
    }, null, 2) + "\n");
  ' "${RAW_DIR}/vllm-start-failure.json" "${PROFILE_ID}" "${MODEL_ID}" "${REVISION}"
  exit 1
fi

export PRIVATEPLATE_MODEL_ACTIVE="${MODEL_ID}"
record_process_commandline
fetch_models
record_active_model
