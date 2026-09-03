#!/usr/bin/env bash
# Isolated deployment and AMD-native validation for the frozen Mantis G3 code.
set -u -o pipefail
set -o noclobber

pkg=/workspace/mantis_g3_delta_testportable_20260726_v2.tar.gz
src=/workspace/mantis_rocm_bridge_project_v12_act_closedloop_g3_20260726_v1
dst=/workspace/mantis_rocm_bridge_project_v13_act_closedloop_g3_testportable_20260726_v1
evidence=/workspace/mantis_g3_deploy_validate_20260726_v2
python_bin=/workspace/rdna/bin/python
checkpoint=/workspace/mantis_act_rocm_multiseed4_20260726_v2/checkpoints/060000
bowl=/workspace/robotwin_002_bowl_model3_stl_amd_20260725_v1
bowl_manifest="$bowl/manifest.json"
bowl_urdf="$bowl/urdf/robotwin_002_bowl_model3.urdf"
mantis_urdf=/workspace/mantis_fixed_base_local_20260725_v1/urdf/mantis_fixed_base.urdf

pkg_sha=33e3a86eb0173279c1538e08f975835971b54e40e3686e8e38da941397b7e2b6
bowl_manifest_sha=ad895e3148b18909ebdcd0e7dcbb6c1f03c3d7def64ded5b6f991e38dc94ac5c
bowl_urdf_sha=d84ccce7fbd7484fd3195eebc386185855b38a2cafec5cbfec6eec122983fc01
mantis_urdf_sha=4db80a7659425b3419555cd28941c04ee5a6f8a44b4a4b3b28e46e3f4e2c5f57
g3_config_sha=be4e963ea84f891f69695c53b35751dc751518b1ed03bca15f3b979dd9901b15
g3_core_sha=d59ff012266868bb66dd109f4953b641da3ca860a01ef04fa4f3d2f8cb2d38f7
g3_cli_sha=71d9b2176f51ffb54588413a44380a572476d141a511189ebac155d4b910cdd7
g3_test_sha=fcc270010b114d10923a7a8be80423f843f7888b93a2253227c7768f11c0beef
g3_doc_sha=8cfdb1c89c2b2f5333766675680f866d64ed812abdda7a1443ee31e841241d51

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

if test -e "$dst" || test -e "$evidence"; then
  printf 'refusing existing destination or evidence root\n' >&2
  exit 80
fi

for required in \
  "$pkg" "$src" "$python_bin" "$checkpoint" \
  "$bowl_manifest" "$bowl_urdf" "$mantis_urdf"; do
  if ! test -e "$required"; then
    printf 'missing required input: %s\n' "$required" >&2
    exit 81
  fi
done

if test "$(kfd_count)" -ne 0; then
  printf 'refusing deployment validation while KFD processes are active\n' >&2
  exit 82
fi

if ! hash_matches "$pkg_sha" "$pkg" \
  || ! hash_matches "$bowl_manifest_sha" "$bowl_manifest" \
  || ! hash_matches "$bowl_urdf_sha" "$bowl_urdf" \
  || ! hash_matches "$mantis_urdf_sha" "$mantis_urdf"; then
  printf 'frozen package or asset hash mismatch\n' >&2
  exit 83
fi

mkdir "$evidence" || exit 84
printf '%s\n' "$(utc_now)" > "$evidence/started_at_utc.txt"
printf '%q ' "$0" "$@" > "$evidence/command.txt"
printf '\n' >> "$evidence/command.txt"
hostname > "$evidence/hostname.txt"
df -h /workspace > "$evidence/disk_before.txt" 2>&1
/opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids \
  > "$evidence/gpu_before.txt" 2>&1
find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  > "$evidence/kfd_before.txt" 2>&1
sha256sum "$pkg" "$bowl_manifest" "$bowl_urdf" "$mantis_urdf" \
  > "$evidence/input_files.SHA256SUMS"

"$python_bin" - <<'PY' > "$evidence/environment.json" 2> "$evidence/environment.stderr.log"
import importlib.metadata
import json
import platform
import torch

def version(name):
    return importlib.metadata.version(name)

print(json.dumps({
    "python_version": platform.python_version(),
    "torch_version": torch.__version__,
    "torch_hip_version": torch.version.hip,
    "torch_cuda_available": torch.cuda.is_available(),
    "torch_device_count": torch.cuda.device_count(),
    "torch_device_name_0": (
        torch.cuda.get_device_name(0) if torch.cuda.device_count() else None
    ),
    "lerobot_version": version("lerobot"),
    "genesis_version": version("genesis-world"),
}, indent=2, sort_keys=True))
PY
environment_rc=$?
printf '%s\n' "$environment_rc" > "$evidence/environment.exit_code.txt"

failures=""
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

cp -a "$src" "$dst" > "$evidence/copy.log" 2>&1
copy_rc=$?
printf '%s\n' "$copy_rc" > "$evidence/copy.exit_code.txt"
if test "$copy_rc" -ne 0; then
  failures="${failures}copy:rc=${copy_rc};"
fi

if test "$copy_rc" -eq 0; then
  tar -xzf "$pkg" -C "$dst" > "$evidence/extract.log" 2>&1
  extract_rc=$?
else
  extract_rc=90
  printf 'copy failed; extraction not attempted\n' > "$evidence/extract.log"
fi
printf '%s\n' "$extract_rc" > "$evidence/extract.exit_code.txt"
if test "$extract_rc" -ne 0; then
  failures="${failures}extract:rc=${extract_rc};"
fi

g3_config="$dst/configs/act-closedloop-g3-v1.json"
g3_core="$dst/src/mantis_rocm_bridge/act_closedloop_g3.py"
g3_cli="$dst/tools/run_genesis_act_closedloop_g3.py"
g3_test="$dst/tests/test_act_closedloop_g3.py"
g3_doc="$dst/docs/AMD_ACT_CLOSEDLOOP_G3_GATE.md"

if test "$copy_rc" -eq 0 && test "$extract_rc" -eq 0; then
  sha256sum "$g3_config" "$g3_core" "$g3_cli" "$g3_test" "$g3_doc" \
    > "$evidence/deployed_files.SHA256SUMS"
  for pair in \
    "$g3_config_sha:$g3_config" \
    "$g3_core_sha:$g3_core" \
    "$g3_cli_sha:$g3_cli" \
    "$g3_test_sha:$g3_test" \
    "$g3_doc_sha:$g3_doc"; do
    expected=${pair%%:*}
    file=${pair#*:}
    if ! hash_matches "$expected" "$file"; then
      failures="${failures}deployed_hash:${file};"
    fi
  done
else
  printf 'deployment incomplete\n' > "$evidence/deployed_files.SHA256SUMS"
fi

if test -z "$failures"; then
  cd "$dst" || exit 85
  export PYTHONPATH=src
  record_gate py_compile "$python_bin" -m py_compile \
    src/mantis_rocm_bridge/act_closedloop_g3.py \
    tools/run_genesis_act_closedloop_g3.py \
    tests/test_act_closedloop_g3.py
  record_gate validate_contracts "$python_bin" tools/validate_contracts.py
  record_gate unittest_focused "$python_bin" -m unittest discover \
    -s tests -p test_act_closedloop_g3.py -v
  record_gate unittest_full "$python_bin" -m unittest discover -s tests -v
  if ! grep -Eq 'Ran 91 tests' "$evidence/unittest_focused.log"; then
    failures="${failures}unittest_focused_count;"
  fi
  if ! grep -Eq 'Ran 682 tests' "$evidence/unittest_full.log"; then
    failures="${failures}unittest_full_count;"
  fi
else
  printf 'validation not admitted after deployment preflight failure\n' \
    > "$evidence/validation_not_admitted.txt"
fi

/opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids \
  > "$evidence/gpu_after.txt" 2>&1
find /sys/kernel/debug/kfd/proc -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  > "$evidence/kfd_after.txt" 2>&1
if test "$(kfd_count)" -ne 0; then
  failures="${failures}residual_kfd_process;"
fi
df -h /workspace > "$evidence/disk_after.txt" 2>&1
printf '%s\n' "$(utc_now)" > "$evidence/finished_at_utc.txt"

if test -z "$failures"; then
  printf 'PASS\n' > "$evidence/status"
else
  printf 'FAIL\n' > "$evidence/status"
fi
printf '%s\n' "${failures:-none}" > "$evidence/failures.txt"

cd "$evidence" || exit 86
find . -maxdepth 1 -type f \
  ! -name final_evidence.SHA256SUMS \
  ! -name final_evidence.verify.log \
  -printf '%f\n' | sort | xargs sha256sum > final_evidence.SHA256SUMS
sha256sum -c final_evidence.SHA256SUMS > final_evidence.verify.log 2>&1
verify_rc=$?
printf '%s\n' "$verify_rc" > /workspace/mantis_g3_deploy_validate_20260726_v2.verify.exit_code.txt

if test "$(tr -d '\n' < status)" = PASS && test "$verify_rc" -eq 0; then
  exit 0
fi
exit 1
