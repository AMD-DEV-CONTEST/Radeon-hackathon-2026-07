#!/usr/bin/env bash
# Supervise the frozen official-AMD G3 seed-101 infrastructure/safety smoke.
set -u -o pipefail
set -o noclobber

project=/workspace/mantis_rocm_bridge_project_v14_act_closedloop_g3_gripper_tolerance_20260726_v1
deploy=/workspace/mantis_g3_revalidate_isolated_20260726_v2
stage=/workspace/mantis_act_closedloop_g3_seed101_supervisor_20260726_v4
out=/workspace/mantis_act_closedloop_g3_seed101_20260726_v4
python_bin=/workspace/rdna/bin/python
checkpoint=/workspace/mantis_act_rocm_multiseed4_20260726_v2/checkpoints/060000
bowl=/workspace/robotwin_002_bowl_model3_stl_amd_20260725_v1
mantis_urdf=/workspace/mantis_fixed_base_local_20260725_v1/urdf/mantis_fixed_base.urdf

g3_config="$project/configs/act-closedloop-g3-v1.json"
g3_core="$project/src/mantis_rocm_bridge/act_closedloop_g3.py"
g3_cli="$project/tools/run_genesis_act_closedloop_g3.py"
g3_test="$project/tests/test_act_closedloop_g3.py"
g3_config_sha=ad13c2fcf2b8e1865516c688de3865b8b8fcba2625a0a8ffb7e8e6b3e3e8ef71
g3_core_sha=6a36488ed4f3732eee4f815e6107f4977e910b6ce527cd003552c6f5fa3653ce
g3_cli_sha=71d9b2176f51ffb54588413a44380a572476d141a511189ebac155d4b910cdd7
g3_test_sha=f509d16a9bb90e65b76c3cde586f611f361521a8c7dd4efbfb4c720101fd085f

utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
kfd_count() {
  find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d \
    -print 2>/dev/null | wc -l | tr -d ' '
}
hash_matches() {
  local expected="$1"
  local file="$2"
  test "$(sha256sum "$file" | awk '{print $1}')" = "$expected"
}

if test -e "$stage" || test -e "$out"; then
  printf 'refusing existing seed-101 stage or output directory\n' >&2
  exit 80
fi
for required in \
  "$project" "$deploy/status" "$deploy/final_evidence.SHA256SUMS" \
  "$python_bin" "$checkpoint/pretrained_model" "$bowl/manifest.json" \
  "$bowl/urdf/robotwin_002_bowl_model3.urdf" "$mantis_urdf" \
  "$g3_config" "$g3_core" "$g3_cli" "$g3_test"; do
  if ! test -e "$required"; then
    printf 'missing required seed-101 input: %s\n' "$required" >&2
    exit 81
  fi
done
if test "$(tr -d '\n' < "$deploy/status")" != PASS; then
  printf 'deployment gate is not PASS\n' >&2
  exit 82
fi
deploy_verify=$(
  cd "$deploy" && sha256sum -c final_evidence.SHA256SUMS 2>&1
)
deploy_verify_rc=$?
if test "$deploy_verify_rc" -ne 0; then
  printf 'deployment evidence manifest failed verification\n%s\n' \
    "$deploy_verify" >&2
  exit 83
fi
for pair in \
  "$g3_config_sha:$g3_config" \
  "$g3_core_sha:$g3_core" \
  "$g3_cli_sha:$g3_cli" \
  "$g3_test_sha:$g3_test"; do
  expected=${pair%%:*}
  file=${pair#*:}
  if ! hash_matches "$expected" "$file"; then
    printf 'frozen G3 source hash mismatch: %s\n' "$file" >&2
    exit 84
  fi
done

gpu_probe=$(
  /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids 2>&1
)
gpu_probe_rc=$?
if test "$gpu_probe_rc" -ne 0 \
  || ! grep -Eq 'GPU use \(%\): 0' <<< "$gpu_probe" \
  || ! grep -Eq 'GPU Memory Allocated \(VRAM%\): 0' <<< "$gpu_probe" \
  || test "$(kfd_count)" -ne 0; then
  printf 'official AMD GPU is not idle; refusing seed-101 launch\n%s\n' \
    "$gpu_probe" >&2
  exit 85
fi

mkdir "$stage" || exit 86
printf '%s\n' "$(utc_now)" > "$stage/supervisor_started_at_utc.txt"
printf '%s\n' "$gpu_probe" > "$stage/supervisor_gpu_before.txt"
printf '%s\n' "$deploy_verify" > "$stage/deployment_manifest_verify.log"
printf '%s\n' "$deploy_verify_rc" > "$stage/deployment_manifest_verify.exit_code.txt"
find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  > "$stage/kfd_before.txt" 2>&1
cp "$0" "$stage/supervisor.sh"

"$python_bin" - <<'PY' \
  > "$stage/supervisor_environment.json" \
  2> "$stage/supervisor_environment.stderr.log"
import importlib.metadata
import json
import platform
import torch
print(json.dumps({
    "python_version": platform.python_version(),
    "torch_version": torch.__version__,
    "torch_hip_version": torch.version.hip,
    "torch_cuda_available": torch.cuda.is_available(),
    "torch_device_count": torch.cuda.device_count(),
    "torch_device_name_0": (
        torch.cuda.get_device_name(0) if torch.cuda.device_count() else None
    ),
    "lerobot_version": importlib.metadata.version("lerobot"),
    "genesis_version": importlib.metadata.version("genesis-world"),
}, indent=2, sort_keys=True))
PY
environment_rc=$?
printf '%s\n' "$environment_rc" > "$stage/supervisor_environment.exit_code.txt"
if test "$environment_rc" -ne 0; then
  printf 'environment identity capture failed\n' > "$stage/supervisor_failure.txt"
  exit 87
fi

sha256sum "$g3_config" "$g3_core" "$g3_cli" "$g3_test" \
  > "$stage/source_files.SHA256SUMS"
find "$checkpoint/pretrained_model" -maxdepth 1 -type f -printf '%p\n' \
  | sort | xargs sha256sum > "$stage/checkpoint_files.SHA256SUMS"
sha256sum \
  "$bowl/manifest.json" \
  "$bowl/urdf/robotwin_002_bowl_model3.urdf" \
  "$mantis_urdf" > "$stage/asset_files.SHA256SUMS"

printf '%s\n' \
  "env HIP_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=src $python_bin tools/run_genesis_act_closedloop_g3.py $checkpoint --seed 101 --output-dir $out --bowl-asset-root $bowl --mantis-urdf $mantis_urdf --backend amdgpu" \
  > "$stage/supervisor_command.txt"

cd "$project" || exit 88
env \
  HIP_VISIBLE_DEVICES=0 \
  HF_HUB_OFFLINE=1 \
  HF_DATASETS_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  PYTHONPATH=src \
  "$python_bin" tools/run_genesis_act_closedloop_g3.py "$checkpoint" \
    --seed 101 \
    --output-dir "$out" \
    --bowl-asset-root "$bowl" \
    --mantis-urdf "$mantis_urdf" \
    --backend amdgpu \
    > "$stage/supervisor.stdout.log" \
    2> "$stage/supervisor.stderr.log" &
child_pid=$!
printf '%s\n' "$child_pid" > "$stage/seed101.pid"
: > "$stage/supervisor_gpu_during.txt"
: > "$stage/kfd_during.txt"
while kill -0 "$child_pid" 2>/dev/null; do
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ.%N)" \
    >> "$stage/supervisor_gpu_during.txt"
  /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids \
    >> "$stage/supervisor_gpu_during.txt" 2>&1
  printf '%s ' "$(date -u +%Y-%m-%dT%H:%M:%SZ.%N)" \
    >> "$stage/kfd_during.txt"
  find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d -printf '%f ' \
    >> "$stage/kfd_during.txt" 2>/dev/null
  printf '\n' >> "$stage/kfd_during.txt"
  sleep 0.2
done
wait "$child_pid"
child_rc=$?
printf '%s\n' "$child_rc" > "$stage/seed101.exit_code.txt"
printf '%s\n' "$(utc_now)" > "$stage/supervisor_finished_at_utc.txt"
/opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids \
  > "$stage/supervisor_gpu_after.txt" 2>&1
find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  > "$stage/kfd_after.txt" 2>&1
post_kfd_count=$(kfd_count)
printf '%s\n' "$post_kfd_count" > "$stage/post_kfd_count.txt"

if ! test -d "$out"; then
  printf 'seed-101 CLI did not create its immutable output directory\n' \
    > "$stage/supervisor_failure.txt"
  cd "$stage" || exit 89
  find . -maxdepth 1 -type f \
    ! -name final_evidence.SHA256SUMS \
    ! -name final_evidence.verify.log \
    -printf '%f\n' | sort | xargs sha256sum > final_evidence.SHA256SUMS
  sha256sum -c final_evidence.SHA256SUMS > final_evidence.verify.log 2>&1
  exit 90
fi

for staged_file in "$stage"/*; do
  mv "$staged_file" "$out/"
done
rmdir "$stage"
cd "$out" || exit 91
sha256sum -c SHA256SUMS > cli_manifest_verify.log 2>&1
cli_manifest_rc=$?
printf '%s\n' "$cli_manifest_rc" > cli_manifest_verify.exit_code.txt

PYTHONPATH="$project/src" "$python_bin" - \
  "$out/receipt.json" "$g3_config" "$out/semantic_audit.json" \
  "$out/seed101_batch_admission.status" <<'PY'
import json
import sys
from pathlib import Path
from mantis_rocm_bridge.act_closedloop_g3 import smoke_seed_admission

receipt_path, gate_path, audit_path, status_path = map(Path, sys.argv[1:])
receipt = json.loads(receipt_path.read_text())
gate = json.loads(gate_path.read_text())
decision = smoke_seed_admission(receipt, gate)
policy_lines = sum(1 for line in Path("policy_steps.jsonl").read_text().splitlines() if line)
evaluator_lines = sum(
    1 for line in Path("strict_evaluator.jsonl").read_text().splitlines() if line
)
runtime_identity = receipt.get("runtime_identity") or {}
identity_issues = (
    runtime_identity.get("identity_issues", [])
    if isinstance(runtime_identity, dict) else ["invalid_runtime_identity_structure"]
)
infrastructure_failure = bool(receipt.get("infrastructure_failure", False))
admitted = (
    receipt.get("seed") == 101
    and bool(decision.get("admitted_to_batch"))
    and not infrastructure_failure
)
audit = {
    "seed": receipt.get("seed"),
    "terminal": bool(receipt.get("terminal")),
    "terminal_reason": receipt.get("terminal_reason"),
    "task_success": bool(receipt.get("task_success")),
    "infrastructure_failure": infrastructure_failure,
    "safety_failure_count": int(receipt.get("safety_failure_count", 0)),
    "safety_failure_reasons": receipt.get("safety_failure_reasons", []),
    "runtime_identity_issues": identity_issues,
    "policy_step_count": policy_lines,
    "strict_evaluator_row_count": evaluator_lines,
    "ordinary_safe_task_failure_is_admissible": True,
    "smoke_seed_admission": decision,
    "admitted_to_seed_102_110_batch": admitted,
}
audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
status_path.write_text("PASS\n" if admitted else "BLOCK\n")
PY
semantic_audit_rc=$?
printf '%s\n' "$semantic_audit_rc" > semantic_audit.exit_code.txt

if test "$post_kfd_count" -ne 0; then
  printf 'residual KFD process after seed-101 child exit\n' \
    > supervisor_infrastructure_failure.txt
  printf 'BLOCK\n' > seed101_batch_admission.status
fi
if test "$cli_manifest_rc" -ne 0 || test "$semantic_audit_rc" -ne 0; then
  printf 'BLOCK\n' > seed101_batch_admission.status
fi

find . -maxdepth 1 -type f \
  ! -name final_evidence.SHA256SUMS \
  ! -name final_evidence.verify.log \
  -printf '%f\n' | sort | xargs sha256sum > final_evidence.SHA256SUMS
sha256sum -c final_evidence.SHA256SUMS > final_evidence.verify.log 2>&1
final_verify_rc=$?
printf '%s\n' "$final_verify_rc" \
  > /workspace/mantis_act_closedloop_g3_seed101_20260726_v4.verify.exit_code.txt

if test "$final_verify_rc" -ne 0; then
  exit 92
fi
exit "$child_rc"
