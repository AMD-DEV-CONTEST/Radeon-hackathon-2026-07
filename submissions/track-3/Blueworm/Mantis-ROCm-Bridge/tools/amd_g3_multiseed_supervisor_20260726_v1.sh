#!/usr/bin/env bash
# Execute the frozen official-AMD ACT G3 seeds 102-110 sequentially, then
# aggregate them with the already admitted immutable seed-101 episode.
set -u -o pipefail
set -o noclobber

project=/workspace/mantis_rocm_bridge_project_v16_act_closedloop_g3_gripper_contract_003_20260726_v1
deploy=/workspace/mantis_g3_revalidate_isolated_20260726_v4
seed101=/workspace/mantis_act_closedloop_g3_seed101_20260726_v6
stage=/workspace/mantis_act_closedloop_g3_multiseed10_supervisor_20260726_v1
batch=/workspace/mantis_act_closedloop_g3_multiseed10_20260726_v1
aggregate="$batch/aggregate"
python_bin=/workspace/rdna/bin/python
aggregate_tool=/workspace/aggregate_act_closedloop_g3_20260726_v1.py
checkpoint=/workspace/mantis_act_rocm_multiseed4_20260726_v2/checkpoints/060000
bowl=/workspace/robotwin_002_bowl_model3_stl_amd_20260725_v1
mantis_urdf=/workspace/mantis_fixed_base_local_20260725_v1/urdf/mantis_fixed_base.urdf

g3_config="$project/configs/act-closedloop-g3-v1.json"
task_config="$project/configs/task-pack-v1.json"
g3_core="$project/src/mantis_rocm_bridge/act_closedloop_g3.py"
g3_cli="$project/tools/run_genesis_act_closedloop_g3.py"
g3_test="$project/tests/test_act_closedloop_g3.py"
g3_config_sha=9d320ed28f1565473fba0d665c574e2a17f5df5c2a3e6db8aaeb43af77589637
g3_core_sha=01341355e9d637609ced18c94b1813174ff6288f7e4bd489afce7d1a049b6a1d
g3_cli_sha=71d9b2176f51ffb54588413a44380a572476d141a511189ebac155d4b910cdd7
g3_test_sha=41e51adc6f706af35789f1ddca7074df882b445d1640b566c0e7b3ea035f4d14

utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

kfd_count() {
  find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d \
    -print 2>/dev/null | wc -l | tr -d ' '
}

capture_kfd() {
  find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' 2>&1
}

hash_matches() {
  local expected="$1"
  local file="$2"
  test "$(sha256sum "$file" | awk '{print $1}')" = "$expected"
}

verify_frozen_sources() {
  hash_matches "$g3_config_sha" "$g3_config" \
    && hash_matches "$g3_core_sha" "$g3_core" \
    && hash_matches "$g3_cli_sha" "$g3_cli" \
    && hash_matches "$g3_test_sha" "$g3_test"
}

probe_gpu_idle() {
  local output="$1"
  /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids > "$output" 2>&1
  local probe_rc=$?
  test "$probe_rc" -eq 0 \
    && grep -Eq 'GPU use \(%\): 0' "$output" \
    && grep -Eq 'GPU Memory Allocated \(VRAM%\): 0' "$output" \
    && test "$(kfd_count)" -eq 0
}

publish_stage_manifest() {
  (
    cd "$stage" || exit 1
    find . -maxdepth 1 -type f \
      ! -name final_evidence.SHA256SUMS \
      ! -name final_evidence.verify.log \
      -printf '%f\n' | sort | xargs sha256sum > final_evidence.SHA256SUMS
    sha256sum -c final_evidence.SHA256SUMS > final_evidence.verify.log 2>&1
  )
}

record_block() {
  local reason="$1"
  if ! test -e "$stage/supervisor_block_reason.txt"; then
    printf '%s\n' "$reason" > "$stage/supervisor_block_reason.txt"
  fi
  if ! test -e "$stage/status"; then
    printf 'BLOCK\n' > "$stage/status"
  fi
}

if test -e "$stage" || test -e "$batch"; then
  printf 'refusing existing G3 batch stage or output directory\n' >&2
  exit 80
fi

for required in \
  "$project" "$deploy/status" "$deploy/final_evidence.SHA256SUMS" \
  "$seed101/status" "$seed101/seed101_batch_admission.status" \
  "$seed101/SHA256SUMS" "$seed101/final_evidence.SHA256SUMS" \
  "$python_bin" "$aggregate_tool" "$checkpoint/pretrained_model" \
  "$bowl/manifest.json" "$bowl/urdf/robotwin_002_bowl_model3.urdf" \
  "$mantis_urdf" "$g3_config" "$task_config" "$g3_core" "$g3_cli" "$g3_test"; do
  if ! test -e "$required"; then
    printf 'missing required G3 batch input: %s\n' "$required" >&2
    exit 81
  fi
done

mkdir "$stage" "$batch" || exit 82
printf '%s\n' "$(utc_now)" > "$stage/started_at_utc.txt"
cp "$0" "$stage/supervisor.sh"
cp "$aggregate_tool" "$stage/aggregate_tool.py"

if test "$(tr -d '\n' < "$deploy/status")" != PASS; then
  record_block "deployment_validation_not_pass"
fi
if ! (
  cd "$deploy" && sha256sum -c final_evidence.SHA256SUMS \
    > "$stage/deployment_manifest_verify.log" 2>&1
); then
  record_block "deployment_manifest_verification_failed"
fi
if test "$(tr -d '\n' < "$seed101/seed101_batch_admission.status")" != PASS; then
  record_block "seed101_batch_admission_not_pass"
fi
if ! (
  cd "$seed101" && sha256sum -c final_evidence.SHA256SUMS \
    > "$stage/seed101_final_manifest_verify.log" 2>&1
); then
  record_block "seed101_final_manifest_verification_failed"
fi
if ! verify_frozen_sources; then
  record_block "frozen_source_hash_mismatch"
fi
if ! probe_gpu_idle "$stage/gpu_before.txt"; then
  record_block "official_amd_gpu_not_idle_before_batch"
fi
capture_kfd > "$stage/kfd_before.txt"

"$python_bin" -m py_compile "$aggregate_tool" \
  > "$stage/aggregate_pycompile.log" 2>&1
printf '%s\n' "$?" > "$stage/aggregate_pycompile.exit_code.txt"
PYTHONPATH="$project/src" "$python_bin" "$aggregate_tool" --self-test \
  > "$stage/aggregate_self_test.log" 2>&1
aggregate_self_test_rc=$?
printf '%s\n' "$aggregate_self_test_rc" \
  > "$stage/aggregate_self_test.exit_code.txt"
if test "$aggregate_self_test_rc" -ne 0; then
  record_block "aggregate_self_test_failed"
fi

"$python_bin" - <<'PY' \
  > "$stage/environment.json" 2> "$stage/environment.stderr.log"
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
printf '%s\n' "$environment_rc" > "$stage/environment.exit_code.txt"
if test "$environment_rc" -ne 0; then
  record_block "environment_identity_capture_failed"
fi

sha256sum "$g3_config" "$task_config" "$g3_core" "$g3_cli" "$g3_test" \
  "$aggregate_tool" > "$stage/source_files.SHA256SUMS"
find "$checkpoint/pretrained_model" -type f -printf '%p\n' \
  | sort | xargs sha256sum > "$stage/checkpoint_files.SHA256SUMS"
sha256sum \
  "$bowl/manifest.json" \
  "$bowl/urdf/robotwin_002_bowl_model3.urdf" \
  "$mantis_urdf" > "$stage/asset_files.SHA256SUMS"

: > "$stage/gpu_during.txt"
: > "$stage/kfd_during.txt"
: > "$stage/episode_status.jsonl"

blocked=0
if test -e "$stage/supervisor_block_reason.txt"; then
  blocked=1
fi

for seed in 102 103 104 105 106 107 108 109 110; do
  if test "$blocked" -ne 0; then
    break
  fi
  out="$batch/seed${seed}"
  if test -e "$out"; then
    record_block "seed_${seed}_output_preexists"
    blocked=1
    break
  fi
  if ! verify_frozen_sources; then
    record_block "seed_${seed}_source_hash_drift"
    blocked=1
    break
  fi
  if ! probe_gpu_idle "$stage/seed${seed}.gpu_before.txt"; then
    record_block "seed_${seed}_gpu_not_idle_before_launch"
    blocked=1
    break
  fi
  capture_kfd > "$stage/seed${seed}.kfd_before.txt"
  printf '%s %s\n' "$(utc_now)" "$seed" >> "$stage/active_seed_history.txt"
  printf '%s\n' "$(utc_now)" > "$stage/seed${seed}.started_at_utc.txt"
  printf '%s\n' \
    "env HIP_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=src $python_bin tools/run_genesis_act_closedloop_g3.py $checkpoint --seed $seed --output-dir $out --bowl-asset-root $bowl --mantis-urdf $mantis_urdf --backend amdgpu" \
    > "$stage/seed${seed}.command.txt"

  (
    cd "$project" || exit 88
    env \
      HIP_VISIBLE_DEVICES=0 \
      HF_HUB_OFFLINE=1 \
      HF_DATASETS_OFFLINE=1 \
      TRANSFORMERS_OFFLINE=1 \
      PYTHONPATH=src \
      "$python_bin" tools/run_genesis_act_closedloop_g3.py "$checkpoint" \
        --seed "$seed" \
        --output-dir "$out" \
        --bowl-asset-root "$bowl" \
        --mantis-urdf "$mantis_urdf" \
        --backend amdgpu
  ) > "$stage/seed${seed}.supervisor.stdout.log" \
    2> "$stage/seed${seed}.supervisor.stderr.log" &
  child_pid=$!
  printf '%s\n' "$child_pid" > "$stage/seed${seed}.pid"

  while kill -0 "$child_pid" 2>/dev/null; do
    printf '%s seed=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ.%N)" "$seed" \
      >> "$stage/gpu_during.txt"
    /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids \
      >> "$stage/gpu_during.txt" 2>&1
    printf '%s seed=%s ' "$(date -u +%Y-%m-%dT%H:%M:%SZ.%N)" "$seed" \
      >> "$stage/kfd_during.txt"
    find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d \
      -printf '%f ' >> "$stage/kfd_during.txt" 2>/dev/null
    printf '\n' >> "$stage/kfd_during.txt"
    sleep 0.5
  done
  wait "$child_pid"
  child_rc=$?
  printf '%s\n' "$child_rc" > "$stage/seed${seed}.child.exit_code.txt"
  printf '%s\n' "$(utc_now)" > "$stage/seed${seed}.finished_at_utc.txt"
  /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids \
    > "$stage/seed${seed}.gpu_after.txt" 2>&1
  capture_kfd > "$stage/seed${seed}.kfd_after.txt"
  post_kfd=$(kfd_count)
  printf '%s\n' "$post_kfd" > "$stage/seed${seed}.post_kfd_count.txt"

  if ! test -d "$out"; then
    record_block "seed_${seed}_missing_output_directory"
    blocked=1
    break
  fi
  (
    cd "$out" && sha256sum -c SHA256SUMS \
      > "$stage/seed${seed}.cli_manifest_verify.log" 2>&1
  )
  manifest_rc=$?
  printf '%s\n' "$manifest_rc" \
    > "$stage/seed${seed}.cli_manifest_verify.exit_code.txt"
  if test "$manifest_rc" -ne 0; then
    record_block "seed_${seed}_cli_manifest_verification_failed"
    blocked=1
    break
  fi

  "$python_bin" - "$seed" "$child_rc" "$out" \
    "$stage/seed${seed}.audit.json" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

seed = int(sys.argv[1])
child_rc = int(sys.argv[2])
out = Path(sys.argv[3])
audit_path = Path(sys.argv[4])

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

receipt = json.load((out / "receipt.json").open())
runtime_identity = receipt.get("runtime_identity") or {}
identity_issues = (
    runtime_identity.get("identity_issues", [])
    if isinstance(runtime_identity, dict)
    else ["invalid_runtime_identity_structure"]
)
task_success = bool(receipt.get("task_success"))
expected_exit = 0 if task_success else 2
output_exit = int((out / "exit_code.txt").read_text().strip())
safety_count = int(receipt.get("safety_failure_count", 0))
audit = {
    "seed": receipt.get("seed"),
    "terminal": receipt.get("terminal") is True,
    "terminal_reason": receipt.get("terminal_reason"),
    "task_success": task_success,
    "infrastructure_failure": bool(receipt.get("infrastructure_failure", False)),
    "has_safety_failure": bool(receipt.get("has_safety_failure", safety_count > 0)),
    "safety_failure_count": safety_count,
    "safety_failure_reasons": receipt.get("safety_failure_reasons", []),
    "failure_taxonomy_label": receipt.get("failure_taxonomy_label"),
    "runtime_identity_issues": identity_issues,
    "policy_step_count": len(receipt.get("policy_steps", [])),
    "strict_evaluator_row_count": len(receipt.get("strict_evaluator_rows", [])),
    "child_exit_code": child_rc,
    "output_exit_code": output_exit,
    "expected_exit_code": expected_exit,
    "receipt_sha256": digest(out / "receipt.json"),
    "cli_manifest_sha256": digest(out / "SHA256SUMS"),
}
issues = []
if audit["seed"] != seed:
    issues.append("seed_identity_mismatch")
if not audit["terminal"]:
    issues.append("nonterminal_receipt")
if audit["infrastructure_failure"]:
    issues.append("infrastructure_failure")
if audit["terminal_reason"] == "runtime_error":
    issues.append("runtime_error")
if audit["runtime_identity_issues"]:
    issues.append("runtime_identity_drift")
if child_rc not in (0, 2) or output_exit != child_rc or child_rc != expected_exit:
    issues.append("exit_semantics_mismatch")
audit["blocking_issues"] = issues
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
fd = os.open(audit_path, flags, 0o644)
with os.fdopen(fd, "w") as stream:
    json.dump(audit, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write("\n")
raise SystemExit(0 if not issues else 1)
PY
  audit_rc=$?
  printf '%s\n' "$audit_rc" > "$stage/seed${seed}.audit.exit_code.txt"
  if test "$audit_rc" -ne 0; then
    record_block "seed_${seed}_semantic_audit_failed"
    blocked=1
    break
  fi
  if test "$post_kfd" -ne 0; then
    record_block "seed_${seed}_residual_kfd_process"
    blocked=1
    break
  fi
  printf '{"seed":%s,"child_exit_code":%s,"audit":"PASS"}\n' \
    "$seed" "$child_rc" >> "$stage/episode_status.jsonl"
done

printf '%s\n' "$(utc_now)" > "$stage/finished_at_utc.txt"
/opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids \
  > "$stage/gpu_after.txt" 2>&1
capture_kfd > "$stage/kfd_after.txt"

PYTHONPATH="$project/src" "$python_bin" "$aggregate_tool" \
  --gate "$g3_config" \
  --task-config "$task_config" \
  --seed101-dir "$seed101" \
  --batch-root "$batch" \
  --audit-root "$stage" \
  --output-dir "$aggregate" \
  --project "$project" \
  --checkpoint "$checkpoint" \
  --started-at-file "$stage/started_at_utc.txt" \
  --finished-at-file "$stage/finished_at_utc.txt" \
  --gpu-before "$stage/gpu_before.txt" \
  --gpu-during "$stage/gpu_during.txt" \
  --gpu-after "$stage/gpu_after.txt" \
  --kfd-before "$stage/kfd_before.txt" \
  --kfd-during "$stage/kfd_during.txt" \
  --kfd-after "$stage/kfd_after.txt" \
  > "$stage/aggregate.stdout.log" 2> "$stage/aggregate.stderr.log"
aggregate_rc=$?
printf '%s\n' "$aggregate_rc" > "$stage/aggregate.exit_code.txt"

if test -f "$aggregate/status"; then
  cp "$aggregate/status" "$stage/aggregate.status"
else
  record_block "aggregate_status_missing"
  aggregate_rc=3
fi

if test "$blocked" -ne 0 && test "$aggregate_rc" -ne 3; then
  record_block "blocked_batch_did_not_publish_block_aggregate"
  aggregate_rc=3
fi
publish_stage_manifest
exit "$aggregate_rc"
