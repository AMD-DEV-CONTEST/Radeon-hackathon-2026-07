#!/usr/bin/env bash
set -euo pipefail
set -o noclobber

EXPECTED_CONTRACT_SHA256=158be58ad9c2dc94509c028ac992a709c74457144c02ee66908c1dbb7bf523fb
MIN_DEMO_PACKAGE_RESERVE_SECONDS=${MIN_DEMO_PACKAGE_RESERVE_SECONDS:-28800}

mode=${1:-verify-only}
script_path=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")
project_root=$(cd "$(dirname "${script_path}")/.." && pwd)
contract_path=${2:-${project_root}/configs/act-rocm-submission-demo-training-10k-diagnostic-v2.json}

if [[ "${mode}" != "verify-only" && "${mode}" != "run" ]]; then
  printf 'usage: %s [verify-only|run] [/absolute/training-contract.json]\n' "$0" >&2
  exit 64
fi
if [[ "${contract_path}" != /* || ! -f "${contract_path}" ]]; then
  printf 'training contract must be an existing absolute file: %s\n' "${contract_path}" >&2
  exit 65
fi
if [[ "${project_root}" != /workspace/persistent/mantis-track3/* ]]; then
  printf 'project root is outside the durable Mantis root: %s\n' "${project_root}" >&2
  exit 66
fi
if [[ -z "${EXPECTED_SUPERVISOR_SHA256:-}" || -z "${EXPECTED_LIVE_INFER_SHA256:-}" ]]; then
  printf 'EXPECTED_SUPERVISOR_SHA256 and EXPECTED_LIVE_INFER_SHA256 are required\n' >&2
  exit 67
fi

hash_of() {
  sha256sum "$1" | awk '{print $1}'
}

is_strict_descendant() {
  local root=$1
  local candidate=$2
  [[ "${candidate}" != "${root}/" ]] \
    && [[ "${candidate}" == "${root}/"* ]] \
    && [[ "${candidate}" != *"//"* ]] \
    && [[ "${candidate}" != *"/./"* ]] \
    && [[ "${candidate}" != *"/../"* ]] \
    && [[ "${candidate}" != */. ]] \
    && [[ "${candidate}" != */.. ]]
}

if [[ "$(hash_of "${contract_path}")" != "${EXPECTED_CONTRACT_SHA256}" ]]; then
  printf 'training contract hash mismatch\n' >&2
  exit 68
fi
if [[ "$(hash_of "${script_path}")" != "${EXPECTED_SUPERVISOR_SHA256}" ]]; then
  printf 'supervisor source hash mismatch\n' >&2
  exit 69
fi
live_infer=${project_root}/tools/mantis_live_infer.py
if [[ ! -f "${live_infer}" || "$(hash_of "${live_infer}")" != "${EXPECTED_LIVE_INFER_SHA256}" ]]; then
  printf 'accepted live-inference source hash mismatch\n' >&2
  exit 70
fi

bootstrap_python=$(command -v python3)
mapfile -t contract_values < <(
  "${bootstrap_python}" - "${contract_path}" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
values = [
    data["training_id"],
    data["status"],
    data["deadline"],
    data["runtime"]["persistent_root"],
    data["runtime"]["python"],
    data["runtime"]["train_binary"],
    data["runtime"]["torch"],
    data["runtime"]["hip"],
    data["runtime"]["device"],
    data["runtime"]["genesis"],
    data["runtime"]["genesis_revision"],
    data["runtime"]["lerobot"],
    str(data["runtime"]["visible_gpu_count"]),
    data["dataset"]["repo_id"],
    data["dataset"]["root"],
    data["dataset"]["codebase_version"],
    str(data["dataset"]["episodes"]),
    str(data["dataset"]["frames"]),
    str(data["dataset"]["state_dimension"]),
    str(data["dataset"]["action_dimension"]),
    data["output"]["training_root"],
    data["output"]["evidence_root"],
    str(data["policy"]["seed"]),
    str(data["policy"]["steps"]),
    str(data["policy"]["batch_size"]),
    str(data["policy"]["num_workers"]),
    str(data["policy"]["chunk_size"]),
    str(data["policy"]["n_action_steps"]),
    str(data["policy"]["n_obs_steps"]),
    str(data["policy"]["save_freq"]),
    str(data["policy"]["log_freq"]),
    str(data["policy"]["eval_steps"]),
    data["required_environment"]["HF_LEROBOT_HOME"],
    data["required_environment"]["HF_HUB_OFFLINE"],
    data["required_environment"]["TRANSFORMERS_OFFLINE"],
    data["required_environment"]["HIP_VISIBLE_DEVICES"],
    data["required_environment"]["ROCR_VISIBLE_DEVICES"],
    data["required_environment"]["CUDA_VISIBLE_DEVICES"],
    str(data["schedule"]["measured_seconds_per_step"]),
]
for value in values:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise SystemExit("contract values must be single-line")
    print(text)
PY
)
if [[ ${#contract_values[@]} -ne 39 ]]; then
  printf 'training contract parse did not yield the exact field set\n' >&2
  exit 71
fi

training_id=${contract_values[0]}
contract_status=${contract_values[1]}
deadline=${contract_values[2]}
persistent_root=${contract_values[3]}
python_bin=${contract_values[4]}
train_bin=${contract_values[5]}
expected_torch=${contract_values[6]}
expected_hip=${contract_values[7]}
expected_device=${contract_values[8]}
expected_genesis=${contract_values[9]}
expected_genesis_revision=${contract_values[10]}
expected_lerobot=${contract_values[11]}
expected_gpu_count=${contract_values[12]}
repo_id=${contract_values[13]}
dataset_root=${contract_values[14]}
dataset_codebase=${contract_values[15]}
dataset_episodes=${contract_values[16]}
dataset_frames=${contract_values[17]}
state_dimension=${contract_values[18]}
action_dimension=${contract_values[19]}
training_root=${contract_values[20]}
formal_evidence_root=${contract_values[21]}
seed=${contract_values[22]}
steps=${contract_values[23]}
batch_size=${contract_values[24]}
num_workers=${contract_values[25]}
chunk_size=${contract_values[26]}
action_steps=${contract_values[27]}
obs_steps=${contract_values[28]}
save_freq=${contract_values[29]}
log_freq=${contract_values[30]}
eval_steps=${contract_values[31]}
hf_lerobot_home=${contract_values[32]}
hf_hub_offline=${contract_values[33]}
transformers_offline=${contract_values[34]}
hip_visible_devices=${contract_values[35]}
rocr_visible_devices=${contract_values[36]}
cuda_visible_devices=${contract_values[37]}
seconds_per_step=${contract_values[38]}

if [[ "${contract_status}" != execution_authorized_pending_source_acceptance ]]; then
  printf 'training contract status is not launch-admissible: %s\n' "${contract_status}" >&2
  exit 72
fi
durable_root=/workspace/persistent/mantis-track3
if [[ "${persistent_root}" != "${durable_root}" ]]; then
  printf 'contract persistent root is not the exact durable root: %s\n' \
    "${persistent_root}" >&2
  exit 73
fi
for path in "${dataset_root}" "${training_root}" "${formal_evidence_root}"; do
  if ! is_strict_descendant "${durable_root}" "${path}"; then
    printf 'contract path escapes durable root: %s\n' "${path}" >&2
    exit 73
  fi
done
if (( steps <= 0 || save_freq <= 0 || steps % save_freq != 0 )); then
  printf 'training steps must be a positive multiple of save_freq\n' >&2
  exit 73
fi
if [[ "${mode}" == verify-only ]]; then
  evidence_root=${formal_evidence_root}-preflight-v1
else
  evidence_root=${formal_evidence_root}
fi
if [[ -e "${training_root}" || -L "${training_root}" ]]; then
  printf 'refusing existing training root: %s\n' "${training_root}" >&2
  exit 74
fi
if [[ -e "${evidence_root}" || -L "${evidence_root}" ]]; then
  printf 'refusing existing evidence root: %s\n' "${evidence_root}" >&2
  exit 75
fi
for executable in "${python_bin}" "${train_bin}"; do
  if [[ ! -f "${executable}" || ! -x "${executable}" ]]; then
    printf 'runtime executable must resolve to a regular executable file: %s\n' \
      "${executable}" >&2
    exit 76
  fi
done
if [[ ! -d "${dataset_root}" || -L "${dataset_root}" ]]; then
  printf 'dataset root must be a real non-symlink directory: %s\n' \
    "${dataset_root}" >&2
  exit 76
fi
if [[ "$(readlink -f /workspace/persistent)" != /persistent ]]; then
  printf '/workspace/persistent does not resolve to /persistent\n' >&2
  exit 77
fi

mkdir "${evidence_root}"
printf '%s\n' "$$" > "${evidence_root}/supervisor.pid"
date -u +%Y-%m-%dT%H:%M:%SZ > "${evidence_root}/started_at_utc.txt"
printf '%s\n' "${mode}" > "${evidence_root}/mode.txt"
printf '%s\n' "${MIN_DEMO_PACKAGE_RESERVE_SECONDS}" > "${evidence_root}/minimum_demo_package_reserve_seconds.txt"

telemetry_pid=
terminal_status=
capture_kfd_owners() {
  local phase=$1
  local json_output=${evidence_root}/kfd_owners_${phase}.json
  local count_output=${evidence_root}/kfd_owner_count_${phase}.txt
  "${python_bin}" - /proc "${json_output}" "${count_output}" <<'PY'
import errno
import json
import os
import sys
from pathlib import Path

proc_root = Path(sys.argv[1])
json_output = Path(sys.argv[2])
count_output = Path(sys.argv[3])
owners = []
scan_errors = []

try:
    processes = sorted(
        (path for path in proc_root.iterdir() if path.name.isdigit()),
        key=lambda path: int(path.name),
    )
except OSError as exc:
    processes = []
    scan_errors.append({
        "scope": str(proc_root),
        "error": type(exc).__name__,
        "errno": exc.errno,
    })

for process in processes:
    fd_root = process / "fd"
    try:
        descriptors = list(fd_root.iterdir())
    except FileNotFoundError:
        continue
    except OSError as exc:
        scan_errors.append({
            "pid": int(process.name),
            "scope": str(fd_root),
            "error": type(exc).__name__,
            "errno": exc.errno,
        })
        continue

    kfd_descriptors = []
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                continue
            scan_errors.append({
                "pid": int(process.name),
                "scope": str(descriptor),
                "error": type(exc).__name__,
                "errno": exc.errno,
            })
            continue
        if target == "/dev/kfd":
            kfd_descriptors.append(descriptor.name)

    if not kfd_descriptors:
        continue
    try:
        comm = (process / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        comm = None
    try:
        executable = os.readlink(process / "exe")
    except OSError:
        executable = None
    owners.append({
        "pid": int(process.name),
        "descriptors": sorted(kfd_descriptors),
        "comm": comm,
        "executable": executable,
    })

result = {
    "schema_version": 1,
    "proc_root": str(proc_root),
    "device": "/dev/kfd",
    "scan_complete": not scan_errors,
    "owner_count": len(owners),
    "owners": owners,
    "scan_errors": scan_errors,
    "claim_boundary": "Live /dev/kfd file-descriptor ownership only; rocm-smi process rows remain separate advisory telemetry.",
}
with json_output.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")
with count_output.open("x", encoding="utf-8") as stream:
    stream.write(f"{len(owners)}\n")
if scan_errors:
    raise SystemExit(2)
PY
}

finalize() {
  local rc=$?
  local finalization_rc=0
  trap - EXIT
  set +e
  if [[ -n "${telemetry_pid}" ]]; then
    kill "${telemetry_pid}" 2>/dev/null
    wait "${telemetry_pid}" 2>/dev/null
  fi
  printf '%s\n' "$(readlink -f /workspace/persistent 2>/dev/null)" \
    > "${evidence_root}/persistent_mount_after.txt"
  if [[ "$(<"${evidence_root}/persistent_mount_after.txt")" != /persistent ]]; then
    finalization_rc=90
  fi
  PYTHONPATH=${project_root}/src "${python_bin}" \
    "${project_root}/tools/check_amd_persistence.py" \
    --check-filesystem \
    --durable-path "training=${training_root}" \
    --durable-path "evidence=${evidence_root}" \
    > "${evidence_root}/persistence_after.json" 2>&1 \
    || finalization_rc=91
  /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids \
    > "${evidence_root}/gpu_after.txt" 2>&1 \
    || finalization_rc=92
  local kfd_after=-1
  local kfd_scan_rc=0
  capture_kfd_owners after || kfd_scan_rc=$?
  if [[ -f "${evidence_root}/kfd_owner_count_after.txt" ]]; then
    kfd_after=$(<"${evidence_root}/kfd_owner_count_after.txt")
  fi
  local matching_after
  matching_after=$(pgrep -af '[l]erobot-train|[m]antis_live_infer.py' || true)
  printf '%s\n' "${matching_after}" > "${evidence_root}/matching_processes_after.txt"
  if ! grep -Eq 'GPU use \(%\): 0' "${evidence_root}/gpu_after.txt" \
    || ! grep -Eq 'GPU Memory Allocated \(VRAM%\): 0' "${evidence_root}/gpu_after.txt" \
    || [[ "${kfd_after}" -ne 0 ]] \
    || [[ -n "${matching_after}" ]]; then
    finalization_rc=93
  fi
  if [[ "${kfd_scan_rc}" -ne 0 ]]; then
    finalization_rc=96
  fi
  if [[ "${rc}" -eq 0 && -z "${terminal_status}" ]]; then
    finalization_rc=95
  fi
  if [[ "${rc}" -eq 0 && "${finalization_rc}" -ne 0 ]]; then
    rc=${finalization_rc}
  fi
  date -u +%Y-%m-%dT%H:%M:%SZ > "${evidence_root}/finished_at_utc.txt"
  if [[ "${finalization_rc}" -ne 0 ]]; then
    printf 'finalization failed with code %s\n' "${finalization_rc}" \
      > "${evidence_root}/finalization_errors.txt"
    printf 'FAIL_FINALIZATION\n' > "${evidence_root}/status"
  elif [[ "${rc}" -eq 0 && -n "${terminal_status}" ]]; then
    printf '%s\n' "${terminal_status}" > "${evidence_root}/status"
  else
    printf 'FAIL\n' > "${evidence_root}/status"
  fi
  printf '%s\n' "${rc}" > "${evidence_root}/supervisor.exit_code.txt"
  (
    cd "${evidence_root}" || exit 1
    find . -type f \
      ! -name final_evidence.SHA256SUMS \
      ! -name final_evidence.verify.log \
      -print0 \
      | sort -z | xargs -0 sha256sum > final_evidence.SHA256SUMS
    sha256sum -c final_evidence.SHA256SUMS > final_evidence.verify.log 2>&1
  )
  local manifest_rc=$?
  if [[ "${manifest_rc}" -ne 0 ]]; then
    finalization_rc=94
    printf 'final manifest generation or verification failed\n' \
      >| "${evidence_root}/finalization_errors.txt"
    printf 'FAIL_FINALIZATION\n' >| "${evidence_root}/status"
    if [[ "${rc}" -eq 0 ]]; then
      rc=${finalization_rc}
      printf '%s\n' "${rc}" >| "${evidence_root}/supervisor.exit_code.txt"
    fi
  fi
  exit "${rc}"
}
trap finalize EXIT

"${python_bin}" - "${python_bin}" "${train_bin}" \
  > "${evidence_root}/executable_identity.json" <<'PY'
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


python_path = Path(sys.argv[1])
train_path = Path(sys.argv[2])
python_real = python_path.resolve(strict=True)
train_real = train_path.resolve(strict=True)
first_line = train_real.open("rb").readline(4096).decode("utf-8", "strict").strip()
shebang_tokens = shlex.split(first_line[2:]) if first_line.startswith("#!") else []
shebang_path = Path(shebang_tokens[0]) if len(shebang_tokens) == 1 else None
expected_prefix = python_path.parent.parent.resolve()
checks = {
    "python_contract_path_absolute": python_path.is_absolute(),
    "python_sys_executable_same_venv": (
        Path(sys.executable).parent.resolve() == python_path.parent.resolve()
        and Path(sys.executable).resolve() == python_real
    ),
    "python_prefix_exact": Path(sys.prefix).resolve() == expected_prefix,
    "python_real_regular_executable": python_real.is_file() and os.access(python_real, os.X_OK),
    "train_contract_path_absolute": train_path.is_absolute(),
    "train_real_regular_executable": train_real.is_file() and os.access(train_real, os.X_OK),
    "train_basename_exact": train_path.name == "lerobot-train",
    "train_shebang_single_absolute_interpreter": (
        shebang_path is not None and shebang_path.is_absolute()
    ),
    "train_shebang_same_venv_bin": (
        shebang_path is not None
        and shebang_path.parent.resolve() == python_path.parent.resolve()
    ),
    "train_shebang_same_interpreter": (
        shebang_path is not None
        and shebang_path.resolve(strict=True) == python_real
    ),
}
observed = {
    "python_contract_path": str(python_path),
    "python_realpath": str(python_real),
    "python_sha256": sha256_file(python_real),
    "sys_executable": sys.executable,
    "sys_prefix": sys.prefix,
    "train_contract_path": str(train_path),
    "train_realpath": str(train_real),
    "train_sha256": sha256_file(train_real),
    "train_shebang": first_line,
    "train_shebang_interpreter": str(shebang_path) if shebang_path else None,
}
result = {
    "schema_version": 1,
    "pass": all(checks.values()),
    "checks": checks,
    "observed": observed,
}
print(json.dumps(result, indent=2, sort_keys=True))
if not result["pass"]:
    raise SystemExit(2)
PY

printf '%s  %s\n' "${EXPECTED_CONTRACT_SHA256}" "${contract_path}" \
  > "${evidence_root}/accepted_contract.sha256"
printf '%s  %s\n' "${EXPECTED_SUPERVISOR_SHA256}" "${script_path}" \
  > "${evidence_root}/accepted_supervisor.sha256"
printf '%s  %s\n' "${EXPECTED_LIVE_INFER_SHA256}" "${live_infer}" \
  > "${evidence_root}/accepted_live_infer.sha256"
source_inputs=(
  "${contract_path}"
  "${script_path}"
  "${live_infer}"
  "${project_root}/tools/check_amd_persistence.py"
  "${project_root}/tools/capture_act_checkpoint_receipt.py"
  "${project_root}/tools/extract_lerobot_train_metrics.py"
  "${project_root}/src/mantis_rocm_bridge/amd_persistence.py"
  "${project_root}/src/mantis_rocm_bridge/camera_mounts.py"
  "${project_root}/src/mantis_rocm_bridge/contracts.py"
  "${project_root}/src/mantis_rocm_bridge/genesis_smoke.py"
  "${project_root}/src/mantis_rocm_bridge/gripper.py"
  "${project_root}/src/mantis_rocm_bridge/stack_bowls_env.py"
)
for source_input in "${source_inputs[@]}"; do
  if [[ ! -f "${source_input}" || -L "${source_input}" ]]; then
    printf 'missing or symlinked execution source: %s\n' "${source_input}" >&2
    exit 80
  fi
done
sha256sum "${source_inputs[@]}" \
  > "${evidence_root}/source_and_contracts.SHA256SUMS"
sha256sum -c "${evidence_root}/source_and_contracts.SHA256SUMS" \
  > "${evidence_root}/source_and_contracts.verify.log"

PYTHONPATH=${project_root}/src "${python_bin}" \
  "${project_root}/tools/check_amd_persistence.py" \
  --check-filesystem \
  --durable-path "training=${training_root}" \
  --durable-path "evidence=${evidence_root}" \
  > "${evidence_root}/persistence_check.json"

"${python_bin}" - "${contract_path}" "${dataset_root}" \
  > "${evidence_root}/dataset_identity.json" <<'PY'
import json
import sys
from pathlib import Path

contract = json.load(open(sys.argv[1], encoding="utf-8"))
root = Path(sys.argv[2])
info_path = root / "meta/info.json"
info = json.load(info_path.open(encoding="utf-8"))
expected = contract["dataset"]
expected_cache_parent = Path(contract["required_environment"]["HF_LEROBOT_HOME"])
metadata_repo_id_present = "repo_id" in info
metadata_repo_id = info.get("repo_id")
root_basename_exact = root.name == expected["repo_id"]
cache_parent_exact = root.parent == expected_cache_parent
codebase_version_exact = str(info.get("codebase_version")) == expected["codebase_version"]
repo_id_exact = isinstance(metadata_repo_id, str) and metadata_repo_id == expected["repo_id"]
issues = []
checks = {
    "root_exact": str(root) == expected["root"],
    "root_basename_repo_id_exact": root_basename_exact,
    "cache_parent_exact": cache_parent_exact,
    "codebase_version_exact": codebase_version_exact,
    "episodes_exact": int(info.get("total_episodes", -1)) == expected["episodes"],
    "frames_exact": int(info.get("total_frames", -1)) == expected["frames"],
}
features = info.get("features", {})
checks["state_16d"] = features.get("observation.state", {}).get("shape") == [expected["state_dimension"]]
checks["action_16d"] = features.get("action", {}).get("shape") == [expected["action_dimension"]]
for name, hwc in expected["camera_shapes_hwc"].items():
    checks[f"camera_{name}"] = features.get(name, {}).get("shape") == hwc
repo_id_missing_local_v3 = (
    not metadata_repo_id_present
    and metadata_repo_id is None
    and expected["codebase_version"] == "v3.0"
    and all(checks.values())
)
checks["repo_id_policy_supported"] = repo_id_exact or repo_id_missing_local_v3
for name, passed in checks.items():
    if not passed:
        issues.append(name)
result = {
    "schema_version": 1,
    "pass": not issues,
    "checks": checks,
    "issues": issues,
    "info_path": str(info_path),
    "observed": {
        "cache_parent": str(root.parent),
        "repo_id_field_present": metadata_repo_id_present,
        "metadata_repo_id": metadata_repo_id,
        "repo_id_policy": (
            "metadata_exact" if repo_id_exact
            else "local_v3_missing" if repo_id_missing_local_v3
            else "unsupported"
        ),
        "root_basename": root.name,
    },
}
print(json.dumps(result, indent=2, sort_keys=True))
if issues:
    raise SystemExit(2)
PY

(
  cd "${dataset_root}"
  find . -type f -print0 | sort -z | xargs -0 sha256sum \
    > "${evidence_root}/dataset_payload.SHA256SUMS"
  sha256sum -c "${evidence_root}/dataset_payload.SHA256SUMS" \
    > "${evidence_root}/dataset_payload.verify.log"
)

export HF_LEROBOT_HOME=${hf_lerobot_home}
export HF_HUB_OFFLINE=${hf_hub_offline}
export TRANSFORMERS_OFFLINE=${transformers_offline}
export HF_DATASETS_OFFLINE=1
export HIP_VISIBLE_DEVICES=${hip_visible_devices}
export ROCR_VISIBLE_DEVICES=${rocr_visible_devices}
export CUDA_VISIBLE_DEVICES=${cuda_visible_devices}
export WANDB_MODE=disabled
export PYTHONPATH=${project_root}/src

"${python_bin}" - "${contract_path}" "${project_root}" \
  > "${evidence_root}/runtime_identity.json" <<'PY'
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import genesis
import lerobot
import torch

contract = json.load(open(sys.argv[1], encoding="utf-8"))
project = Path(sys.argv[2])
runtime = contract["runtime"]


genesis_distribution = importlib.metadata.distribution("genesis-world")
direct_url_text = genesis_distribution.read_text("direct_url.json")
direct_url = None
direct_url_error = None
try:
    direct_url = json.loads(direct_url_text) if direct_url_text is not None else None
except (TypeError, json.JSONDecodeError) as error:
    direct_url_error = str(error)

direct_url_value = direct_url.get("url") if isinstance(direct_url, dict) else None
direct_url_has_dir_info = (
    isinstance(direct_url, dict) and isinstance(direct_url.get("dir_info"), dict)
)
parsed_direct_url = urlparse(direct_url_value) if isinstance(direct_url_value, str) else None
direct_url_is_local_file = (
    parsed_direct_url is not None
    and parsed_direct_url.scheme == "file"
    and parsed_direct_url.netloc == ""
    and not parsed_direct_url.query
    and not parsed_direct_url.fragment
)
genesis_url_path = (
    Path(unquote(parsed_direct_url.path))
    if direct_url_is_local_file and parsed_direct_url is not None
    else None
)
genesis_root = None
genesis_git_root = None
genesis_revision = None
git_error = None
if genesis_url_path is not None and genesis_url_path.is_absolute():
    try:
        genesis_root = genesis_url_path.resolve(strict=True)
    except OSError as error:
        git_error = str(error)
if genesis_root is not None and genesis_root.is_dir() and (genesis_root / ".git").exists():
    top_level = subprocess.run(
        ["git", "-C", str(genesis_root), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    head = subprocess.run(
        ["git", "-C", str(genesis_root), "rev-parse", "--verify", "HEAD^{commit}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if top_level.returncode == 0:
        genesis_git_root = Path(top_level.stdout.strip()).resolve()
    if head.returncode == 0:
        genesis_revision = head.stdout.strip()
    if top_level.returncode != 0 or head.returncode != 0:
        git_error = "\n".join(
            item.strip() for item in (top_level.stderr, head.stderr) if item.strip()
        )

persistent_root = Path(runtime["persistent_root"]).resolve(strict=True)
genesis_under_persistent_root = (
    genesis_root is not None
    and (genesis_root == persistent_root or persistent_root in genesis_root.parents)
)
distribution_path = getattr(genesis_distribution, "_path", None)
observed = {
    "torch": str(torch.__version__),
    "hip": str(torch.version.hip),
    "device_count": int(torch.cuda.device_count()),
    "device": str(torch.cuda.get_device_name(0)) if torch.cuda.device_count() else None,
    "lerobot": str(getattr(lerobot, "__version__", "unknown")),
    "genesis": genesis_distribution.version,
    "genesis_revision": genesis_revision,
    "genesis_module_file": str(Path(genesis.__file__).resolve()),
    "genesis_distribution_path": str(Path(distribution_path).resolve()) if distribution_path else None,
    "genesis_direct_url": direct_url,
    "genesis_direct_url_error": direct_url_error,
    "genesis_checkout": str(genesis_root) if genesis_root is not None else None,
    "genesis_git_root": str(genesis_git_root) if genesis_git_root is not None else None,
    "genesis_git_error": git_error,
    "project_root": str(project.resolve()),
    "torch_cuda_available": bool(torch.cuda.is_available()),
}
checks = {
    "torch": observed["torch"] == runtime["torch"],
    "hip": observed["hip"] == runtime["hip"],
    "device_count": observed["device_count"] == runtime["visible_gpu_count"],
    "device": observed["device"] == runtime["device"],
    "lerobot": observed["lerobot"] == runtime["lerobot"],
    "genesis": observed["genesis"] == runtime["genesis"],
    "genesis_direct_url_json": isinstance(direct_url, dict),
    "genesis_direct_url_directory_info": direct_url_has_dir_info,
    "genesis_direct_url_local_file": direct_url_is_local_file,
    "genesis_checkout_absolute": genesis_url_path is not None and genesis_url_path.is_absolute(),
    "genesis_checkout_directory": genesis_root is not None and genesis_root.is_dir(),
    "genesis_checkout_under_persistent_root": genesis_under_persistent_root,
    "genesis_checkout_git_marker": genesis_root is not None and (genesis_root / ".git").exists(),
    "genesis_git_root_exact": genesis_root is not None and genesis_git_root == genesis_root,
    "genesis_revision": observed["genesis_revision"] == runtime["genesis_revision"],
    "rocm_available": observed["torch_cuda_available"] and bool(torch.version.hip),
}
result = {"schema_version": 1, "pass": all(checks.values()), "checks": checks, "observed": observed}
print(json.dumps(result, indent=2, sort_keys=True))
if not result["pass"]:
    raise SystemExit(2)
PY

check_persistent_mount() {
  local phase=$1
  local observed
  observed=$(readlink -f /workspace/persistent)
  printf '%s\n' "${observed}" > "${evidence_root}/persistent_mount_${phase}.txt"
  if [[ "${observed}" != /persistent ]]; then
    printf 'persistent mount drift at %s\n' "${phase}" > "${evidence_root}/block_reason.txt"
    exit 77
  fi
}

check_idle_gpu() {
  local phase=$1
  local gpu_probe
  local kfd_count
  local active_processes
  gpu_probe=$(/opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids 2>&1)
  printf '%s\n' "${gpu_probe}" > "${evidence_root}/gpu_${phase}.txt"
  if ! capture_kfd_owners "${phase}"; then
    printf 'KFD owner audit is incomplete at %s\n' "${phase}" \
      > "${evidence_root}/block_reason.txt"
    exit 78
  fi
  kfd_count=$(<"${evidence_root}/kfd_owner_count_${phase}.txt")
  active_processes=$(pgrep -af '[l]erobot-train|[m]antis_live_infer.py' || true)
  printf '%s\n' "${active_processes}" > "${evidence_root}/matching_processes_${phase}.txt"
  if ! grep -Eq 'GPU use \(%\): 0' <<< "${gpu_probe}" \
    || ! grep -Eq 'GPU Memory Allocated \(VRAM%\): 0' <<< "${gpu_probe}" \
    || [[ "${kfd_count}" -ne 0 ]] \
    || [[ -n "${active_processes}" ]]; then
    printf 'AMD GPU admission is not idle at %s\n' "${phase}" \
      > "${evidence_root}/block_reason.txt"
    exit 78
  fi
}

check_persistent_mount before
check_idle_gpu before

"${python_bin}" - "${deadline}" "${seconds_per_step}" "${steps}" \
  "${MIN_DEMO_PACKAGE_RESERVE_SECONDS}" \
  > "${evidence_root}/deadline_admission.json" <<'PY'
import datetime
import json
import sys

deadline = datetime.datetime.fromisoformat(sys.argv[1])
now = datetime.datetime.now(datetime.timezone.utc)
training_seconds = float(sys.argv[2]) * int(sys.argv[3])
reserve_seconds = int(sys.argv[4])
remaining_seconds = (deadline.astimezone(datetime.timezone.utc) - now).total_seconds()
passed = remaining_seconds >= training_seconds + reserve_seconds
result = {
    "schema_version": 1,
    "pass": passed,
    "checked_at_utc": now.isoformat(),
    "deadline": deadline.isoformat(),
    "remaining_seconds": remaining_seconds,
    "estimated_training_seconds": training_seconds,
    "required_post_training_reserve_seconds": reserve_seconds,
}
print(json.dumps(result, indent=2, sort_keys=True))
if not passed:
    raise SystemExit(2)
PY

train_command=(
  "${train_bin}"
  "--dataset.repo_id=${repo_id}"
  "--policy.type=act"
  "--policy.device=cuda"
  "--output_dir=${training_root}"
  "--job_name=${training_id}"
  "--seed=${seed}"
  "--steps=${steps}"
  "--batch_size=${batch_size}"
  "--num_workers=${num_workers}"
  "--save_freq=${save_freq}"
  "--log_freq=${log_freq}"
  "--eval_steps=${eval_steps}"
  "--save_checkpoint=true"
  "--wandb.enable=false"
  "--policy.chunk_size=${chunk_size}"
  "--policy.n_action_steps=${action_steps}"
  "--policy.n_obs_steps=${obs_steps}"
  "--policy.push_to_hub=false"
)
printf '%q ' "${train_command[@]}" > "${evidence_root}/command.txt"
printf '\n' >> "${evidence_root}/command.txt"
"${python_bin}" -m pip freeze > "${evidence_root}/pip_freeze.txt"
printf '%s\n' \
  "HF_LEROBOT_HOME=${HF_LEROBOT_HOME}" \
  "HF_HUB_OFFLINE=${HF_HUB_OFFLINE}" \
  "TRANSFORMERS_OFFLINE=${TRANSFORMERS_OFFLINE}" \
  "HF_DATASETS_OFFLINE=${HF_DATASETS_OFFLINE}" \
  "HIP_VISIBLE_DEVICES=${HIP_VISIBLE_DEVICES}" \
  "ROCR_VISIBLE_DEVICES=${ROCR_VISIBLE_DEVICES}" \
  "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}" \
  "WANDB_MODE=${WANDB_MODE}" \
  "PYTHONPATH=${PYTHONPATH}" > "${evidence_root}/environment.txt"

if [[ "${mode}" == verify-only ]]; then
  printf '0\n' > "${evidence_root}/training_invocations.txt"
  terminal_status=VERIFY_ONLY_COMPLETE_NO_TRAINING
  exit 0
fi

check_persistent_mount launch
PYTHONPATH=${project_root}/src "${python_bin}" \
  "${project_root}/tools/check_amd_persistence.py" \
  --check-filesystem \
  --durable-path "training=${training_root}" \
  --durable-path "evidence=${evidence_root}" \
  > "${evidence_root}/persistence_launch.json"
check_idle_gpu launch

printf '1\n' > "${evidence_root}/training_invocations.txt"
"${train_command[@]}" > "${evidence_root}/train.log" 2>&1 &
train_pid=$!
printf '%s\n' "${train_pid}" > "${evidence_root}/train.pid"
(
  while kill -0 "${train_pid}" 2>/dev/null; do
    printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids
    sleep 60
  done
) > "${evidence_root}/gpu_during.txt" 2>&1 &
telemetry_pid=$!
printf '%s\n' "${telemetry_pid}" > "${evidence_root}/telemetry.pid"

set +e
wait "${train_pid}"
train_rc=$?
set -e
printf '%s\n' "${train_rc}" > "${evidence_root}/train.exit_code.txt"
if [[ "${train_rc}" -ne 0 ]]; then
  printf 'training child exited nonzero\n' > "${evidence_root}/block_reason.txt"
  exit "${train_rc}"
fi
kill "${telemetry_pid}" 2>/dev/null || true
wait "${telemetry_pid}" 2>/dev/null || true
telemetry_pid=

if grep -Eiq 'Traceback|out of memory|RuntimeError|(^|[^[:alpha:]])nan([^[:alpha:]]|$)|non-finite' \
  "${evidence_root}/train.log"; then
  printf 'fatal training log signature\n' > "${evidence_root}/block_reason.txt"
  exit 79
fi

"${python_bin}" - "${training_root}" "${evidence_root}/checkpoint_audit.json" \
  "${steps}" "${save_freq}" \
  > "${evidence_root}/checkpoint_audit.json" <<'PY'
import json
import sys
from pathlib import Path

training = Path(sys.argv[1])
output = Path(sys.argv[2])
steps = int(sys.argv[3])
save_freq = int(sys.argv[4])
expected = [f"{step:06d}" for step in range(save_freq, steps + 1, save_freq)]
root = training / "checkpoints"
real = sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink())
issues = []
rows = []
if [path.name for path in real] != expected:
    issues.append(f"checkpoint names: {[path.name for path in real]!r}")
for path in real:
    step_file = path / "training_state/training_step.json"
    recorded = json.loads(step_file.read_text()).get("step") if step_file.is_file() else None
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if recorded != int(path.name):
        issues.append(f"{path.name}: recorded step {recorded!r}")
    for required in (
        "pretrained_model/model.safetensors",
        "pretrained_model/config.json",
        "pretrained_model/policy_preprocessor.json",
        "pretrained_model/policy_postprocessor.json",
        "training_state/optimizer_state.safetensors",
    ):
        if not (path / required).is_file():
            issues.append(f"{path.name}: missing {required}")
    rows.append({
        "name": path.name,
        "recorded_step": recorded,
        "file_count": len(files),
        "total_bytes": sum(item.stat().st_size for item in files),
    })
last = root / "last"
expected_last = root / f"{steps:06d}"
if not last.is_symlink() or last.resolve() != expected_last.resolve():
    issues.append(f"last symlink does not target {steps:06d}")
result = {
    "schema_version": 1,
    "pass": not issues,
    "expected": expected,
    "issues": issues,
    "checkpoints": rows,
    "claim_boundary": "Checkpoint serialization only; no convergence or task-success claim.",
}
output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
if issues:
    raise SystemExit(2)
PY

for ((step_value=save_freq; step_value<=steps; step_value+=save_freq)); do
  printf -v step '%06d' "${step_value}"
  PYTHONPATH=${project_root}/src "${python_bin}" \
    "${project_root}/tools/capture_act_checkpoint_receipt.py" \
    "${training_root}/checkpoints/${step}" \
    --expected-step "${step_value}" \
    --training-log "${evidence_root}/train.log" \
    --output-prefix "${evidence_root}/checkpoint_${step}_v1" \
    --skip-gpu
done

PYTHONPATH=${project_root}/src "${python_bin}" \
  "${project_root}/tools/extract_lerobot_train_metrics.py" \
  "${evidence_root}/train.log" \
  --csv "${evidence_root}/metrics.csv" \
  --json "${evidence_root}/metrics.json" \
  --png "${evidence_root}/loss_curve.png" \
  > "${evidence_root}/metrics_extract.log" 2>&1

(
  cd "$(dirname "${training_root}")"
  find "$(basename "${training_root}")" -type f -print0 \
    | sort -z | xargs -0 sha256sum > "${evidence_root}/training_output.SHA256SUMS"
  sha256sum -c "${evidence_root}/training_output.SHA256SUMS" \
    > "${evidence_root}/training_output.verify.log"
)
printf '%s\n' \
  "Fresh ${steps}-step optimization and checkpoint materialization only; no convergence, task-success, held-out, robustness, safety, performance-advantage, or submission claim." \
  > "${evidence_root}/claim_boundary.txt"
terminal_status=PASS_TRAINING_COMPLETE
