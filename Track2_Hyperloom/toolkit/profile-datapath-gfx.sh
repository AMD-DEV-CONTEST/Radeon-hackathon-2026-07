#!/bin/bash
# gfx1201 data-path profiler. rocprofv3 ONLY (Omniperf/rocprof-compute are CDNA-only, dead on RDNA4).
#
# INSTRUMENT NOTES (about the TOOL, so you don't lose turns to the same walls — not the answers):
#  * USE THE SDK-MATCHED rocprofv3, below. Do NOT use /usr/bin/rocprofv3 — version skew vs the ROCm-7.14 app
#    runtime SEGFAULTS. The SDK v1.3.1 binary works first try where /usr/bin v1.3.2 crashes.
#  * GL2C_EA_* memory counters read 0 on gfx1201 UNLESS the GPU perf level is 'stable'. NOT broken —
#    they are gated behind STABLE_STD (rocm-systems#5953). Enable them:
#      sudo amd-smi set --gpu <N> --perf-level STABLE_STD     # or sysfs: echo profile_standard > .../power_dpm_force_performance_level
#    VERIFIED on gfx1201 GPU0: GL2C_EA_RDREQ_sum 0 -> 1.1M, GRBM_COUNT 0 -> 3.0M under profile_standard.
#    Restore with '... --perf-level AUTO' when done. (TA_*, SQ_INSTS_VALU, FETCH_SIZE are gated the same way.)
#  * SQ_BUSY_CYCLES / GRBM_GUI_ACTIVE ratio is a near-CONSTANT across kernels = fixed topology multiplier,
#    NOT a per-kernel utilization signal. Don't classify compute/mem from it.
#  * ROBUST kernel COUNT immune to any rocprofv3 crash: `AMD_LOG_LEVEL=4 <app> 2>log` then grep launch lines
#    (also shows if HIP graphs are active: identical launch counts across token counts => one graph replay/tok).
#  * Trustworthy per-kernel TIME at high dispatch density: trace a FEW kernel types via
#    `--pmc ... --kernel-include-regex '<union>'`. Full --kernel-trace at 1000+ kernels inflates ~4-6x.
#
RP="${ROCPROFV3:-/opt/rocm/bin/rocprofv3}"
[ -x "$RP" ] || RP="$(command -v rocprofv3)"   # last resort; prefer the SDK binary above
# --- UNLOCK THE MEMORY COUNTERS: flip the compute GPU to STABLE_STD (profile_standard), restore on exit.
# Without this, GL2C_*/FETCH_SIZE/TA_*/SQ_INSTS_VALU read 0. Auto-detects the lowest-BDF amdgpu card
# (= HIP device 0, the compute GPU); the display GPU is left untouched. Override with PERF_GPU_NODE=.
GN="${PERF_GPU_NODE:-$(for c in /sys/class/drm/card*/device; do
    [ -f "$c/vendor" ] && grep -q 0x1002 "$c/vendor" 2>/dev/null && \
      echo "$(basename "$(readlink -f "$c")") $c"; done | sort | head -1 | awk '{print $2}')}"
if [ -n "$GN" ] && [ -e "$GN/power_dpm_force_performance_level" ]; then
    ORIG_PL="$(cat "$GN/power_dpm_force_performance_level" 2>/dev/null)"
    restore(){ [ -n "${ORIG_PL:-}" ] && echo "$ORIG_PL" | sudo tee "$GN/power_dpm_force_performance_level" >/dev/null 2>&1; echo ">> perf-level restored to '$ORIG_PL'"; }
    trap restore EXIT
    echo profile_standard | sudo tee "$GN/power_dpm_force_performance_level" >/dev/null 2>&1
    echo ">> perf-level -> profile_standard (STABLE_STD) on $GN (was '$ORIG_PL') — memory counters unlocked"
fi
# Full working counter set under STABLE_STD: memory (GL2C/FETCH_SIZE) + compute/occupancy (SQ/TA/GRBM).
HIP_VISIBLE_DEVICES=0 "$RP" --pmc \
    GL2C_EA_RDREQ_sum GL2C_EA_WRREQ_sum FETCH_SIZE GL2C_HIT GRBM_COUNT \
    SQ_WAVES SQ_BUSY_CYCLES SQ_INSTS_VALU TA_TA_BUSY GRBM_GUI_ACTIVE \
    --output-format csv -d ./prof-out -- "$@"
