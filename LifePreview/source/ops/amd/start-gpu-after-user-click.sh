#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-/persistent/douyin-amd/config/amd.env}"
CLICK_AUTHORITY="${2:-}"
SUPERVISOR_CONFIG="${3:-/persistent/douyin-amd/releases/current/deploy/amd/supervisord.conf}"

fail() {
  printf 'AMD click-to-GPU start: %s\n' "$1" >&2
  exit 2
}

[[ -n "$CLICK_AUTHORITY" ]] || fail "persisted click authority is required"
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "amd.env is missing or unsafe"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
: "${AMD_ROOT:?AMD_ROOT must be configured}"
[[ "$AMD_ROOT" == /persistent/* && -d "$AMD_ROOT" ]] || {
  fail "AMD_ROOT must be an existing /persistent directory"
}
[[ -f "$SUPERVISOR_CONFIG" && ! -L "$SUPERVISOR_CONFIG" ]] || {
  fail "Supervisor configuration is missing or unsafe"
}

PYTHON_BIN="${AMD_PYTHON:-python3}"
mapfile -t authority_values < <(
  "$PYTHON_BIN" - "$CLICK_AUTHORITY" "$AMD_ROOT" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import sys

authority_input = Path(sys.argv[1])
if authority_input.is_symlink():
    raise SystemExit("click authority symlinks are forbidden")
authority_path = authority_input.resolve(strict=True)
root = Path(sys.argv[2]).resolve(strict=True)
if root not in authority_path.parents:
    raise SystemExit("click authority must be a regular persistent file")
authority = json.loads(authority_path.read_text(encoding="utf-8"))
required = {
    "schemaVersion", "userClick", "action", "promptId", "submissionNonce",
    "workflowPath", "workflowSha256", "assetsManifestPath",
    "assetsManifestSha256", "statePath", "stateSha256",
}
if set(authority) != required:
    raise SystemExit("click authority schema is invalid")
if authority["schemaVersion"] != "amd.user-gpu-click.v1":
    raise SystemExit("click authority revision is invalid")
if authority["userClick"] is not True or authority["action"] != "start_generation":
    raise SystemExit("user click was not explicitly authorized")
if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", authority["promptId"]) is None:
    raise SystemExit("promptId is invalid")
if re.fullmatch(r"[0-9a-f]{32,128}", authority["submissionNonce"]) is None:
    raise SystemExit("submissionNonce is invalid")
for field in ("workflowSha256", "assetsManifestSha256", "stateSha256"):
    if re.fullmatch(r"[0-9a-f]{64}", authority[field]) is None:
        raise SystemExit(f"{field} is invalid")

def persistent_file(field):
    candidate = Path(authority[field])
    if candidate.is_symlink():
        raise SystemExit(f"{field} symlinks are forbidden")
    value = candidate.resolve(strict=True)
    if root not in value.parents or not value.is_file():
        raise SystemExit(f"{field} is outside persistent authority")
    return value

workflow = persistent_file("workflowPath")
assets = persistent_file("assetsManifestPath")
state_path = persistent_file("statePath")

def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()

if digest(workflow) != authority["workflowSha256"]:
    raise SystemExit("workflow SHA does not match persistent authority")
if digest(assets) != authority["assetsManifestSha256"]:
    raise SystemExit("asset manifest SHA does not match persistent authority")
if digest(state_path) != authority["stateSha256"]:
    raise SystemExit("state SHA does not match click authority")
state = json.loads(state_path.read_text(encoding="utf-8"))
expected = {
    "promptId": authority["promptId"],
    "submissionNonce": authority["submissionNonce"],
    "workflowSha256": authority["workflowSha256"],
    "assetsManifestSha256": authority["assetsManifestSha256"],
}
if any(state.get(key) != value for key, value in expected.items()):
    raise SystemExit("persisted submission state does not match click authority")
if state.get("status") not in {"prepared", "queued", "running", "succeeded"}:
    raise SystemExit("persisted submission state is not recoverable")
print(authority["promptId"])
print(authority["submissionNonce"])
print(authority["workflowSha256"])
print(authority["assetsManifestSha256"])
print(authority["stateSha256"])
print(authority_path)
print(state_path)
PY
) || fail "persisted user-click authority validation failed"
[[ "${#authority_values[@]}" -eq 7 ]] || fail "click authority projection is incomplete"
PROMPT_ID="${authority_values[0]}"
SUBMISSION_NONCE="${authority_values[1]}"
WORKFLOW_SHA256="${authority_values[2]}"
ASSETS_MANIFEST_SHA256="${authority_values[3]}"
STATE_SHA256="${authority_values[4]}"
CLICK_AUTHORITY="${authority_values[5]}"
STATE_PATH="${authority_values[6]}"

evidence_root="$AMD_ROOT/release-evidence/gpu-click-gate"
install -d -m 0700 -- "$evidence_root"
exec 9>"$evidence_root/start.lock"
flock -n 9 || fail "another click-to-GPU transition is active"

gate_json="$evidence_root/$SUBMISSION_NONCE.go-no-go.json"
"$SCRIPT_DIR/gpu-go-no-go.sh" "$ENV_FILE" "$gate_json"

ctl=(supervisorctl -c "$SUPERVISOR_CONFIG")
api_status="$("${ctl[@]}" status shidu-api 2>&1 || true)"
[[ "$api_status" == *"RUNNING"* ]] || fail "shidu-api is not RUNNING"
curl --fail --silent --show-error --max-time 5 \
  "http://127.0.0.1:${SHIDU_API_PORT:-18082}/health/ready" >/dev/null || {
  fail "shidu-api readiness failed"
}

comfy_status="$("${ctl[@]}" status comfyui 2>&1 || true)"
worker_status="$("${ctl[@]}" status video-local 2>&1 || true)"
[[ "$comfy_status" != *"RUNNING"* && "$worker_status" != *"RUNNING"* ]] || {
  fail "ComfyUI or GPU worker is already running"
}

started_comfy=0
started_worker=0
transition_complete=0
cleanup() {
  if [[ "$transition_complete" -ne 1 && "$started_comfy" -eq 1 && "$started_worker" -eq 0 ]]; then
    "${ctl[@]}" stop comfyui >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

"${ctl[@]}" start comfyui
started_comfy=1
comfy_ready=0
for _attempt in $(seq 1 60); do
  if curl --fail --silent --show-error --max-time 2 \
      http://127.0.0.1:18188/system_stats >/dev/null 2>&1; then
    comfy_ready=1
    break
  fi
  sleep 1
done
[[ "$comfy_ready" -eq 1 ]] || fail "ComfyUI did not become ready"

history_payload="$(curl --fail --silent --show-error --max-time 5 \
  "http://127.0.0.1:18188/history/$PROMPT_ID")"
queue_payload="$(curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:18188/queue)"
recovery="$({
  AMD_HISTORY="$history_payload" AMD_QUEUE="$queue_payload" \
    "$PYTHON_BIN" - "$PROMPT_ID" <<'PY'
import json
import os
import sys

prompt_id = sys.argv[1]
history = json.loads(os.environ["AMD_HISTORY"])
queue = json.loads(os.environ["AMD_QUEUE"])
if isinstance(history, dict) and prompt_id in history:
    print("history_recovered")
    raise SystemExit
for key in ("queue_running", "queue_pending"):
    values = queue.get(key, []) if isinstance(queue, dict) else []
    for item in values:
        if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
            print("queue_recovered")
            raise SystemExit
print("absent")
PY
} || true)"
case "$recovery" in
  history_recovered)
    "${ctl[@]}" stop comfyui >/dev/null
    started_comfy=0
    action="history_recovered"
    ;;
  queue_recovered)
    action="queue_recovered"
    ;;
  absent)
    "${ctl[@]}" start video-local
    started_worker=1
    worker_status="$("${ctl[@]}" status video-local 2>&1 || true)"
    [[ "$worker_status" == *"RUNNING"* ]] || fail "video-local did not enter RUNNING"
    action="worker_started"
    ;;
  *) fail "Comfy history/queue response is invalid" ;;
esac

receipt="$evidence_root/$SUBMISSION_NONCE.start.json"
tmp_json="$(mktemp "$evidence_root/.gpu-click-start.XXXXXX")"
AMD_START_ACTION="$action" \
AMD_PROMPT_ID="$PROMPT_ID" \
AMD_SUBMISSION_NONCE="$SUBMISSION_NONCE" \
AMD_WORKFLOW_SHA="$WORKFLOW_SHA256" \
AMD_ASSETS_SHA="$ASSETS_MANIFEST_SHA256" \
AMD_STATE_SHA="$STATE_SHA256" \
AMD_CLICK_AUTHORITY="$CLICK_AUTHORITY" \
AMD_STATE_PATH="$STATE_PATH" \
AMD_GATE_JSON="$gate_json" \
"$PYTHON_BIN" - "$tmp_json" <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

payload = {
    "schemaVersion": "amd.gpu-click-start.v1",
    "action": os.environ["AMD_START_ACTION"],
    "recordedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "promptId": os.environ["AMD_PROMPT_ID"],
    "submissionNonce": os.environ["AMD_SUBMISSION_NONCE"],
    "workflowSha256": os.environ["AMD_WORKFLOW_SHA"],
    "assetsManifestSha256": os.environ["AMD_ASSETS_SHA"],
    "stateSha256": os.environ["AMD_STATE_SHA"],
    "clickAuthorityPath": os.environ["AMD_CLICK_AUTHORITY"],
    "statePath": os.environ["AMD_STATE_PATH"],
    "goNoGoEvidencePath": os.environ["AMD_GATE_JSON"],
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
chmod 0600 -- "$tmp_json"
mv -- "$tmp_json" "$receipt"
transition_complete=1
trap - EXIT
printf 'AMD user-click GPU transition: %s; evidence: %s\n' "$action" "$receipt"
