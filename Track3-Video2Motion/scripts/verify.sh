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
  OUT=$("$PYX" "$REPO/src/diagnostics/diag_perfect.py" "$MOTION" 2>/dev/null | sed -n '4,10p')
  echo "$OUT"
  if echo "$OUT" | grep -qE '0\.9[0-9]{3}|0\.[0-8]'; then
    bad "some tracking reward is below 1.0000"
  else
    ok "all six tracking rewards read 1.0000"
  fi
else
  info "skipped — no motion file yet (run scripts/run_pipeline.sh first)"
fi

step "Summary"
[ "$FAIL" -eq 0 ] && ok "environment looks good" || bad "$FAIL check(s) failed — see docs/TROUBLESHOOTING.md"
exit "$FAIL"
