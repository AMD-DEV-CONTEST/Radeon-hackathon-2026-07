#!/usr/bin/env bash
# Materialize the immutable G3 gripper-readback-tolerance repair as project v14.
set -u -o pipefail
set -o noclobber

pkg=/workspace/mantis_g3_delta_gripper_tolerance_1e4_20260726_v4.tar.gz
src=/workspace/mantis_rocm_bridge_project_v14_act_closedloop_g3_gripper_tolerance_20260726_v1
dst=/workspace/mantis_rocm_bridge_project_v15_act_closedloop_g3_gripper_tolerance_1e4_20260726_v1
evidence=/workspace/mantis_g3_materialize_gripper_tolerance_20260726_v2

pkg_sha=7270494ecb7e5c609fae62b2743744d646393684d7777da1001fd987859895e2
base_config_sha=ad13c2fcf2b8e1865516c688de3865b8b8fcba2625a0a8ffb7e8e6b3e3e8ef71
base_core_sha=6a36488ed4f3732eee4f815e6107f4977e910b6ce527cd003552c6f5fa3653ce
base_cli_sha=71d9b2176f51ffb54588413a44380a572476d141a511189ebac155d4b910cdd7
base_test_sha=f509d16a9bb90e65b76c3cde586f611f361521a8c7dd4efbfb4c720101fd085f
base_doc_sha=f60e8ba7b571a8cf025ba419a51315fa8b43909faad2329d58b10e9c9991eb81
new_config_sha=3d128d511c03e499a44cab8ec7b004591ed37b6094d978f9bae39fb21e1c77e7
new_core_sha=5ae67642a2ce04a6c0ad2dc71444b27a9d8ec50173d6bebfff31c3a2d7830324
new_cli_sha=71d9b2176f51ffb54588413a44380a572476d141a511189ebac155d4b910cdd7
new_test_sha=7116c3b4433d958565e7b3eda39599b6acd6a35620fc926a77d7a3503fe44a00
new_doc_sha=77584c5f4c5f8660f14b1bf74e941e804825929c6c0db9a2eefeaebfbe73b49d

utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
hash_matches() {
  local expected="$1"
  local file="$2"
  test "$(sha256sum "$file" | awk '{print $1}')" = "$expected"
}
record_hash_gate() {
  local label="$1"
  local expected="$2"
  local file="$3"
  if ! hash_matches "$expected" "$file"; then
    failures="${failures}${label}:${file};"
  fi
}

if test -e "$dst" || test -e "$evidence"; then
  printf 'refusing existing destination or evidence root\n' >&2
  exit 80
fi
for required in "$pkg" "$src"; do
  if ! test -e "$required"; then
    printf 'missing required immutable input: %s\n' "$required" >&2
    exit 81
  fi
done

gpu_before=$(
  /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids 2>&1
)
gpu_before_rc=$?
if test "$gpu_before_rc" -ne 0 \
  || ! grep -Eq 'GPU use \(%\): 0' <<< "$gpu_before" \
  || ! grep -Eq 'GPU Memory Allocated \(VRAM%\): 0' <<< "$gpu_before" \
  || ! grep -Fq 'No KFD PIDs currently running' <<< "$gpu_before"; then
  printf 'official AMD GPU is not idle; refusing materialization\n%s\n' \
    "$gpu_before" >&2
  exit 82
fi

mkdir "$evidence" || exit 83
printf '%s\n' "$(utc_now)" > "$evidence/started_at_utc.txt"
printf '%q ' "$0" "$@" > "$evidence/command.txt"
printf '\n' >> "$evidence/command.txt"
printf '%s\n' "$gpu_before" > "$evidence/gpu_before.txt"
sha256sum "$pkg" > "$evidence/package.SHA256SUMS"

base_config="$src/configs/act-closedloop-g3-v1.json"
base_core="$src/src/mantis_rocm_bridge/act_closedloop_g3.py"
base_cli="$src/tools/run_genesis_act_closedloop_g3.py"
base_test="$src/tests/test_act_closedloop_g3.py"
base_doc="$src/docs/AMD_ACT_CLOSEDLOOP_G3_GATE.md"
sha256sum "$base_config" "$base_core" "$base_cli" "$base_test" "$base_doc" \
  > "$evidence/base_source.SHA256SUMS"

failures=""
record_hash_gate package "$pkg_sha" "$pkg"
record_hash_gate base_config "$base_config_sha" "$base_config"
record_hash_gate base_core "$base_core_sha" "$base_core"
record_hash_gate base_cli "$base_cli_sha" "$base_cli"
record_hash_gate base_test "$base_test_sha" "$base_test"
record_hash_gate base_doc "$base_doc_sha" "$base_doc"

if test -z "$failures"; then
  cp -a "$src" "$dst" > "$evidence/copy.log" 2>&1
  copy_rc=$?
  printf '%s\n' "$copy_rc" > "$evidence/copy.exit_code.txt"
  if test "$copy_rc" -ne 0; then
    failures="${failures}copy:rc=${copy_rc};"
  fi
else
  printf 'copy not admitted after immutable-input hash failure\n' \
    > "$evidence/copy.log"
  copy_rc=90
  printf '%s\n' "$copy_rc" > "$evidence/copy.exit_code.txt"
fi

if test "$copy_rc" -eq 0; then
  tar -xzf "$pkg" -C "$dst" > "$evidence/extract.log" 2>&1
  extract_rc=$?
else
  extract_rc=90
  printf 'extraction not admitted\n' > "$evidence/extract.log"
fi
printf '%s\n' "$extract_rc" > "$evidence/extract.exit_code.txt"
if test "$extract_rc" -ne 0; then
  failures="${failures}extract:rc=${extract_rc};"
fi

new_config="$dst/configs/act-closedloop-g3-v1.json"
new_core="$dst/src/mantis_rocm_bridge/act_closedloop_g3.py"
new_cli="$dst/tools/run_genesis_act_closedloop_g3.py"
new_test="$dst/tests/test_act_closedloop_g3.py"
new_doc="$dst/docs/AMD_ACT_CLOSEDLOOP_G3_GATE.md"
if test "$extract_rc" -eq 0; then
  sha256sum "$new_config" "$new_core" "$new_cli" "$new_test" "$new_doc" \
    > "$evidence/materialized_source.SHA256SUMS"
  record_hash_gate new_config "$new_config_sha" "$new_config"
  record_hash_gate new_core "$new_core_sha" "$new_core"
  record_hash_gate new_cli "$new_cli_sha" "$new_cli"
  record_hash_gate new_test "$new_test_sha" "$new_test"
  record_hash_gate new_doc "$new_doc_sha" "$new_doc"
else
  printf 'materialized source unavailable\n' \
    > "$evidence/materialized_source.SHA256SUMS"
fi

gpu_after=$(
  /opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids 2>&1
)
gpu_after_rc=$?
printf '%s\n' "$gpu_after" > "$evidence/gpu_after.txt"
if test "$gpu_after_rc" -ne 0 \
  || ! grep -Eq 'GPU use \(%\): 0' <<< "$gpu_after" \
  || ! grep -Eq 'GPU Memory Allocated \(VRAM%\): 0' <<< "$gpu_after" \
  || ! grep -Fq 'No KFD PIDs currently running' <<< "$gpu_after"; then
  failures="${failures}residual_gpu_activity;"
fi
printf '%s\n' "$(utc_now)" > "$evidence/finished_at_utc.txt"
if test -z "$failures"; then
  printf 'PASS\n' > "$evidence/status"
else
  printf 'FAIL\n' > "$evidence/status"
fi
printf '%s\n' "${failures:-none}" > "$evidence/failures.txt"

cd "$evidence" || exit 84
find . -type f \
  ! -name final_evidence.SHA256SUMS \
  ! -name final_evidence.verify.log \
  -print | sort | xargs sha256sum > final_evidence.SHA256SUMS
sha256sum -c final_evidence.SHA256SUMS > final_evidence.verify.log 2>&1
verify_rc=$?
printf '%s\n' "$verify_rc" \
  > /workspace/mantis_g3_materialize_gripper_tolerance_20260726_v2.verify.exit_code.txt
if test "$(tr -d '\n' < status)" = PASS && test "$verify_rc" -eq 0; then
  exit 0
fi
exit 1
