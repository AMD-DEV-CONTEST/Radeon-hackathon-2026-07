#!/usr/bin/env bash
# Revalidate the immutable official-AMD G3 v13 project with process-isolated tests.
set -u -o pipefail
set -o noclobber

project=/workspace/mantis_rocm_bridge_project_v16_act_closedloop_g3_gripper_contract_003_20260726_v1
evidence=/workspace/mantis_g3_revalidate_isolated_20260726_v4
python_bin=/workspace/rdna/bin/python

g3_config="$project/configs/act-closedloop-g3-v1.json"
g3_core="$project/src/mantis_rocm_bridge/act_closedloop_g3.py"
g3_cli="$project/tools/run_genesis_act_closedloop_g3.py"
g3_test="$project/tests/test_act_closedloop_g3.py"
g3_doc="$project/docs/AMD_ACT_CLOSEDLOOP_G3_GATE.md"
g3_config_sha=9d320ed28f1565473fba0d665c574e2a17f5df5c2a3e6db8aaeb43af77589637
g3_core_sha=01341355e9d637609ced18c94b1813174ff6288f7e4bd489afce7d1a049b6a1d
g3_cli_sha=71d9b2176f51ffb54588413a44380a572476d141a511189ebac155d4b910cdd7
g3_test_sha=41e51adc6f706af35789f1ddca7074df882b445d1640b566c0e7b3ea035f4d14
g3_doc_sha=ce3f80cde55995aaf5cb59da446b7cbd847066dd2700bf7270bd5f8d771df7db

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
record_gate() {
  local name="$1"
  shift
  "$@" > "$evidence/$name.log" 2>&1
  local rc=$?
  printf '%s\n' "$rc" > "$evidence/$name.exit_code.txt"
  if test "$rc" -ne 0; then
    failures="${failures}${name}:rc=${rc};"
  fi
}

if test -e "$evidence"; then
  printf 'refusing existing evidence root: %s\n' "$evidence" >&2
  exit 80
fi
for required in \
  "$project" "$python_bin" \
  "$g3_config" "$g3_core" "$g3_cli" "$g3_test" "$g3_doc"; do
  if ! test -e "$required"; then
    printf 'missing required immutable input: %s\n' "$required" >&2
    exit 81
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
  printf 'official AMD GPU is not idle; refusing revalidation\n%s\n' \
    "$gpu_probe" >&2
  exit 82
fi

mkdir "$evidence" || exit 83
mkdir "$evidence/isolated_full" "$evidence/pycache" || exit 84
printf '%s\n' "$(utc_now)" > "$evidence/started_at_utc.txt"
printf '%q ' "$0" "$@" > "$evidence/command.txt"
printf '\n' >> "$evidence/command.txt"
hostname > "$evidence/hostname.txt"
df -h /workspace > "$evidence/disk_before.txt" 2>&1
printf '%s\n' "$gpu_probe" > "$evidence/gpu_before.txt"
find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  > "$evidence/kfd_before.txt" 2>&1
sha256sum "$g3_config" "$g3_core" "$g3_cli" "$g3_test" "$g3_doc" \
  > "$evidence/source_files.SHA256SUMS"

failures=""
for pair in \
  "$g3_config_sha:$g3_config" \
  "$g3_core_sha:$g3_core" \
  "$g3_cli_sha:$g3_cli" \
  "$g3_test_sha:$g3_test" \
  "$g3_doc_sha:$g3_doc"; do
  expected=${pair%%:*}
  file=${pair#*:}
  if ! hash_matches "$expected" "$file"; then
    failures="${failures}source_hash:${file};"
  fi
done

"$python_bin" - <<'PY' \
  > "$evidence/environment.json" \
  2> "$evidence/environment.stderr.log"
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
printf '%s\n' "$environment_rc" > "$evidence/environment.exit_code.txt"
if test "$environment_rc" -ne 0; then
  failures="${failures}environment:rc=${environment_rc};"
else
  identity_ok=$(
    "$python_bin" - "$evidence/environment.json" <<'PY'
import json
import sys
d = json.load(open(sys.argv[1]))
ok = (
    d.get("lerobot_version") == "0.4.4"
    and d.get("genesis_version") == "1.2.3"
    and bool(d.get("torch_hip_version"))
)
print("1" if ok else "0")
PY
  )
  if test "$identity_ok" != 1; then
    failures="${failures}runtime_identity;"
  fi
fi

if test -z "$failures"; then
  cd "$project" || exit 85
  export PYTHONPATH=src
  export PYTHONDONTWRITEBYTECODE=1
  export PYTHONPYCACHEPREFIX="$evidence/pycache"
  record_gate py_compile "$python_bin" -m py_compile \
    src/mantis_rocm_bridge/act_closedloop_g3.py \
    tools/run_genesis_act_closedloop_g3.py \
    tests/test_act_closedloop_g3.py
  record_gate validate_contracts "$python_bin" tools/validate_contracts.py
  record_gate unittest_focused "$python_bin" -m unittest discover \
    -s tests -p test_act_closedloop_g3.py -v
  if ! grep -Eq '^Ran 91 tests in ' "$evidence/unittest_focused.log"; then
    failures="${failures}unittest_focused_count;"
  fi

  find tests -maxdepth 1 -type f -name 'test_*.py' -print \
    | sort > "$evidence/isolated_full/test_files.txt"
  isolated_file_count=0
  isolated_total=0
  while IFS= read -r test_file; do
    test_name=${test_file##*/}
    test_stem=${test_name%.py}
    test_log="$evidence/isolated_full/${test_stem}.log"
    test_rc_file="$evidence/isolated_full/${test_stem}.exit_code.txt"
    "$python_bin" -m unittest discover -s tests -p "$test_name" -v \
      > "$test_log" 2>&1
    test_rc=$?
    printf '%s\n' "$test_rc" > "$test_rc_file"
    isolated_file_count=$((isolated_file_count + 1))
    if test "$test_rc" -ne 0; then
      failures="${failures}isolated_full:${test_name}:rc=${test_rc};"
    fi
    ran_line_count=$(grep -Ec '^Ran [0-9]+ tests? in ' "$test_log" || true)
    if test "$ran_line_count" -ne 1; then
      failures="${failures}isolated_count_line:${test_name};"
      continue
    fi
    test_count=$(
      awk '/^Ran [0-9]+ tests? in / {print $2}' "$test_log"
    )
    case "$test_count" in
      ''|*[!0-9]*)
        failures="${failures}isolated_count_value:${test_name};"
        ;;
      *)
        isolated_total=$((isolated_total + test_count))
        ;;
    esac
  done < "$evidence/isolated_full/test_files.txt"
  printf '%s\n' "$isolated_file_count" \
    > "$evidence/isolated_full/file_count.txt"
  printf '%s\n' "$isolated_total" \
    > "$evidence/isolated_full/total_tests.txt"
  if test "$isolated_file_count" -eq 0; then
    failures="${failures}isolated_no_test_files;"
  fi
  if test "$isolated_total" -ne 682; then
    failures="${failures}isolated_total:${isolated_total};"
  fi
else
  printf 'test validation not admitted after immutable-input preflight failure\n' \
    > "$evidence/validation_not_admitted.txt"
fi

gpu_after=$(
  /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids 2>&1
)
gpu_after_rc=$?
printf '%s\n' "$gpu_after" > "$evidence/gpu_after.txt"
printf '%s\n' "$gpu_after_rc" > "$evidence/gpu_after.exit_code.txt"
if test "$gpu_after_rc" -ne 0 \
  || ! grep -Eq 'GPU use \(%\): 0' <<< "$gpu_after" \
  || ! grep -Eq 'GPU Memory Allocated \(VRAM%\): 0' <<< "$gpu_after"; then
  failures="${failures}residual_gpu_activity;"
fi
find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  > "$evidence/kfd_after.txt" 2>&1
post_kfd_count=$(kfd_count)
printf '%s\n' "$post_kfd_count" > "$evidence/post_kfd_count.txt"
if test "$post_kfd_count" -ne 0; then
  failures="${failures}residual_kfd_process;"
fi
sha256sum "$g3_config" "$g3_core" "$g3_cli" "$g3_test" "$g3_doc" \
  > "$evidence/source_files_after.SHA256SUMS"
for pair in \
  "$g3_config_sha:$g3_config" \
  "$g3_core_sha:$g3_core" \
  "$g3_cli_sha:$g3_cli" \
  "$g3_test_sha:$g3_test" \
  "$g3_doc_sha:$g3_doc"; do
  expected=${pair%%:*}
  file=${pair#*:}
  if ! hash_matches "$expected" "$file"; then
    failures="${failures}post_test_source_hash:${file};"
  fi
done
df -h /workspace > "$evidence/disk_after.txt" 2>&1
printf '%s\n' "$(utc_now)" > "$evidence/finished_at_utc.txt"

if test -z "$failures"; then
  printf 'PASS\n' > "$evidence/status"
else
  printf 'FAIL\n' > "$evidence/status"
fi
printf '%s\n' "${failures:-none}" > "$evidence/failures.txt"

cd "$evidence" || exit 86
find . -type f \
  ! -name final_evidence.SHA256SUMS \
  ! -name final_evidence.verify.log \
  -print | sort | xargs sha256sum > final_evidence.SHA256SUMS
sha256sum -c final_evidence.SHA256SUMS > final_evidence.verify.log 2>&1
verify_rc=$?
printf '%s\n' "$verify_rc" \
  > /workspace/mantis_g3_revalidate_isolated_20260726_v4.verify.exit_code.txt

if test "$(tr -d '\n' < status)" = PASS && test "$verify_rc" -eq 0; then
  exit 0
fi
exit 1
