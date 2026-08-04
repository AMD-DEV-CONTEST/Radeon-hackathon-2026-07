#!/usr/bin/env bash
# venv 1 of 3 — training, simulation, web UI.
source "$(dirname "$0")/common.sh"
need_cmd "$PY"

step "Creating $VENVS/mjx"
"$PY" -m venv "$VENVS/mjx"
PIP="$VENVS/mjx/bin/pip"; PYX="$VENVS/mjx/bin/python"
$PIP install -q --upgrade pip

# JAX-ROCm goes first and is verified immediately. If this reports "cpu",
# nothing downstream is worth installing.
step "JAX-ROCm"
$PIP install -q --upgrade "jax[rocm7-local]"
BACKEND=$($PYX -c "import jax; print(jax.default_backend())")
info "jax backend: $BACKEND"
[ "$BACKEND" = "gpu" ] || die "JAX is not using the GPU. Check the ROCm install before continuing."
$PYX -c "import jax; print('  devices:', jax.devices())"

step "Simulation, RL and web stack"
# pygame is not optional: unitree_mujoco's bridge imports it unconditionally,
# even with the joystick disabled.
$PIP install -q \
    "mujoco==3.11.0" "mujoco-mjx==3.11.0" "brax==0.14.2" \
    mujoco_playground gradio matplotlib imageio pygame

info "done: $VENVS/mjx"
