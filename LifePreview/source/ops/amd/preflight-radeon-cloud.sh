#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-/persistent/douyin-amd/config/amd.env}"

fail() {
  printf 'AMD preflight failed: %s\n' "$1" >&2
  exit 1
}

[[ -f "$ENV_FILE" ]] || fail "environment file is missing: $ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required_vars=(
  AMD_ROOT AMD_RUNTIME_ROOT AMD_RELEASE_DIR
  AMD_PYTHON AMD_BIN AMD_PROVIDER_BIN AMD_ROCM_PYTHON
  AMD_COMFY_DIR AMD_WEB_DIR
  AMD_PERSISTENT_ROOT AMD_COMPETITION_WORKER_ID
  AMD_COMPETITION_STAGE_FACTORY
  SHIDU_GPU_BACKEND SHIDU_API_HOST SHIDU_API_PORT
  SHIDU_PROVIDER_MCP_PROFILE
  SHIDU_SEARCH_MCP_ENDPOINT SHIDU_READER_MCP_ENDPOINT
  SHIDU_H3_AUTHORITY_ROOT
  SHIDU_PROJECT_ID SHIDU_ACTOR_ID
  SHIDU_SERVICE_FACTORY SHIDU_ARTIFACT_GATEWAY_FACTORY
  CREATIVE_HUB_ARTIFACT_STORE_ROOT FACTORY_CONFIG_DIR
  CREATIVE_HUB_ALEMBIC_CONFIG CREATIVE_ORCHESTRATION_ALEMBIC_CONFIG
  CREATIVE_HUB_POSTGRES_USER_FILE CREATIVE_HUB_POSTGRES_PASSWORD_FILE
  CREATIVE_HUB_POSTGRES_DB_FILE
  CREATIVE_ORCHESTRATION_POSTGRES_USER_FILE
  CREATIVE_ORCHESTRATION_POSTGRES_PASSWORD_FILE
  CREATIVE_ORCHESTRATION_POSTGRES_DB_FILE
  CREATIVE_HUB_MIGRATION_POSTGRES_USER_FILE
  CREATIVE_HUB_MIGRATION_POSTGRES_PASSWORD_FILE
  CREATIVE_HUB_MIGRATION_POSTGRES_DB_FILE
  CREATIVE_HUB_CREDENTIAL_MASTER_KEY_FILE SHIDU_SIGNING_SECRET_FILE
  SHIDU_PREVIOUS_SIGNING_SECRETS_FILE
  SHIDU_ZHIPU_API_KEY_FILE
)
for name in "${required_vars[@]}"; do
  [[ -n "${!name:-}" ]] || fail "$name is required"
done

if [[ "$SHIDU_PROVIDER_MCP_PROFILE" == "legacy-keyed-v1" ]]; then
  for name in \
    SHIDU_ZHIPU_CODING_PLAN_API_KEY_FILE \
    SHIDU_GOOGLE_BOOKS_API_KEY_FILE; do
    [[ -n "${!name:-}" ]] || fail "$name is required for legacy-keyed-v1"
  done
elif [[ "$SHIDU_PROVIDER_MCP_PROFILE" != "public-keyless-v1" ]]; then
  fail "SHIDU_PROVIDER_MCP_PROFILE must be public-keyless-v1 or legacy-keyed-v1"
fi

[[ "$AMD_ROOT" == /persistent/* ]] || \
  fail "AMD_ROOT must use the persistent PVC"
[[ "$AMD_RUNTIME_ROOT" == /workspace/* ]] || \
  fail "AMD_RUNTIME_ROOT must use disposable workspace cache"
[[ "$AMD_RUNTIME_ROOT" != "$AMD_ROOT" ]] || \
  fail "persistent and disposable runtime roots must be separate"
[[ "$SHIDU_H3_AUTHORITY_ROOT" == "$AMD_ROOT"/authorities/* ]] || \
  fail "SHIDU_H3_AUTHORITY_ROOT must use the persistent authority root"
[[ "$SHIDU_GPU_BACKEND" == "rocm" ]] || fail "SHIDU_GPU_BACKEND must be rocm"
[[ "$SHIDU_API_HOST" == "127.0.0.1" ]] || fail "Shidu API must bind loopback"
[[ -x "$AMD_PYTHON" ]] || fail "Python runtime is unavailable"
[[ -x "$AMD_PROVIDER_BIN/python" ]] || fail "Provider Python runtime is unavailable"
[[ -x "$AMD_ROCM_PYTHON" ]] || fail "ROCm Python runtime is unavailable"
[[ -x "$AMD_PROVIDER_BIN/shidu-provider-mcp" ]] || \
  fail "Provider MCP console script is unavailable"
for executable in shidu-api shidu-amd-vertical-slice-worker creative-hub-shidu-research-worker creative-hub-dag-worker; do
  [[ -x "$AMD_BIN/$executable" ]] || fail "$executable console script is unavailable"
done
[[ -d "$AMD_RELEASE_DIR" ]] || fail "release directory is unavailable"
[[ -f "$AMD_RELEASE_DIR/deploy/amd/release-manifest.json" ]] || \
  fail "release-manifest.json is missing"
[[ -f "$AMD_COMFY_DIR/main.py" ]] || fail "ComfyUI main.py is missing"
[[ -f "$FACTORY_CONFIG_DIR/models.yaml" ]] || fail "models.yaml is missing"
[[ -f "$FACTORY_CONFIG_DIR/pipeline.yaml" ]] || fail "baseline pipeline.yaml is missing"
[[ -f "${FACTORY_COMFY_CONFIG_FILE:-}" ]] || fail "AMD Comfy config is missing"
[[ -f "${FACTORY_PIPELINE_OVERRIDE_FILE:-}" ]] || fail "AMD pipeline override is missing"
[[ -f "$CREATIVE_HUB_ALEMBIC_CONFIG" ]] || fail "hub Alembic config is missing"
[[ -f "$CREATIVE_ORCHESTRATION_ALEMBIC_CONFIG" ]] || \
  fail "orchestration Alembic config is missing"

for command in ffmpeg ffprobe git pg_isready supervisord supervisorctl curl; do
  command -v "$command" >/dev/null 2>&1 || fail "$command is unavailable"
done

"$AMD_PYTHON" - "$AMD_RELEASE_DIR/deploy/amd/release-manifest.json" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert manifest["git"]["amdBranch"] == "codex/amd-rocm-port"
assert manifest["runtime"]["pythonPolicy"] == ">=3.12,<3.13"
assert manifest["runtime"]["deploymentMode"] == "native-process"
assert manifest["accelerator"] == {
    "vendor": "amd", "computeBackend": "rocm", "frameworkDevice": "cuda:0"
}
assert manifest["resources"]["gpuCount"] == 1
assert manifest["resources"]["comfyUiCount"] == 1
assert manifest["resources"]["workers"] == {"vertical-slice-worker": 1}
PY

"$AMD_PYTHON" - <<'PY'
import sys
if sys.version_info[:2] != (3, 12):
    raise SystemExit("Python 3.12 is required")
PY

"$AMD_PROVIDER_BIN/python" - <<'PY'
import sys
if sys.version_info[:2] != (3, 12):
    raise SystemExit("Provider Python 3.12 is required")
PY

"$AMD_ROCM_PYTHON" - <<'PY'
import torch
if not torch.version.hip or not torch.cuda.is_available() or torch.cuda.device_count() != 1:
    raise SystemExit("one ROCm GPU is required")
name = torch.cuda.get_device_name(0)
props = torch.cuda.get_device_properties(0)
print(f"ROCm GPU ready: {name}; {props.total_memory // (1024 ** 2)} MiB")
PY

if grep -Eq '(^|=)replace-with-' "$ENV_FILE"; then
  fail "replace-with-* capability or identity placeholders remain"
fi

while IFS='=' read -r name value; do
  [[ "$name" == *_FILE ]] || continue
  if [[ "$SHIDU_PROVIDER_MCP_PROFILE" == "public-keyless-v1" ]] &&
    [[ "$name" == "SHIDU_ZHIPU_CODING_PLAN_API_KEY_FILE" ||
       "$name" == "SHIDU_GOOGLE_BOOKS_API_KEY_FILE" ]]; then
    continue
  fi
  [[ -n "$value" && -f "$value" && ! -L "$value" ]] || \
    fail "$name must reference a regular, non-symlink file"
  [[ "$(stat -c '%a' "$value")" =~ ^(400|440|600|640)$ ]] || \
    fail "$name permissions must be 0400, 0440, 0600, or 0640"
done < <(env)

pg_isready -h "${CREATIVE_HUB_POSTGRES_HOST:-127.0.0.1}" >/dev/null || \
  fail "PostgreSQL is not ready"

[[ "${AMD_MANAGE_COMFYUI:-0}" == "0" ]] || \
  fail "competition startup must keep ComfyUI stopped until the user click"
[[ "$AMD_PERSISTENT_ROOT" == "$AMD_ROOT" ]] || \
  fail "competition persistent root must equal AMD_ROOT"
[[ "$AMD_COMPETITION_STAGE_FACTORY" == \
  "shidu_api.competition_stage_bundle:create_production_stage_functions" ]] || \
  fail "competition stage factory is not frozen"
if "$AMD_PYTHON" - <<'PY'
import socket
with socket.socket() as value:
    value.settimeout(0.2)
    raise SystemExit(0 if value.connect_ex(("127.0.0.1", 18188)) == 0 else 1)
PY
then
  fail "ComfyUI must be stopped before the user click"
fi

printf 'AMD native-process preflight passed.\n'
