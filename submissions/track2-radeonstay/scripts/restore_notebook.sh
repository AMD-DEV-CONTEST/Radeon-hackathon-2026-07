#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

usage() {
  cat >&2 <<'USAGE'
Usage: restore_notebook.sh \
  --source-bundle FILE \
  --source-sha256 SHA256 \
  --bundle-ref REF \
  --expected-commit FULL_SHA \
  --llama-runtime FILE \
  --llama-runtime-sha256 SHA256 \
  --release-profile FILE \
  --release-profile-sha256 SHA256 \
  --runtime-proof FILE \
  --runtime-proof-sha256 SHA256 \
  --state-root ABSOLUTE_PVC_DIRECTORY \
  [--run-id FRESH_DEPLOYMENT_ID] [--app-port PORT] [--model-port PORT] \
  [--username NAME] [--no-tunnel]

Run this script from a Radeon Cloud Jupyter Terminal. An SSH login may not
inherit the platform's FRP_BROKER_URL variables even on a Tunnel-capable Pod.
USAGE
}

source_bundle=""
source_sha256=""
bundle_ref=""
expected_commit=""
llama_runtime=""
llama_runtime_sha256=""
release_profile=""
release_profile_sha256=""
runtime_proof=""
runtime_proof_sha256=""
state_root=""
run_id=""
app_port="7861"
model_port="8000"
ui_username="radeonstay"
expose_tunnel=1

while (( $# > 0 )); do
  case "$1" in
    --source-bundle) source_bundle="${2:-}"; shift 2 ;;
    --source-sha256) source_sha256="${2:-}"; shift 2 ;;
    --bundle-ref) bundle_ref="${2:-}"; shift 2 ;;
    --expected-commit) expected_commit="${2:-}"; shift 2 ;;
    --llama-runtime) llama_runtime="${2:-}"; shift 2 ;;
    --llama-runtime-sha256) llama_runtime_sha256="${2:-}"; shift 2 ;;
    --release-profile) release_profile="${2:-}"; shift 2 ;;
    --release-profile-sha256) release_profile_sha256="${2:-}"; shift 2 ;;
    --runtime-proof) runtime_proof="${2:-}"; shift 2 ;;
    --runtime-proof-sha256) runtime_proof_sha256="${2:-}"; shift 2 ;;
    --state-root) state_root="${2:-}"; shift 2 ;;
    --run-id) run_id="${2:-}"; shift 2 ;;
    --app-port) app_port="${2:-}"; shift 2 ;;
    --model-port) model_port="${2:-}"; shift 2 ;;
    --username) ui_username="${2:-}"; shift 2 ;;
    --no-tunnel) expose_tunnel=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

for required_value in \
  "$source_bundle" \
  "$source_sha256" \
  "$bundle_ref" \
  "$expected_commit" \
  "$llama_runtime" \
  "$llama_runtime_sha256" \
  "$release_profile" \
  "$release_profile_sha256" \
  "$runtime_proof" \
  "$runtime_proof_sha256" \
  "$state_root"; do
  if [[ -z "$required_value" ]]; then
    usage
    exit 2
  fi
done

if [[ ! "$source_sha256" =~ ^[0-9a-f]{64}$ \
      || ! "$llama_runtime_sha256" =~ ^[0-9a-f]{64}$ \
      || ! "$release_profile_sha256" =~ ^[0-9a-f]{64}$ \
      || ! "$runtime_proof_sha256" =~ ^[0-9a-f]{64}$ \
      || ! "$expected_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Source, runtime, profile, and commit identities must be lowercase full hashes" >&2
  exit 2
fi
if [[ ! "$bundle_ref" =~ ^refs/[A-Za-z0-9._/-]+$ ]]; then
  echo "Bundle ref has an invalid format" >&2
  exit 2
fi
if [[ -n "$run_id" \
      && ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$ ]]; then
  echo "Run ID has an invalid format" >&2
  exit 2
fi
if [[ ! "$ui_username" =~ ^[A-Za-z0-9._-]{4,64}$ ]]; then
  echo "Username must contain 4-64 safe characters" >&2
  exit 2
fi
for port in "$app_port" "$model_port"; do
  if [[ ! "$port" =~ ^[1-9][0-9]{0,4}$ ]] || (( port > 65535 )); then
    echo "Ports must be integers between 1 and 65535" >&2
    exit 2
  fi
done
if [[ "$app_port" == "$model_port" ]]; then
  echo "Application and model ports must be different" >&2
  exit 2
fi
if [[ "$state_root" != /* || "$state_root" == "/" ]]; then
  echo "--state-root must be a dedicated absolute directory, not /" >&2
  exit 2
fi
if [[ "$state_root" == *$'\n'* || "$state_root" == *$'\r'* ]]; then
  echo "State root must not contain newline characters" >&2
  exit 2
fi
for input_file in \
  "$source_bundle" "$llama_runtime" "$release_profile" "$runtime_proof"; do
  if [[ ! -f "$input_file" || -L "$input_file" ]]; then
    echo "Recovery input must be a regular non-symlink file: $input_file" >&2
    exit 2
  fi
done

for required_command in \
  git curl sha256sum tar python3 ss nohup install stat id rocminfo rocm-smi; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "Required command is unavailable: $required_command" >&2
    exit 4
  fi
done
if [[ "$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.12" ]]; then
  echo "The recorded release requires Python 3.12" >&2
  exit 4
fi

if (( expose_tunnel == 1 )); then
  if [[ ! -x /var/run/secrets/frp-self-service/install ]]; then
    echo "Radeon Cloud Tunnel installer is unavailable; recreate the Notebook" >&2
    exit 4
  fi
  if [[ -z "${FRP_BROKER_URL:-}" || -z "${FRP_BROKER_TLS_SERVER_NAME:-}" ]]; then
    echo "Tunnel variables are absent. Run from the Jupyter Terminal, not SSH." >&2
    exit 4
  fi
fi

verify_sha256() {
  local expected="$1"
  local file="$2"
  printf '%s  %s\n' "$expected" "$file" | sha256sum --check --strict
}

verify_sha256 "$source_sha256" "$source_bundle"
verify_sha256 "$llama_runtime_sha256" "$llama_runtime"
verify_sha256 "$release_profile_sha256" "$release_profile"
verify_sha256 "$runtime_proof_sha256" "$runtime_proof"
git bundle verify "$source_bundle" >/dev/null

mapfile -t release_values < <(python3 - "$release_profile" <<'PY_PROFILE'
import hashlib
import json
import math
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
value = json.loads(path.read_text(encoding="utf-8"))
required = {
    "schema_version",
    "created_at_utc",
    "reference_label",
    "winner_label",
    "winner_report_sha256",
    "candidate_source_index_sha256",
    "quality_qualified_candidate_count",
    "quality_negative_label",
    "quality_negative_manifest_sha256",
    "stability_report_sha256",
    "stability_run_count",
    "stability_run_ids_sha256",
    "soak_report_sha256",
    "soak_run_id",
    "soak_duration_seconds",
    "final_evidence_accepted",
    "c2_commit",
    "request_configuration",
    "request_configuration_sha256",
    "service_configuration",
    "service_configuration_sha256",
    "hardware",
    "model",
    "llama_cpp",
}
if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 4:
    raise SystemExit("Release profile does not match schema v4")
if value["reference_label"] not in {"A", "B"}:
    raise SystemExit("Release profile reference must be A or B")
if value["winner_label"] not in tuple("BCDEFGH") or not (
    value["winner_label"] > value["reference_label"]
):
    raise SystemExit("Release profile winner must be B-H")
if not re.fullmatch(r"[0-9a-f]{40}", str(value["c2_commit"])):
    raise SystemExit("Release profile C2 commit must be a full SHA-1")
if not re.fullmatch(r"[0-9a-f]{64}", str(value["winner_report_sha256"])):
    raise SystemExit("Release profile winner report SHA256 is invalid")
for field in (
    "candidate_source_index_sha256", "stability_report_sha256",
    "stability_run_ids_sha256", "soak_report_sha256",
):
    if not re.fullmatch(r"[0-9a-f]{64}", str(value[field])):
        raise SystemExit(f"Release final-evidence SHA256 is invalid: {field}")
expected_candidate_count = 8 if value["reference_label"] == "A" else 7
expected_negative_label = "none" if value["reference_label"] == "A" else "A"
if (
    type(value["quality_qualified_candidate_count"]) is not int
    or value["quality_qualified_candidate_count"] != expected_candidate_count
    or value["quality_negative_label"] != expected_negative_label
    or type(value["stability_run_count"]) is not int
    or value["stability_run_count"] != 5
    or value["final_evidence_accepted"] is not True
):
    raise SystemExit("Release final-evidence summary is inconsistent")
negative_sha = value["quality_negative_manifest_sha256"]
if value["reference_label"] == "A":
    if negative_sha is not None:
        raise SystemExit("A Reference must not declare quality-negative evidence")
elif not isinstance(negative_sha, str) or re.fullmatch(r"[0-9a-f]{64}", negative_sha) is None:
    raise SystemExit("B Reference requires a bound A quality-negative manifest")
if not isinstance(value["soak_run_id"], str) or re.fullmatch(
    r"[A-Za-z0-9][A-Za-z0-9._:-]{0,47}", value["soak_run_id"]
) is None:
    raise SystemExit("Release long-soak run ID is invalid")
if (
    not isinstance(value["soak_duration_seconds"], (int, float))
    or isinstance(value["soak_duration_seconds"], bool)
    or not math.isfinite(float(value["soak_duration_seconds"]))
    or float(value["soak_duration_seconds"]) < 1800.0
):
    raise SystemExit("Release long-soak duration is below the formal floor")

request = value["request_configuration"]
if not isinstance(request, dict) or set(request) != {
    "thinking_enabled", "schema_constrained", "fused_plan_evidence"
}:
    raise SystemExit("Release request configuration fields are invalid")
if not all(type(request[field]) is bool for field in request):
    raise SystemExit("Release request configuration values must be boolean")
if request["schema_constrained"] is not True:
    raise SystemExit("Release profile must keep schema-constrained generation")
declared_request_sha256 = value["request_configuration_sha256"]
if not isinstance(declared_request_sha256, str) or re.fullmatch(
    r"[0-9a-f]{64}", declared_request_sha256
) is None:
    raise SystemExit("Release request configuration SHA256 is invalid")
canonical_request = json.dumps(
    request,
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
).encode("ascii")
if hashlib.sha256(canonical_request).hexdigest() != declared_request_sha256:
    raise SystemExit("Release request configuration SHA256 does not match its values")

service = value["service_configuration"]
service_fields = {
    "experiment", "ctx", "parallel", "batch", "ubatch", "flash_attn",
    "gpu_layers", "cache_type_k", "cache_type_v", "log_verbosity",
}
if not isinstance(service, dict) or set(service) != service_fields:
    raise SystemExit("Release service configuration fields are invalid")
if service["experiment"] != value["winner_label"]:
    raise SystemExit("Release service experiment does not match the winner")
for field in ("ctx", "parallel", "batch", "ubatch", "gpu_layers", "log_verbosity"):
    if type(service[field]) is not int or service[field] <= 0:
        raise SystemExit(f"Release service field is invalid: {field}")
if service["flash_attn"] not in {"on", "off"}:
    raise SystemExit("Release flash attention must be on or off")
for field in ("cache_type_k", "cache_type_v"):
    if service[field] not in {"f16", "q8_0"}:
        raise SystemExit(f"Release cache type is unsupported: {field}")
if service["log_verbosity"] != 5:
    raise SystemExit("Release profile must retain log verbosity 5")
declared_service_sha256 = value["service_configuration_sha256"]
if not isinstance(declared_service_sha256, str) or re.fullmatch(
    r"[0-9a-f]{64}", declared_service_sha256
) is None:
    raise SystemExit("Release service configuration SHA256 is invalid")
effective_service = {key: item for key, item in service.items() if key != "experiment"}
canonical_service = json.dumps(
    effective_service,
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
).encode("ascii")
if hashlib.sha256(canonical_service).hexdigest() != declared_service_sha256:
    raise SystemExit("Release service configuration SHA256 does not match its values")

hardware = value["hardware"]
if not isinstance(hardware, dict) or set(hardware) != {
    "rocm_version", "gpu_name", "gpu_arch", "compute_units", "vram_bytes"
}:
    raise SystemExit("Release hardware fields are invalid")
if not re.fullmatch(r"[0-9][A-Za-z0-9._+-]{0,63}", str(hardware["rocm_version"])):
    raise SystemExit("Release ROCm version is invalid")
if (
    not isinstance(hardware["gpu_name"], str)
    or not 1 <= len(hardware["gpu_name"]) <= 160
):
    raise SystemExit("Release GPU evidence name is invalid")
if not re.fullmatch(r"gfx[0-9A-Za-z]+", str(hardware["gpu_arch"])):
    raise SystemExit("Release GPU architecture is invalid")
for field in ("compute_units", "vram_bytes"):
    if type(hardware[field]) is not int or hardware[field] <= 0:
        raise SystemExit(f"Release hardware field is invalid: {field}")

model = value["model"]
if not isinstance(model, dict) or set(model) != {
    "alias", "repository", "revision", "filename", "sha256", "quantization", "license"
}:
    raise SystemExit("Release model fields are invalid")
patterns = {
    "alias": r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
    "repository": r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+",
    "revision": r"[0-9a-f]{40,64}",
    "filename": r"[A-Za-z0-9][A-Za-z0-9._-]{0,239}",
    "sha256": r"[0-9a-f]{64}",
    "quantization": r"Q[0-9][A-Za-z0-9_-]{0,31}",
    "license": r"[A-Za-z0-9][A-Za-z0-9.+-]{0,63}",
}
for field, pattern in patterns.items():
    if not re.fullmatch(pattern, str(model[field])):
        raise SystemExit(f"Release model field is invalid: {field}")

llama = value["llama_cpp"]
if not isinstance(llama, dict) or set(llama) != {"commit", "server_sha256"}:
    raise SystemExit("Release llama.cpp fields are invalid")
if not re.fullmatch(r"[0-9a-f]{40,64}", str(llama["commit"])):
    raise SystemExit("Release llama.cpp commit is invalid")
if not re.fullmatch(r"[0-9a-f]{64}", str(llama["server_sha256"])):
    raise SystemExit("Release llama-server SHA256 is invalid")

rows = (
    value["winner_label"], value["c2_commit"], model["alias"],
    model["repository"], model["revision"], model["filename"], model["sha256"],
    model["quantization"], llama["commit"], llama["server_sha256"],
    "1" if request["thinking_enabled"] else "0",
    "1" if request["fused_plan_evidence"] else "0",
    declared_request_sha256,
    service["ctx"], service["parallel"], service["batch"], service["ubatch"],
    service["flash_attn"], service["gpu_layers"], service["cache_type_k"],
    service["cache_type_v"], service["log_verbosity"],
    declared_service_sha256,
    hardware["rocm_version"], hardware["gpu_name"], hardware["gpu_arch"],
    hardware["compute_units"], hardware["vram_bytes"],
    value["winner_report_sha256"],
    value["reference_label"],
    value["candidate_source_index_sha256"],
    value["quality_qualified_candidate_count"],
    value["quality_negative_label"],
    value["quality_negative_manifest_sha256"] or "none",
    value["stability_report_sha256"],
    value["stability_run_count"],
    value["stability_run_ids_sha256"],
    value["soak_report_sha256"],
    value["soak_run_id"],
    value["soak_duration_seconds"],
)
for row in rows:
    text = str(row)
    if "\n" in text or "\r" in text:
        raise SystemExit("Release profile contains a multiline scalar")
    print(text)
PY_PROFILE
)
if (( ${#release_values[@]} != 40 )); then
  echo "Release profile did not produce the expected frozen values" >&2
  exit 3
fi
winner_label="${release_values[0]}"
profile_c2_commit="${release_values[1]}"
model_alias="${release_values[2]}"
model_repository="${release_values[3]}"
model_revision="${release_values[4]}"
model_name="${release_values[5]}"
model_sha256="${release_values[6]}"
model_quantization="${release_values[7]}"
llama_cpp_commit="${release_values[8]}"
llama_server_sha256="${release_values[9]}"
thinking_enabled="${release_values[10]}"
fused_plan_evidence="${release_values[11]}"
request_configuration_sha256="${release_values[12]}"
context_size="${release_values[13]}"
parallel_slots="${release_values[14]}"
batch_size="${release_values[15]}"
ubatch_size="${release_values[16]}"
flash_attn="${release_values[17]}"
gpu_layers="${release_values[18]}"
cache_type_k="${release_values[19]}"
cache_type_v="${release_values[20]}"
log_verbosity="${release_values[21]}"
service_configuration_sha256="${release_values[22]}"
required_rocm_version="${release_values[23]}"
required_gpu_name="${release_values[24]}"
required_gpu_arch="${release_values[25]}"
required_compute_units="${release_values[26]}"
required_vram_bytes="${release_values[27]}"
required_winner_report_sha256="${release_values[28]}"
reference_label="${release_values[29]}"
candidate_source_index_sha256="${release_values[30]}"
quality_qualified_candidate_count="${release_values[31]}"
quality_negative_label="${release_values[32]}"
quality_negative_manifest_sha256="${release_values[33]}"
stability_report_sha256="${release_values[34]}"
stability_run_count="${release_values[35]}"
stability_run_ids_sha256="${release_values[36]}"
soak_report_sha256="${release_values[37]}"
soak_run_id="${release_values[38]}"
soak_duration_seconds="${release_values[39]}"
if [[ "$profile_c2_commit" != "$expected_commit" ]]; then
  echo "Release profile C2 commit does not match --expected-commit" >&2
  exit 3
fi

mapfile -t runtime_proof_values < <(python3 - \
  "$runtime_proof" "$profile_c2_commit" "$winner_label" "$reference_label" \
  "$required_winner_report_sha256" \
  "$model_alias" "$model_sha256" "$llama_server_sha256" \
  "$service_configuration_sha256" "$request_configuration_sha256" \
  "$required_rocm_version" "$required_gpu_name" "$required_gpu_arch" \
  "$required_compute_units" "$required_vram_bytes" \
  "$candidate_source_index_sha256" "$quality_qualified_candidate_count" \
  "$quality_negative_label" "$quality_negative_manifest_sha256" \
  "$stability_report_sha256" "$stability_run_count" \
  "$stability_run_ids_sha256" "$soak_report_sha256" "$soak_run_id" \
  "$soak_duration_seconds" <<'PY_RUNTIME_PROOF'
import json
import math
import re
import sys
from pathlib import Path

(
    proof_path,
    expected_commit,
    expected_winner,
    expected_reference,
    expected_winner_report_sha256,
    expected_model_alias,
    expected_model_sha256,
    expected_llama_sha256,
    expected_service_configuration_sha256,
    expected_request_configuration_sha256,
    expected_rocm_version,
    expected_gpu_name,
    expected_gpu_arch,
    expected_compute_units,
    expected_vram_bytes,
    expected_candidate_source_index_sha256,
    expected_quality_candidate_count,
    expected_quality_negative_label,
    expected_quality_negative_manifest_sha256,
    expected_stability_report_sha256,
    expected_stability_run_count,
    expected_stability_run_ids_sha256,
    expected_soak_report_sha256,
    expected_soak_run_id,
    expected_soak_duration_seconds,
) = sys.argv[1:]
proof = json.loads(Path(proof_path).read_text(encoding="utf-8"))
required_fields = {
    "schema_version",
    "status", "run_id", "captured_at_utc", "rocm_version", "gpu_name",
    "gpu_arch", "compute_units", "vram_bytes", "offloaded_layers",
    "total_layers", "model_alias", "model_sha256", "llama_server_sha256",
    "binding_valid", "telemetry_active", "c2_commit", "winner_label",
    "reference_label",
    "winner_assessment_accepted", "winner_report_sha256",
    "winner_core_metric", "winner_core_improvement_percent",
    "request_configuration_sha256",
    "service_configuration_sha256",
    "candidate_source_index_sha256", "quality_qualified_candidate_count",
    "quality_negative_label", "quality_negative_manifest_sha256",
    "stability_report_sha256", "stability_run_count",
    "stability_run_ids_sha256", "soak_report_sha256", "soak_run_id",
    "soak_duration_seconds", "final_evidence_accepted",
}
if not isinstance(proof, dict) or set(proof) != required_fields:
    raise SystemExit("Runtime proof does not match the accepted-final schema")
run_id = proof.get("run_id")
if not isinstance(run_id, str) or re.fullmatch(
    r"[A-Za-z0-9][A-Za-z0-9._:-]{0,47}", run_id
) is None:
    raise SystemExit("Runtime proof run ID is invalid")
if not (
    proof.get("schema_version") == 2
    and proof.get("status") == "accepted_final"
    and proof.get("binding_valid") is True
    and proof.get("telemetry_active") is True
    and proof.get("winner_assessment_accepted") is True
    and proof.get("c2_commit") == expected_commit
    and proof.get("winner_label") == expected_winner
    and proof.get("reference_label") == expected_reference
    and proof.get("winner_report_sha256") == expected_winner_report_sha256
    and proof.get("model_alias") == expected_model_alias
    and proof.get("model_sha256") == expected_model_sha256
    and proof.get("llama_server_sha256") == expected_llama_sha256
    and proof.get("service_configuration_sha256")
    == expected_service_configuration_sha256
    and proof.get("request_configuration_sha256")
    == expected_request_configuration_sha256
    and proof.get("rocm_version") == expected_rocm_version
    and proof.get("gpu_name") == expected_gpu_name
    and proof.get("gpu_arch") == expected_gpu_arch
    and proof.get("compute_units") == int(expected_compute_units)
    and proof.get("vram_bytes") == int(expected_vram_bytes)
    and proof.get("candidate_source_index_sha256")
    == expected_candidate_source_index_sha256
    and proof.get("quality_qualified_candidate_count")
    == int(expected_quality_candidate_count)
    and proof.get("quality_negative_label") == expected_quality_negative_label
    and (
        (proof.get("quality_negative_manifest_sha256") is None
         and expected_quality_negative_manifest_sha256 == "none")
        or proof.get("quality_negative_manifest_sha256")
        == expected_quality_negative_manifest_sha256
    )
    and proof.get("stability_report_sha256") == expected_stability_report_sha256
    and proof.get("stability_run_count") == int(expected_stability_run_count) == 5
    and proof.get("stability_run_ids_sha256")
    == expected_stability_run_ids_sha256
    and proof.get("soak_report_sha256") == expected_soak_report_sha256
    and proof.get("soak_run_id") == expected_soak_run_id
    and isinstance(proof.get("soak_duration_seconds"), (int, float))
    and not isinstance(proof["soak_duration_seconds"], bool)
    and math.isfinite(float(proof["soak_duration_seconds"]))
    and float(proof["soak_duration_seconds"])
    == float(expected_soak_duration_seconds)
    and float(proof["soak_duration_seconds"]) >= 1800.0
    and proof.get("final_evidence_accepted") is True
    and type(proof.get("offloaded_layers")) is int
    and type(proof.get("total_layers")) is int
    and proof["offloaded_layers"] == proof["total_layers"] == 41
    and isinstance(proof.get("winner_report_sha256"), str)
    and re.fullmatch(r"[0-9a-f]{64}", proof["winner_report_sha256"])
    and isinstance(proof.get("winner_core_metric"), str)
    and 1 <= len(proof["winner_core_metric"]) <= 80
    and isinstance(proof.get("winner_core_improvement_percent"), (int, float))
    and not isinstance(proof["winner_core_improvement_percent"], bool)
    and math.isfinite(float(proof["winner_core_improvement_percent"]))
    and float(proof["winner_core_improvement_percent"]) >= 5.0
):
    raise SystemExit("Runtime proof differs from the frozen release profile")
print(run_id)
PY_RUNTIME_PROOF
)
if (( ${#runtime_proof_values[@]} != 1 )); then
  echo "Runtime proof did not produce one evidence run ID" >&2
  exit 3
fi
proof_run_id="${runtime_proof_values[0]}"
if [[ -z "$run_id" ]]; then
  run_id="deployment-$(date -u +%Y%m%dT%H%M%SZ)-$$"
fi
if [[ "$run_id" != "$proof_run_id" ]]; then
  :
else
  echo "Deployment run ID must differ from the immutable evidence run ID" >&2
  exit 3
fi
evidence_run_id="$proof_run_id"
deployment_run_id="$run_id"

python3 - \
  "$required_rocm_version" "$required_gpu_name" "$required_gpu_arch" \
  "$required_compute_units" "$required_vram_bytes" <<'PY_HARDWARE'
import os
import re
import subprocess
import sys
from pathlib import Path

(
    required_rocm_version,
    required_gpu_name,
    required_gpu_arch,
    required_compute_units_text,
    required_vram_bytes_text,
) = sys.argv[1:]
environment = dict(os.environ)
environment["LC_ALL"] = "C"


def capture(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    return completed.stdout


version_path = Path("/opt/rocm/.info/version")
if not version_path.is_file():
    raise SystemExit("ROCm version file is unavailable")
observed_rocm_version = version_path.read_text(
    encoding="utf-8", errors="strict"
).splitlines()[0].strip()
if observed_rocm_version != required_rocm_version:
    raise SystemExit(
        "ROCm version differs from the accepted winner: "
        f"{observed_rocm_version!r} != {required_rocm_version!r}"
    )

rocminfo = capture(["rocminfo"])
accelerator = re.search(
    r"^[ \t]*Name:[ \t]*(gfx[0-9A-Za-z]+)[ \t]*$"
    r"(?:(?!^[ \t]*Name:).)*?"
    r"^[ \t]*Marketing Name:[ \t]*(.+?)[ \t]*$"
    r"(?:(?!^[ \t]*Name:).)*?"
    r"^[ \t]*Compute Unit:[ \t]*([1-9][0-9]*)[ \t]*$",
    rocminfo,
    re.MULTILINE | re.DOTALL,
)
if accelerator is None:
    raise SystemExit("rocminfo lacks a parseable Radeon accelerator block")
observed_gpu_arch, observed_gpu_name, observed_compute_units_text = accelerator.groups()
if (
    observed_gpu_arch != required_gpu_arch
    or observed_gpu_name.strip() != required_gpu_name
    or int(observed_compute_units_text) != int(required_compute_units_text)
):
    raise SystemExit("Radeon GPU identity differs from the accepted winner")

rocm_smi = capture(["rocm-smi"])
vram_values = [
    int(value)
    for value in re.findall(
        r"VRAM Total Memory \(B\):[ \t]*([1-9][0-9]*)",
        rocm_smi,
        re.IGNORECASE,
    )
]
if not vram_values:
    raise SystemExit("rocm-smi lacks total VRAM byte evidence")
observed_vram_bytes = max(vram_values)
if observed_vram_bytes < int(required_vram_bytes_text):
    raise SystemExit("Radeon VRAM is below the accepted winner requirement")
print(
    "hardware_preflight=accepted "
    f"rocm={observed_rocm_version} arch={observed_gpu_arch} "
    f"cu={observed_compute_units_text} vram_bytes={observed_vram_bytes}"
)
PY_HARDWARE

current_uid="$(id -u)"
ensure_private_directory() {
  local path="$1"
  local create_parents="${2:-0}"
  if [[ -L "$path" ]]; then
    echo "Private directory must not be a symbolic link: $path" >&2
    return 1
  fi
  if [[ ! -e "$path" ]]; then
    if (( create_parents == 1 )); then
      mkdir -m 0700 -p -- "$path"
    else
      mkdir -m 0700 -- "$path"
    fi
  elif [[ ! -d "$path" ]]; then
    echo "Private path must be a directory: $path" >&2
    return 1
  fi
  if [[ "$(stat -c '%u' -- "$path")" != "$current_uid" \
        || "$(stat -c '%a' -- "$path")" != "700" ]]; then
    echo "Private directory must be owned by the current user with mode 0700: $path" >&2
    return 1
  fi
}

ensure_private_directory "$state_root" 1

release_root="$state_root/releases"
artifact_root="$state_root/artifacts"
release_dir="$release_root/$run_id"
repo_dir="$release_dir/repo"
venv_dir="$release_dir/venv"
run_dir="$release_dir/run"
process_home="$release_dir/home"
process_tmp="$release_dir/tmp"
runtime_dir="$artifact_root/llama-${llama_runtime_sha256:0:12}"
runtime_partial="$artifact_root/.llama-${llama_runtime_sha256:0:12}.${run_id}.partial"
model_dir="$artifact_root/model"
model_file="$model_dir/$model_name"
model_partial="$model_dir/.${model_name}.${run_id}.partial"

ensure_private_directory "$release_root"
ensure_private_directory "$artifact_root"
ensure_private_directory "$model_dir"
if [[ -e "$release_dir" || -L "$release_dir" ]]; then
  echo "Release directory already exists; choose a new run ID: $release_dir" >&2
  exit 2
fi
ensure_private_directory "$release_dir"
ensure_private_directory "$run_dir"
ensure_private_directory "$process_home"
ensure_private_directory "$process_tmp"
frozen_profile="$release_dir/release-profile.json"
frozen_runtime_proof="$release_dir/runtime-proof.json"
install -m 0600 -- "$release_profile" "$frozen_profile"
install -m 0600 -- "$runtime_proof" "$frozen_runtime_proof"
verify_sha256 "$release_profile_sha256" "$frozen_profile"
verify_sha256 "$runtime_proof_sha256" "$frozen_runtime_proof"

git -C "$release_dir" init -q repo
git -C "$repo_dir" fetch -q "$source_bundle" "$bundle_ref"
git -C "$repo_dir" checkout -q --detach FETCH_HEAD
actual_commit="$(git -C "$repo_dir" rev-parse HEAD)"
if [[ "$actual_commit" != "$expected_commit" ]]; then
  echo "Recovered commit does not match the manifest" >&2
  exit 3
fi

project_dir="$repo_dir/submissions/track2-radeonstay"
test -f "$project_dir/requirements.lock"
python3 -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install -r "$project_dir/requirements.lock"
"$venv_dir/bin/python" -m pip install --no-deps -e "$project_dir"

verify_runtime_tree() {
  local tree_root="$1"
  local operation="$2"
  python3 - "$tree_root" "$operation" "$llama_runtime_sha256" <<'PY_RUNTIME_TREE'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
operation = sys.argv[2]
archive_sha256 = sys.argv[3]
manifest = root / ".radeonstay-runtime-manifest.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort()
        file_names.sort()
        for name in [*directory_names, *file_names]:
            path = Path(directory) / name
            if path == manifest:
                continue
            relative = path.relative_to(root).as_posix()
            metadata = path.lstat()
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISDIR(metadata.st_mode):
                row: dict[str, object] = {
                    "path": relative,
                    "kind": "directory",
                    "mode": mode,
                }
            elif stat.S_ISREG(metadata.st_mode):
                row = {
                    "path": relative,
                    "kind": "file",
                    "mode": mode,
                    "sha256": file_sha256(path),
                }
            elif stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(path)
                resolved_target = (path.parent / target).resolve()
                if os.path.commonpath((root, resolved_target)) != str(root):
                    raise SystemExit(f"Runtime symlink escapes its root: {relative}")
                row = {
                    "path": relative,
                    "kind": "symlink",
                    "target": target,
                }
            else:
                raise SystemExit(f"Runtime contains an unsupported file type: {relative}")
            rows.append(row)
    return sorted(rows, key=lambda row: str(row["path"]))


payload = {
    "schema_version": 1,
    "archive_sha256": archive_sha256,
    "entries": inventory(),
}
if operation == "create":
    if manifest.exists() or manifest.is_symlink():
        raise SystemExit("Runtime integrity manifest already exists")
    descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
elif operation == "verify":
    metadata = manifest.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.geteuid()
    ):
        raise SystemExit("Runtime integrity manifest is not a private regular file")
    observed = json.loads(manifest.read_text(encoding="utf-8"))
    if observed != payload:
        raise SystemExit("Cached llama runtime differs from its frozen tree manifest")
else:
    raise SystemExit("Unsupported runtime tree operation")
PY_RUNTIME_TREE
}

if [[ -e "$runtime_dir" || -L "$runtime_dir" ]]; then
  ensure_private_directory "$runtime_dir"
  verify_runtime_tree "$runtime_dir" verify
else
  if [[ -e "$runtime_partial" || -L "$runtime_partial" ]]; then
    echo "Runtime partial path already exists; use a fresh run ID" >&2
    exit 3
  fi
  python3 - "$llama_runtime" <<'PY_RUNTIME_ARCHIVE'
import posixpath
import sys
import tarfile
from pathlib import PurePosixPath

archive = sys.argv[1]
with tarfile.open(archive, mode="r:gz") as handle:
    members = handle.getmembers()
    if not members:
        raise SystemExit("Runtime archive is empty")
    for member in members:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise SystemExit(f"Runtime archive path is unsafe: {member.name!r}")
        if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
            raise SystemExit(f"Runtime archive file type is unsafe: {member.name!r}")
        if member.islnk():
            raise SystemExit(f"Runtime archive hard links are forbidden: {member.name!r}")
        if member.issym():
            target = PurePosixPath(member.linkname)
            resolved = PurePosixPath(
                posixpath.normpath(str(name.parent / target))
            )
            if target.is_absolute() or ".." in resolved.parts:
                raise SystemExit(
                    f"Runtime archive symlink escapes its root: {member.name!r}"
                )
PY_RUNTIME_ARCHIVE
  ensure_private_directory "$runtime_partial"
  tar --no-same-owner --no-same-permissions -xzf "$llama_runtime" -C "$runtime_partial"
  partial_llama_server="$runtime_partial/bin/llama-server"
  if [[ ! -x "$partial_llama_server" || -L "$partial_llama_server" ]]; then
    echo "Runtime archive lacks a regular executable llama-server" >&2
    exit 3
  fi
  verify_sha256 "$llama_server_sha256" "$partial_llama_server"
  verify_runtime_tree "$runtime_partial" create
  mv -T -- "$runtime_partial" "$runtime_dir"
  ensure_private_directory "$runtime_dir"
  verify_runtime_tree "$runtime_dir" verify
fi
llama_server="$runtime_dir/bin/llama-server"
if [[ ! -x "$llama_server" || -L "$llama_server" ]]; then
  echo "Recovered llama-server is not executable" >&2
  exit 3
fi
verify_sha256 "$llama_server_sha256" "$llama_server"

if [[ -f "$model_file" && ! -L "$model_file" ]]; then
  if [[ "$(stat -c '%u' -- "$model_file")" != "$current_uid" \
        || "$(stat -c '%a' -- "$model_file")" != "600" ]]; then
    echo "Cached model must be owned by the current user with mode 0600" >&2
    exit 3
  fi
  verify_sha256 "$model_sha256" "$model_file"
else
  if [[ -e "$model_file" || -e "$model_partial" ]]; then
    echo "Model destination or partial file already exists unexpectedly" >&2
    exit 3
  fi
  curl --fail --location --retry 3 \
    "https://huggingface.co/$model_repository/resolve/$model_revision/$model_name?download=true" \
    --output "$model_partial"
  verify_sha256 "$model_sha256" "$model_partial"
  mv -- "$model_partial" "$model_file"
  chmod 0600 "$model_file"
fi

if ss -ltnH | awk '{print $4}' | grep -Eq "(^|:)$model_port$"; then
  echo "Model port is already occupied: $model_port" >&2
  exit 3
fi
if ss -ltnH | awk '{print $4}' | grep -Eq "(^|:)$app_port$"; then
  echo "Application port is already occupied: $app_port" >&2
  exit 3
fi

credentials_file="$release_dir/access-credentials.txt"
env_file="$project_dir/.env"
runtime_instance_file="$run_dir/runtime-instance.json"
"$venv_dir/bin/python" - \
  "$env_file" "$credentials_file" "$app_port" "$model_port" \
  "$ui_username" "$run_id" "$runtime_instance_file" "$model_alias" \
  "$thinking_enabled" "$fused_plan_evidence" "$frozen_runtime_proof" \
  "$evidence_run_id" <<'PY_ENV'
import os
import secrets
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
credentials_path = Path(sys.argv[2])
(
    app_port,
    model_port,
    username,
    run_id,
    runtime_instance_path,
    model_alias,
    thinking_enabled,
    fused_plan_evidence,
    runtime_proof_path,
    evidence_run_id,
) = sys.argv[3:]
if thinking_enabled not in {"0", "1"} or fused_plan_evidence not in {"0", "1"}:
    raise SystemExit("Release request flags must be 0 or 1")
password = secrets.token_urlsafe(24)
values = {
    "RADEONSTAY_MODEL_BASE_URL": f"http://127.0.0.1:{model_port}/v1",
    "RADEONSTAY_MODEL_NAME": model_alias,
    "RADEONSTAY_MODEL_API_KEY": "local-only",
    "RADEONSTAY_MODEL_TIMEOUT_SECONDS": "120",
    "RADEONSTAY_MODEL_ENABLE_THINKING": thinking_enabled,
    "RADEONSTAY_FUSED_PLAN_EVIDENCE": fused_plan_evidence,
    "RADEONSTAY_RUNTIME_PROOF_PATH": runtime_proof_path,
    "RADEONSTAY_RUNTIME_INSTANCE_PATH": runtime_instance_path,
    "RADEONSTAY_ISOLATED_DEMO": "1",
    "RADEONSTAY_DEMO_RUN_ID": run_id,
    "RADEONSTAY_EVIDENCE_RUN_ID": evidence_run_id,
    "RADEONSTAY_DATABASE_PATH": "runtime/radeonstay.db",
    "RADEONSTAY_POLICY_DIR": "data/policies",
    "RADEONSTAY_AUDIT_SECRET": secrets.token_urlsafe(48),
    "RADEONSTAY_IDENTITY_SECRET": secrets.token_urlsafe(48),
    "RADEONSTAY_DETERMINISTIC_MODE": "0",
    "RADEONSTAY_HOST": "127.0.0.1",
    "RADEONSTAY_PORT": app_port,
    "RADEONSTAY_PUBLIC_DEMO_ENABLED": "1",
    "RADEONSTAY_UI_USERNAME": username,
    "RADEONSTAY_UI_PASSWORD": password,
}
for path, text in (
    (env_path, "".join(f"{key}={value}\n" for key, value in values.items())),
    (
        credentials_path,
        f"username={username}\npassword={password}\n",
    ),
):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
PY_ENV

model_pid=""
app_pid=""
cleanup_on_error() {
  local status=$?
  trap - EXIT
  if (( status == 0 )); then
    return
  fi
  if [[ -n "$app_pid" ]] && kill -0 "$app_pid" 2>/dev/null; then
    kill -TERM "$app_pid" 2>/dev/null || true
  fi
  if [[ -n "$model_pid" ]] && kill -0 "$model_pid" 2>/dev/null; then
    kill -TERM "$model_pid" 2>/dev/null || true
  fi
  echo "Restore failed; logs and downloaded artifacts were preserved in $release_dir" >&2
  exit "$status"
}
trap cleanup_on_error EXIT

model_log="$run_dir/llama-server.log"
app_log="$run_dir/app.log"
nohup env -i \
  PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  HOME="$process_home" \
  TMPDIR="$process_tmp" \
  LANG="C.UTF-8" \
  LC_ALL="C.UTF-8" \
  LD_LIBRARY_PATH="$runtime_dir/bin:/opt/rocm/lib:/opt/rocm/lib64" \
  LLAMA_SERVER="$llama_server" \
  MODEL_PATH="$model_file" \
  MODEL_ALIAS="$model_alias" \
  MODEL_HOST="127.0.0.1" \
  MODEL_PORT="$model_port" \
  CONTEXT_SIZE="$context_size" \
  PARALLEL_SLOTS="$parallel_slots" \
  BATCH_SIZE="$batch_size" \
  UBATCH_SIZE="$ubatch_size" \
  FLASH_ATTN="$flash_attn" \
  GPU_LAYERS="$gpu_layers" \
  CACHE_TYPE_K="$cache_type_k" \
  CACHE_TYPE_V="$cache_type_v" \
  EXPECTED_SERVICE_CONFIGURATION_SHA256="$service_configuration_sha256" \
  EVIDENCE_RUN_ID="$evidence_run_id" \
  RADEONSTAY_DEMO_RUN_ID="$deployment_run_id" \
  RADEONSTAY_RUNTIME_INSTANCE_PATH="$runtime_instance_file" \
  PYTHON_BIN="$venv_dir/bin/python" \
  "$project_dir/scripts/serve_model.sh" > "$model_log" 2>&1 < /dev/null &
model_pid=$!
printf '%s\n' "$model_pid" > "$run_dir/model.pid"

model_ready=0
for (( attempt = 1; attempt <= 300; attempt++ )); do
  if ! kill -0 "$model_pid" 2>/dev/null; then
    tail -n 100 "$model_log" >&2
    exit 5
  fi
  if curl --fail --silent --max-time 2 \
      "http://127.0.0.1:$model_port/v1/models" >/dev/null 2>&1; then
    model_ready=1
    break
  fi
  sleep 1
done
if (( model_ready == 0 )); then
  echo "Model did not become ready within 300 seconds" >&2
  exit 5
fi

cd "$project_dir"
nohup env -i \
  PATH="$venv_dir/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  HOME="$process_home" \
  TMPDIR="$process_tmp" \
  LANG="C.UTF-8" \
  LC_ALL="C.UTF-8" \
  "$project_dir/scripts/serve_app.sh" > "$app_log" 2>&1 < /dev/null &
app_pid=$!
printf '%s\n' "$app_pid" > "$run_dir/app.pid"

app_ready=0
for (( attempt = 1; attempt <= 120; attempt++ )); do
  if ! kill -0 "$app_pid" 2>/dev/null; then
    tail -n 100 "$app_log" >&2
    exit 5
  fi
  if curl --fail --silent --max-time 5 \
      "http://127.0.0.1:$app_port/health/ready" >/dev/null 2>&1; then
    app_ready=1
    break
  fi
  sleep 1
done
if (( app_ready == 0 )); then
  echo "Application did not become ready within 120 seconds" >&2
  exit 5
fi

unauth_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "http://127.0.0.1:$app_port/config")"
if [[ "$unauth_status" != "401" && "$unauth_status" != "403" ]]; then
  echo "Public UI authentication gate did not reject an anonymous config request" >&2
  exit 6
fi

tunnel_url="disabled"
if (( expose_tunnel == 1 )); then
  /var/run/secrets/frp-self-service/install
  tunnel_output="$("$HOME/.local/bin/rc-tunnel" expose --port "$app_port")"
  printf '%s\n' "$tunnel_output" > "$release_dir/tunnel.txt"
  tunnel_url="$(grep -Eo 'https://rc-[A-Za-z0-9-]+\.radeon\.firstdg\.ai' \
    "$release_dir/tunnel.txt" | head -n 1 || true)"
  if [[ -z "$tunnel_url" ]]; then
    echo "Tunnel started without returning a recognized public URL" >&2
    exit 6
  fi
fi

trap - EXIT
printf 'restore_status=complete\n'
printf 'evidence_run_id=%s\n' "$evidence_run_id"
printf 'deployment_run_id=%s\n' "$deployment_run_id"
printf 'winner_label=%s\n' "$winner_label"
printf 'release_profile=%s\n' "$frozen_profile"
printf 'release_profile_sha256=%s\n' "$release_profile_sha256"
printf 'runtime_proof=%s\n' "$frozen_runtime_proof"
printf 'runtime_proof_sha256=%s\n' "$runtime_proof_sha256"
printf 'release_dir=%s\n' "$release_dir"
printf 'credentials_file=%s\n' "$credentials_file"
printf 'public_url=%s\n' "$tunnel_url"
printf 'health_url=http://127.0.0.1:%s/health/ready\n' "$app_port"
