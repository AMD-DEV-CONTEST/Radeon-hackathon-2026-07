#!/usr/bin/env bash
# Reproduces every FAST (CPU, each under ~5 minutes) confirmation-eval-style
# result in this project end to end. Does NOT include the multi-hour
# attribution / generalization-sweep / FruitArchive search / GPU-backend
# commands -- those are listed individually, with their own runtime, in
# docs/REPRODUCIBILITY.md. Run from the repo root.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== [1/4] Core confirmation-eval (Genesis, CPU, ~2-4 min) ==="
uv run python franka_fruit_pick/codesign/confirmation_eval.py --n-trials 30

echo "=== [2/4] Cross-simulator confirmation-eval (MuJoCo, CPU, ~3-5 min) ==="
uv run python franka_fruit_pick/codesign/mujoco_repl/confirmation_eval_mj.py --n-trials 30

echo "=== [3/4] Per-finger contact-onset diagnostic (Genesis, CPU, ~2.5 min) ==="
uv run python franka_fruit_pick/codesign/finger_contact_batch_genesis.py --n-trials 60 --seed-base 2000

echo "=== [4/4] Contact-geometry mechanism test (Genesis, CPU, ~14 min) ==="
uv run python franka_fruit_pick/codesign/contact_geometry_eval.py --seed-base 11000

echo "=== Done. See docs/REPRODUCIBILITY.md for the remaining (multi-hour / GPU) results. ==="
