#!/usr/bin/env bash
# Video2Motion container entrypoint.
set -euo pipefail

MJX=/opt/venv/mjx/bin/python

banner() {
  echo "─────────────────────────────────────────────────────────────"
  echo " Video2Motion  ·  human video → Unitree G1 policy  ·  AMD ROCm"
  echo "─────────────────────────────────────────────────────────────"
}

check_gpu() {
  echo "[check] ROCm devices"
  ls /dev/kfd /dev/dri >/dev/null 2>&1 || {
    echo "  !! /dev/kfd or /dev/dri missing."
    echo "     Run with: --device=/dev/kfd --device=/dev/dri --group-add video"
    return 1
  }
  $MJX -c "import jax; b=jax.default_backend(); print('  jax backend:', b, jax.devices()); \
           raise SystemExit(0 if b=='gpu' else 1)" || {
    echo "  !! JAX is not seeing the GPU. Everything will run on CPU and be unusably slow."
    return 1
  }
}

check_models() {
  local d=${V2M_BODY_MODELS:-/opt/models/body_models}
  if [ ! -f "$d/smpl/SMPL_NEUTRAL.pkl" ] && [ ! -f "$d/smplx/SMPLX_NEUTRAL.npz" ]; then
    cat <<'MSG'
  !! SMPL / SMPL-X body models not found.

     They are registration-gated and their licence forbids redistribution,
     so they cannot ship inside this image. Download them yourself and mount:

       -v /path/to/body_models:/opt/models/body_models:ro

     Expected layout:
       body_models/smpl/SMPL_{NEUTRAL,MALE,FEMALE}.pkl
       body_models/smplx/SMPLX_{NEUTRAL,MALE,FEMALE}.npz

     Step 1 (video → SMPL-X) will fail without them. Steps 2–4 still work on
     motions that are already retargeted.
MSG
  else
    echo "[check] body models found"
    ln -sfn "$d" /opt/GVHMR/inputs/checkpoints/body_models 2>/dev/null || true
  fi
}

banner
case "${1:-web}" in
  web)
    check_gpu || true
    check_models
    echo "[run] web UI on http://0.0.0.0:7860"
    cd /opt/video2motion/webapp && exec $MJX app.py
    ;;
  train)   shift; cd /opt/video2motion && exec $MJX train_track.py "$@" ;;
  eval)    shift; cd /opt/video2motion && exec $MJX eval_track.py "$@" ;;
  layer2)  shift; cd /opt/video2motion && exec $MJX layer2_numpy.py "$@" ;;
  deploy)  shift; cd /opt/video2motion && exec $MJX deploy_track.py "$@" ;;
  check)   check_gpu; check_models ;;
  bash|sh) exec /bin/bash ;;
  *)       exec "$@" ;;
esac
