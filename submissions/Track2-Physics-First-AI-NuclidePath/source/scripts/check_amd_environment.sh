#!/usr/bin/env bash
set -u

pass=0
warn=0
fail=0
check() {
  local label="$1"; shift
  if "$@" >/tmp/amd_check.out 2>/tmp/amd_check.err; then
    printf '[PASS] %s\n' "$label"
    pass=$((pass + 1))
    return 0
  fi
  printf '[FAIL] %s\n' "$label"
  sed -n '1,3p' /tmp/amd_check.err
  fail=$((fail + 1))
  return 1
}

printf '%s\n' '=== AMD Hackathon Environment Check ==='
printf 'Host: '; hostname
printf 'Kernel: '; uname -sr
printf 'Python: '; python3 --version 2>&1 || true

if command -v lspci >/dev/null 2>&1 && lspci | grep -Eiq 'AMD|Advanced Micro Devices'; then
  printf '[PASS] AMD device visible on PCI\n'
  lspci | grep -Ei 'VGA|3D|Display|AMD|Advanced Micro Devices' || true
  pass=$((pass + 1))
else
  printf '[FAIL] AMD device visible on PCI\n'
  fail=$((fail + 1))
fi

if command -v rocminfo >/dev/null 2>&1; then
  check 'rocminfo available' rocminfo || true
  rocminfo 2>/dev/null | grep -E 'Name:|Marketing Name:|Agent [0-9]+' | head -20 || true
else
  printf '[FAIL] rocminfo available\n'
  fail=$((fail + 1))
fi

if command -v amd-smi >/dev/null 2>&1; then
  check 'amd-smi responds' amd-smi || true
elif command -v rocm-smi >/dev/null 2>&1; then
  check 'rocm-smi responds' rocm-smi || true
else
  printf '[WARN] amd-smi/rocm-smi not available\n'
  warn=$((warn + 1))
fi

for device in /dev/kfd /dev/dri; do
  if [ -e "$device" ]; then
    printf '[PASS] %s exists\n' "$device"
    pass=$((pass + 1))
  else
    printf '[FAIL] %s missing\n' "$device"
    fail=$((fail + 1))
  fi
done

if command -v hipcc >/dev/null 2>&1; then
  printf '[PASS] hipcc: '; hipcc --version | head -1
  pass=$((pass + 1))
else
  printf '[WARN] hipcc not available\n'
  warn=$((warn + 1))
fi

printf '\nSummary: %s passed, %s warnings, %s failed\n' "$pass" "$warn" "$fail"
if [ "$fail" -gt 0 ]; then
  exit 1
fi
