#!/usr/bin/env bash
# =============================================================================
# Path A · Make the xla_rocm plugin profiler-free  (see docs/ROCM_BUG_REPORT.md, Suggested Fix)
# =============================================================================
# ROOT CAUSE (see docs/ROCM_BUG_REPORT.md): the active xla_rocm plugin has a *dynamic NEEDED*
# dependency on librocprofiler-sdk.so.1. Because that lib exports
# `rocprofiler_configure`, the ROCm runtime AUTO-REGISTERS it as a profiling
# tool the instant the plugin loads — by design this ignores env vars
# (see github.com/ROCm/rocprofiler-register). The tool then GOTCHA-hooks every
# HIP kernel launch and non-deterministically segfaults in libhsa-runtime64.
#
# THE FIX THIS SCRIPT TESTS: strip that one NEEDED entry from the plugin .so
# with `patchelf --remove-needed`. No rocprofiler-sdk in the plugin -> no
# `rocprofiler_configure` gets registered -> no kernel-launch interception ->
# the race has no hook to crash in. Reversible: we keep a .bak of the plugin.
#
# WHY NOT just rename the system lib? It's a hard NEEDED dep of the plugin, so
# hiding the .so makes `import jax` fail at the dynamic-linker stage. We must
# remove the dependency edge from the plugin itself, not hide its target.
#
# This runs ONLY on the AMD instance (needs the GPU + the ROCm plugin). Local
# has no GPU. Safe: it backs up the plugin and restores on failure; the fix is
# a single reversible patchelf on one .so, no package removal.
#
# Usage (on the instance):
#   cd /workspace/Radeon-hackathon-2026-07/amd-physical-ai-locomotion
#   git pull
#   export MUJOCO_GL=osmesa
#   bash scripts/pathA_profiler_free.sh            # measure -> patch -> re-measure
#   REVERT=1 bash scripts/pathA_profiler_free.sh   # undo: restore plugin from .bak
#   TRIALS=30 bash scripts/pathA_profiler_free.sh  # more trials = tighter race stats
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

export MUJOCO_GL="${MUJOCO_GL:-osmesa}"
export PYTHONPATH="$PWD"

TRIALS="${TRIALS:-20}"          # stress runs per phase (race needs repetition)
STRESS_ROUNDS="${STRESS_ROUNDS:-8}"
export STRESS_ROUNDS
LIB="librocprofiler-sdk.so.1"   # the NEEDED entry we strip

hr() { echo "-----------------------------------------------------------------"; }

# --- Locate the active plugin .so -------------------------------------------
locate_plugin() {
  python3 - <<'PY'
import importlib, os, sys
for name in ("jax_plugins.xla_rocm7", "jax_plugins.xla_rocm60"):
    try:
        m = importlib.import_module(name)
    except Exception:
        continue
    d = os.path.dirname(m.__file__)
    for root, _dirs, files in os.walk(d):
        for f in files:
            if f.endswith("_plugin.so") or f == "xla_rocm_plugin.so":
                print(os.path.join(root, f)); sys.exit(0)
    # fallback: any .so under the plugin dir
    for root, _dirs, files in os.walk(d):
        for f in files:
            if f.endswith(".so"):
                print(os.path.join(root, f)); sys.exit(0)
sys.exit(1)
PY
}

PLUGIN_SO="$(locate_plugin || true)"
if [ -z "${PLUGIN_SO:-}" ] || [ ! -f "$PLUGIN_SO" ]; then
  echo "❌ Could not find the xla_rocm plugin .so. Is the ROCm JAX plugin installed?"
  echo "   Try: python3 -c 'import jax_plugins.xla_rocm7 as m; print(m.__file__)'"
  exit 2
fi
BAK="${PLUGIN_SO}.rocprof.bak"
echo "[pathA] active plugin: $PLUGIN_SO"

# --- REVERT mode: restore the original plugin and exit ----------------------
if [ "${REVERT:-0}" = "1" ]; then
  if [ -f "$BAK" ]; then
    cp -f "$BAK" "$PLUGIN_SO"
    echo "✅ Restored original plugin from $BAK"
    ldd "$PLUGIN_SO" 2>/dev/null | grep -i rocprof || echo "   (post-restore ldd shows rocprof deps as expected)"
  else
    echo "⚠️  No backup at $BAK — nothing to revert (plugin may already be original)."
  fi
  exit 0
fi

# --- Show the dependency we're targeting ------------------------------------
hr
echo "[pathA] current rocprofiler linkage of the plugin (ldd):"
if ldd "$PLUGIN_SO" 2>/dev/null | grep -i rocprof | sed 's/^/    /'; then
  :
else
  echo "    (none found by ldd — plugin may already be profiler-free)"
fi

# --- Trial runner: run the stress N times, count survivals ------------------
# A survival = exit 0 AND the STRESS_OK sentinel present. A segfault kills the
# process (exit 139 / no sentinel) => counted as a crash. Returns crashes via
# the global CRASHES; prints a per-phase summary.
run_trials() {
  local label="$1"; local n="$2"
  local crashes=0 survived=0 i rc out
  echo "[pathA] $label — running $n stress trials (ROUNDS=$STRESS_ROUNDS each)..."
  for i in $(seq 1 "$n"); do
    out="$(STRESS_TOKEN="t$i" python3 scripts/gpu_stress.py 2>&1)"
    rc=$?
    if [ $rc -eq 0 ] && printf '%s' "$out" | grep -q "STRESS_OK t$i"; then
      survived=$((survived+1)); printf '.'
    else
      crashes=$((crashes+1)); printf 'X'
      # keep the first crash's tail for the report
      if [ -z "${FIRST_CRASH_TAIL:-}" ]; then
        FIRST_CRASH_TAIL="$(printf '%s' "$out" | tail -4)"
      fi
    fi
  done
  echo ""
  echo "[pathA] $label result: survived=$survived crashed=$crashes  (rc of last: $rc)"
  CRASHES=$crashes
  SURVIVED=$survived
}

# --- Phase 1: baseline (current plugin, WITH rocprofiler) -------------------
hr
echo "[pathA] PHASE 1/3 — baseline with rocprofiler still linked"
echo "         (expect some/many X's — that IS the §9.4 race)"
run_trials "baseline" "$TRIALS"
BASE_CRASHES=$CRASHES; BASE_SURV=$SURVIVED

# --- Phase 2: patch the plugin (remove the NEEDED rocprofiler dep) ----------
hr
echo "[pathA] PHASE 2/3 — stripping '$LIB' NEEDED entry from the plugin"

if ! command -v patchelf >/dev/null 2>&1; then
  echo "    patchelf not found — attempting install..."
  pip install patchelf >/dev/null 2>&1 || pip3 install patchelf >/dev/null 2>&1 || true
fi
if ! command -v patchelf >/dev/null 2>&1; then
  # pip's patchelf ships a python entrypoint; try module invocation too
  if python3 -c "import patchelf" 2>/dev/null; then
    PATCHELF="python3 -m patchelf"
  else
    echo "❌ patchelf unavailable and pip install failed. Install it (apt-get install -y patchelf"
    echo "   or pip install patchelf) then re-run. No changes made."
    exit 3
  fi
else
  PATCHELF="patchelf"
fi

# Back up once (don't clobber an existing pristine backup on re-runs).
[ -f "$BAK" ] || cp -f "$PLUGIN_SO" "$BAK"
echo "    backup: $BAK"

# Which rocprof NEEDED entries are present? Strip every rocprofiler-* one, so
# the plugin can load with the target .so absent and registers no tool.
NEEDED_ROCPROF="$($PATCHELF --print-needed "$PLUGIN_SO" 2>/dev/null | grep -i rocprof || true)"
if [ -z "$NEEDED_ROCPROF" ]; then
  echo "    plugin has NO rocprofiler NEEDED entries already — nothing to strip."
else
  echo "    stripping these NEEDED entries:"
  printf '%s\n' "$NEEDED_ROCPROF" | sed 's/^/        /'
  while IFS= read -r dep; do
    [ -z "$dep" ] && continue
    $PATCHELF --remove-needed "$dep" "$PLUGIN_SO" \
      && echo "        removed: $dep" \
      || echo "        FAILED to remove: $dep"
  done <<< "$NEEDED_ROCPROF"
fi

echo "    post-patch ldd rocprof check:"
if ldd "$PLUGIN_SO" 2>/dev/null | grep -i rocprof | sed 's/^/        /'; then
  echo "    ⚠️  ldd STILL shows a rocprof dep (transitive via another lib?) — patch may be partial."
else
  echo "        none  <-- plugin is now profiler-free"
fi

# Sanity: can jax still import + see the GPU with the patched plugin?
hr
echo "[pathA] verifying JAX still initialises on GPU with the patched plugin..."
if python3 - <<'PY'
import sys
from src import config as C
C.set_headless_render_defaults()
import jax
ok = ("gpu" == jax.default_backend()) or any(
    ("Rocm" in type(d).__name__ or "Gpu" in type(d).__name__) for d in jax.devices()
)
print("    devices:", jax.devices())
sys.exit(0 if ok else 1)
PY
then
  echo "    ✅ JAX imports and sees the GPU with the patched plugin."
else
  echo "❌ JAX no longer initialises on GPU after patch — the plugin genuinely needs"
  echo "   rocprofiler symbols at runtime. Auto-reverting..."
  cp -f "$BAK" "$PLUGIN_SO"
  echo "   restored original plugin. Path A (patchelf) not viable on this build;"
  echo "   fall back to removing the rocprofiler-sdk package, or the runtime workaround."
  exit 4
fi

# --- Phase 3: re-measure with the profiler-free plugin ----------------------
hr
echo "[pathA] PHASE 3/3 — re-measuring with the profiler-free plugin"
FIRST_CRASH_TAIL=""   # reset so we capture a post-patch crash if any
run_trials "profiler-free" "$TRIALS"
FREE_CRASHES=$CRASHES; FREE_SURV=$SURVIVED

# --- Verdict ----------------------------------------------------------------
hr
echo "=================  PATH A VERDICT  ================="
echo "  baseline (with rocprofiler):   survived=$BASE_SURV  crashed=$BASE_CRASHES / $TRIALS"
echo "  profiler-free (patched):       survived=$FREE_SURV  crashed=$FREE_CRASHES / $TRIALS"
echo "----------------------------------------------------"
if [ "$FREE_CRASHES" -eq 0 ] && [ "$FREE_SURV" -eq "$TRIALS" ]; then
  if [ "$BASE_CRASHES" -gt 0 ]; then
    echo "✅ FIXED. Zero crashes after removing rocprofiler, vs $BASE_CRASHES before."
  else
    echo "✅ Zero crashes after patch. Baseline also had 0 (race didn't fire this run);"
    echo "   run again with a higher TRIALS to strengthen the before/after signal."
  fi
  echo ""
  echo "  The patched plugin PERSISTS (backup at $BAK). Now train for real:"
  echo "      SMOKE=1 bash scripts/01_train.sh        # confirm pipeline"
  echo "      bash scripts/01_train.sh                # full run"
  echo "  To undo:  REVERT=1 bash scripts/pathA_profiler_free.sh"
  echo ""
  echo "  If confirmed, record that this profiler-free approach works via"
  echo "  patchelf --remove-needed $LIB on $PLUGIN_SO."
  exit 0
elif [ "$FREE_CRASHES" -lt "$BASE_CRASHES" ]; then
  echo "◐ PARTIAL. Crashes dropped ($BASE_CRASHES -> $FREE_CRASHES) but not to zero."
  echo "   rocprofiler was likely a major but not sole factor, OR ldd still shows a"
  echo "   transitive rocprof dep (see phase 2). Investigate that, or try path B."
  [ -n "${FIRST_CRASH_TAIL:-}" ] && { echo "   last post-patch crash tail:"; printf '%s\n' "$FIRST_CRASH_TAIL" | sed 's/^/       /'; }
  exit 5
else
  echo "✗ NO IMPROVEMENT. Removing the rocprofiler NEEDED dep did not reduce crashes"
  echo "   (free=$FREE_CRASHES vs base=$BASE_CRASHES). Either the interception loads via a"
  echo "   different path (libamdhip64 pulling rocprofiler-register directly), or the"
  echo "   crash isn't rocprofiler after all. Next: try removing the rocprofiler-sdk package, then the runtime workaround."
  [ -n "${FIRST_CRASH_TAIL:-}" ] && { echo "   crash tail:"; printf '%s\n' "$FIRST_CRASH_TAIL" | sed 's/^/       /'; }
  echo ""
  echo "   (The patched plugin is left in place; REVERT=1 to restore if you prefer."
  echo "    It's harmless to keep — it just has one fewer NEEDED entry.)"
  exit 6
fi
