#!/usr/bin/env bash
set -euo pipefail

cd /workspace/radeonvla-reflex

command_name="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$command_name" in
  help)
    cat <<'EOF'
RadeonVLA-Reflex container commands:
  help         Show this message
  shell        Open a project shell
  check-amd    Validate ROCm, the visible Radeon GPU, Genesis, and the scene
  smoke        Run the short assets -> scene -> expert -> record -> validate smoke
  remote-full  Run data collection, SmolVLA training, evaluation, demos, and benchmark
  reflex-demo  Record normal, interrupt, and target-shift demos from CKPT

Arbitrary executable example:
  python -m radeonvla.scene --backend amdgpu --steps 50 --save-frames
EOF
    ;;
  shell)
    exec /bin/bash "$@"
    ;;
  check-amd)
    exec bash scripts/check_remote_amd.sh "$@"
    ;;
  smoke)
    exec bash scripts/run_pipeline_smoke.sh "$@"
    ;;
  remote-full)
    exec bash scripts/run_full_remote.sh "$@"
    ;;
  reflex-demo)
    exec bash scripts/run_reflex_demo.sh "$@"
    ;;
  *)
    exec "$command_name" "$@"
    ;;
esac
