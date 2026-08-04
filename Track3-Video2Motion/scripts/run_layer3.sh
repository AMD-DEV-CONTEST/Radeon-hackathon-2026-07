#!/usr/bin/env bash
# Layer 3 — Unitree's own simulator, own G1 model, over DDS.
# Needs scripts/setup_dds.sh.
source "$(dirname "$0")/common.sh"

NAME="${1:?usage: run_layer3.sh <name>}"
PY_MJX="${V2M_PY_MJX:-$VENVS/mjx/bin/python}"
WORK="${V2M_WORKDIR:-$REPO/workdir}"
UM="${V2M_UNITREE_MUJOCO:-$THIRD/unitree_mujoco}"
MOTION="$WORK/motions_bm/$NAME.npz"
[ -f "$MOTION" ] || die "motion not found: $MOTION"

STEPS=$("$PY_MJX" -c "import numpy as np; print(np.load('$MOTION')['joint_pos'].shape[0]-1)")
SECS=$(python3 -c "print(f'{$STEPS*0.02:.2f}')")
info "motion: $STEPS steps = ${SECS}s"

pkill -9 -f unitree_mujoco_headless 2>/dev/null || true
pkill -9 -f deploy_track 2>/dev/null || true
sleep 2

step "Simulator (headless, EGL)"
# Start from the motion's first frame: unitree's generic standing keyframe can
# differ by tens of degrees, and the policy's RSI perturbation is only ±0.1 rad.
( cd "$UM/simulate_python" && MUJOCO_GL=egl setsid nohup "$PY_MJX" \
    unitree_mujoco_headless.py --init_motion "$MOTION" \
    --out "$WORK/render/${NAME}_layer3.mp4" --seconds "$SECS" \
    > "$WORK/render/${NAME}_layer3_sim.log" 2>&1 & )
sleep 8

step "Controller (DDS, SDK-only observations)"
"$PY_MJX" "$REPO/src/deploy_track.py" \
    --policy "$WORK/deploy/track_$NAME.npz" --motion "$MOTION" \
    --steps "$STEPS" --domain_id 1 --interface lo

for _ in $(seq 1 30); do sleep 2; grep -q "written" "$WORK/render/${NAME}_layer3_sim.log" && break; done
pkill -9 -f unitree_mujoco_headless 2>/dev/null || true
info "video: $WORK/render/${NAME}_layer3.mp4"
