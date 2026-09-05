#!/usr/bin/env bash
set -uo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
failures=0

section() {
  printf '\n[%s]\n' "$1"
}

critical() {
  local label="$1"
  shift
  printf '%-30s' "$label"
  if "$@" >/tmp/amd-remote-check.out 2>&1; then
    echo "PASS"
    sed -n '1,14p' /tmp/amd-remote-check.out
  else
    echo "FAIL"
    sed -n '1,14p' /tmp/amd-remote-check.out
    failures=$((failures + 1))
  fi
}

optional() {
  local label="$1"
  shift
  printf '%-30s' "$label"
  if "$@" >/tmp/amd-remote-check.out 2>&1; then
    echo "PASS"
    sed -n '1,8p' /tmp/amd-remote-check.out
  else
    echo "INFO"
    sed -n '1,8p' /tmp/amd-remote-check.out
  fi
}

section "SSH identity and operating system"
id
hostname
uname -a
sed -n '1,12p' /etc/os-release 2>/dev/null || true

section "CPU"
lscpu 2>/dev/null | sed -n '1,24p' || true
if [[ -r /sys/fs/cgroup/cpu.max ]]; then
  echo "cgroup cpu.max: $(cat /sys/fs/cgroup/cpu.max)"
fi
if [[ -r /sys/fs/cgroup/cpuset.cpus.effective ]]; then
  echo "cgroup cpuset:  $(cat /sys/fs/cgroup/cpuset.cpus.effective)"
fi

section "Memory"
free -h 2>/dev/null || true
if [[ -r /sys/fs/cgroup/memory.max ]]; then
  memory_max="$(cat /sys/fs/cgroup/memory.max)"
  echo "cgroup memory.max: $memory_max"
  if [[ "$memory_max" =~ ^[0-9]+$ ]]; then
    awk -v bytes="$memory_max" 'BEGIN {printf "effective memory limit: %.2f GiB\n", bytes/1024/1024/1024}'
  fi
fi

section "Persistent workspace and disks"
critical "/workspace exists" test -d /workspace
df -h /workspace 2>/dev/null || df -h .
findmnt /workspace 2>/dev/null || mount | grep -F ' /workspace ' || true
critical "persistent root writable" bash -lc "mkdir -p '$ROOT' && test -w '$ROOT'"

section "AMD GPU and ROCm"
critical "/dev/kfd" test -e /dev/kfd
critical "/dev/dri" test -d /dev/dri
critical "amd-smi" amd-smi static
critical "rocminfo" bash -lc "rocminfo | grep -m 8 -E 'Marketing Name|Name:.*gfx|Wavefront Size'"

section "Base development tools"
critical "git" git --version
critical "curl" curl --version
critical "ssh client" ssh -V
critical "python3" python3 --version
optional "podman" podman --version

section "Coding agents"
optional "node" node --version
optional "npm" npm --version
optional "gh" gh --version
optional "codex" codex --version
optional "claude" claude --version

rm -f /tmp/amd-remote-check.out

if (( failures > 0 )); then
  echo
  echo "Remote environment verification failed: $failures critical check(s)."
  exit 1
fi

echo
echo "Remote environment critical checks passed."
echo "Coding-agent INFO results may be absent before installation."
