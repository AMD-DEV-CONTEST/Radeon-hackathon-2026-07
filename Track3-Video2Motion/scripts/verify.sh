#!/usr/bin/env bash
# Checks that catch the failures we actually hit. Run after setup.sh.
source "$(dirname "$0")/common.sh"
PYX="${V2M_PY_MJX:-$VENVS/mjx/bin/python}"
FAIL=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL=$((FAIL+1)); }

step "1. Paths, GPU and scene file"
"$PYX" "$REPO/src/config.py" || FAIL=$((FAIL+1))

step "2. The three environments are isolated"
# numpy alone differs (2.5.x vs 1.26.4), so a single env is impossible.
"$PYX" -c "import torch" 2>/dev/null && bad "mjx venv must NOT have torch" || ok "mjx venv has no torch"
if [ -x "${V2M_PY_GVHMR:-$VENVS/gvhmr/bin/python}" ]; then
  "${V2M_PY_GVHMR:-$VENVS/gvhmr/bin/python}" -c "import jax" 2>/dev/null \
    && bad "gvhmr venv must NOT have jax" || ok "gvhmr venv has no jax"
fi

step "3. Reward function is correct (the important one)"
# Sets the state exactly to a reference frame; a perfect tracker must score
# 1.0000 on every term. Anything else means a frame, reference-point or unit
# convention is wrong, and no policy can score in that environment.
MOTION="${1:-$REPO/workdir/motions_bm/salute.npz}"
if [ -f "$MOTION" ]; then
  # Do not swallow stderr and do not let `set -e` abort here: this check
  # failing silently is worse than it failing loudly, and that is exactly what
  # happened when it was written as OUT=$(... 2>/dev/null).
  set +e
  RAW=$("$PYX" "$REPO/src/diagnostics/diag_perfect.py" "$MOTION" 2>&1)
  RC=$?
  set -e
  if [ "$RC" -ne 0 ]; then
    bad "the reward check could not run"
    echo "$RAW" | tail -6 | sed 's/^/      /'
  else
    echo "$RAW" | sed -n '4,10p'
    # Check the reward table only. Grepping the whole output matched the
    # per-body velocity numbers further down (0.0298 and friends) and reported
    # a failure while every reward was in fact 1.0000.
    OFF=$(echo "$RAW" | awk '
      /^ *[0-9]+ / && NF == 7 {
        for (i = 2; i <= 7; i++) if ($i != "1.0000") { bad++ }
      }
      END { print bad + 0 }')
    if [ "$OFF" -gt 0 ]; then
      bad "$OFF reward value(s) are not exactly 1.0000"
    else
      ok "all six tracking rewards read 1.0000"
    fi
  fi
else
  info "skipped — no motion file yet (run scripts/run_pipeline.sh first)"
fi

step "Summary"
[ "$FAIL" -eq 0 ] && ok "environment looks good" || bad "$FAIL check(s) failed — see docs/TROUBLESHOOTING.md"
exit "$FAIL"
