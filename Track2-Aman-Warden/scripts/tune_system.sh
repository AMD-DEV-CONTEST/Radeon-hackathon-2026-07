#!/usr/bin/env bash
#
# Warden — Host kernel tuning for ROCm/Radeon bare-metal benchmark runs.
#
# Applies three host-level knobs that meaningfully affect GPU inference
# latency on AMD Cloud droplets (and inside any docker that inherits them):
#
#   1. vm.swappiness=10            discourage swap while GGUF is mmap'd
#   2. transparent_hugepage=always let the kernel back KG weights + KV
#                                  cache with 2MB THPs (cuts TLB misses)
#   3. nr_hugepages=<auto>         pre-reserve explicit 2MB hugepages
#                                  sized for the loaded GGUF (best-effort)
#   4. ulimit -n 65536              raise file-descriptor cap so the audit
#                                  log + RAG (ChromaDB) don't hit the 1024
#                                  default during long benchmarks
#   5. ulimit -l unlimited          allow mlocking weights in RAM if the
#                                  operator later flips WARDEN_LLM_USE_MLOCK=1
#
# Idempotent: re-running detects current state and only changes what's
# wrong. Requires root for the /proc and sysctl writes; the script prints
# what it would do (default) and only mutates the host with --apply.
#
# Usage:
#   sudo scripts/tune_system.sh            # dry-run: print planned changes
#   sudo scripts/tune_system.sh --apply    # actually apply them

set -u

APPLY=0
if [ "${1:-}" = "--apply" ]; then
    APPLY=1
fi

# --- helpers --------------------------------------------------------------

_planned=0
log_change() {
    _planned=$(( _planned + 1 ))
    echo "  - $1"
}

set_sysctl() {
    # set_sysctl <key> <value>
    local key="$1" val="$2"
    local current
    current="$(sysctl -n "$key" 2>/dev/null || echo '?')"
    if [ "$current" != "$val" ]; then
        log_change "$key: $current -> $val"
        if [ "$APPLY" -eq 1 ]; then
            sysctl -w "$key=$val" >/dev/null || true
        fi
    fi
}

set_thp() {
    # set_thp <value>   (always | never | madvise)
    local val="$1"
    local f="/sys/kernel/mm/transparent_hugepage/enabled"
    if [ -r "$f" ]; then
        local current
        current="$(awk -F'[][]' '{print $2}' "$f" 2>/dev/null || echo '?')"
        if [ "$current" != "$val" ]; then
            log_change "THP enabled: $current -> $val"
            if [ "$APPLY" -eq 1 ]; then
                echo "$val" > "$f" 2>/dev/null || true
            fi
        fi
    fi
}

set_hugepages() {
    # Auto-size 2MB hugepages to hold ~8GB (enough for a Q4_K_M 7B GGUF
    # even with Q8 KV cache). Each 2MB hugepage holds 2048 KB, so 8GB =
    # 4096 hugepages. This is best-effort: hugepages can only be reserved
    # if the host has 8GB of physically contiguous memory available.
    local target=4096
    local current
    current="$(cat /proc/sys/vm/nr_hugepages 2>/dev/null || echo 0)"
    if [ "$current" -lt "$target" ]; then
        log_change "nr_hugepages: $current -> $target (auto-sized for ~8GB GGUF)"
        if [ "$APPLY" -eq 1 ]; then
            sysctl -w "vm.nr_hugepages=$target" >/dev/null || true
        fi
    fi
}

raise_ulimit_n() {
    local target=65536
    local current
    current="$(ulimit -n 2>/dev/null || echo '?')"
    if [ "$current" != "unlimited" ] && [ "$current" != "?" ] && [ "$current" -lt "$target" ]; then
        log_change "ulimit -n (open files): $current -> $target"
        if [ "$APPLY" -eq 1 ]; then
            ulimit -n "$target" 2>/dev/null || true   # applies to current shell only
            # For the docker child to inherit, also write the hard limit
            # via /etc/security/limits.conf — but we don't edit that file
            # here (would require a process restart). The benchmark shell
            # gets the raised soft limit.
        fi
    fi
}

raise_ulimit_l() {
    local current
    current="$(ulimit -l 2>/dev/null || echo '?')"
    if [ "$current" != "unlimited" ] && [ "$current" != "?" ]; then
        log_change "ulimit -l (locked memory): $current -> unlimited"
        if [ "$APPLY" -eq 1 ]; then
            ulimit -l unlimited 2>/dev/null || true
        fi
    fi
}

# --- main -----------------------------------------------------------------

echo "===================================================="
echo "  Warden host kernel tuner (ROCm bare-metal)"
echo "===================================================="
if [ "$APPLY" -eq 0 ]; then
    echo "  Mode: DRY-RUN (no changes. Re-run with --apply.)"
else
    echo "  Mode: APPLYING (writing changes)"
fi
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "  WARN: not running as root; --apply writes to /proc and sysctl"
    echo "  will fail silently. Re-run with: sudo $0 $*"
    echo ""
fi

set_sysctl vm.swappiness 10
set_thp always
set_hugepages
raise_ulimit_n
raise_ulimit_l

echo ""
if [ "$_planned" -eq 0 ]; then
    echo "  All settings already at recommended values. No changes needed."
else
    echo "  $_planned setting(s) ${APPLY:+applied}${APPLY:-would be applied}."
fi
echo ""
echo "  These settings are inherited by any docker run on this host."
echo "  Inside docker without first running this on the host, only the"
echo "  ulimit changes apply (per-process); the sysctl/THP/hugepages"
echo "  require host-level access."
