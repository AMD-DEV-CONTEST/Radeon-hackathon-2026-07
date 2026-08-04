#!/usr/bin/env bash
# venv 1 of 3 — training, simulation, web UI.
source "$(dirname "$0")/common.sh"
need_cmd "$PY"

step "Creating $VENVS/mjx"
"$PY" -m venv "$VENVS/mjx"
PIP="$VENVS/mjx/bin/pip"; PYX="$VENVS/mjx/bin/python"
$PIP install -q $PIP_OPTS --upgrade pip

# JAX-ROCm goes first and is verified immediately. If this reports "cpu",
# nothing downstream is worth installing.
step "JAX-ROCm"
$PIP install -q $PIP_OPTS --upgrade "jax[rocm7-local]"
BACKEND=$($PYX -c "import jax; print(jax.default_backend())")
info "jax backend: $BACKEND"
[ "$BACKEND" = "gpu" ] || die "JAX is not using the GPU. Check the ROCm install before continuing."
$PYX -c "import jax; print('  devices:', jax.devices())"

step "Simulation, RL and web stack"
# pygame is not optional: unitree_mujoco's bridge imports it unconditionally,
# even with the joystick disabled.
# NOTE: the distribution is called `playground`; `mujoco_playground` is only
# the import name and does not exist on PyPI.
$PIP install -q $PIP_OPTS \
    "mujoco==3.11.0" "mujoco-mjx==3.11.0" "brax==0.14.2" \
    "playground==0.2.0" gradio matplotlib imageio pygame

step "Robot meshes (mujoco_menagerie, ~2 GB)"
# The `playground` package ships the scene XML but not the meshes it references.
# Without this every model load dies with
#   Error opening file '../../../../../mujoco_menagerie/unitree_g1/assets/pelvis.STL'
$PYX -c "from mujoco_playground._src import mjx_env; mjx_env.ensure_menagerie_exists(); \
         print('  menagerie:', mjx_env.MENAGERIE_PATH)"

# Load the G1 for real — the scene file existing is not the same as it loading.
$PYX - <<'PYEOF'
import mujoco
from pathlib import Path
from mujoco_playground._src.locomotion.g1 import base, g1_constants as c
m = mujoco.MjModel.from_xml_string(
    Path(c.FEET_ONLY_FLAT_TERRAIN_XML).read_text(), base.get_assets())
print(f"  G1 model loads: {m.nq} dof, {m.nu} actuators")
PYEOF

info "done: $VENVS/mjx"
