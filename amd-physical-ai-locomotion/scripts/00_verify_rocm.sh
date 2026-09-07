#!/usr/bin/env bash
# =============================================================================
# Phase 0 · ROCm toolchain verification (RUN THIS FIRST on the Radeon instance)
# =============================================================================
# This is the single most important, highest-risk step of the whole project.
# Do NOT run training until this script passes end-to-end. Its job is to prove
# that JAX sees the AMD GPU (RocmDevice) and that a minimal MJX rollout runs.
#
# Usage:
#   bash scripts/00_verify_rocm.sh
#
# If any check fails, the failure is itself valuable: it is the raw material
# for the upstream open-source contribution (Phase 4 / 10 points).
# =============================================================================
set -uo pipefail

pass=0; fail=0
ok()   { echo "  [ OK ]   $1"; pass=$((pass+1)); }
bad()  { echo "  [FAIL]   $1"; fail=$((fail+1)); }
info() { echo "  [info]   $1"; }
hr()   { echo "-----------------------------------------------------------------"; }

# Headless-render friendly defaults (from AMD's ROCm+JAX+MuJoCo blog).
# osmesa lets MuJoCo render without a display; the XLA flag avoids a
# command-buffer path that has been flaky on some ROCm builds.
export MUJOCO_GL="${MUJOCO_GL:-osmesa}"
export XLA_FLAGS="${XLA_FLAGS:---xla_gpu_enable_command_buffer=}"

echo "================================================================="
echo " AMD Radeon / ROCm toolchain verification"
echo " MUJOCO_GL=$MUJOCO_GL"
echo " XLA_FLAGS=$XLA_FLAGS"
echo "================================================================="

hr
echo "[1/6] rocm-smi — is a GPU visible to ROCm?"
if command -v rocm-smi >/dev/null 2>&1; then
  rocm-smi --showproductname 2>/dev/null | sed 's/^/         /' || rocm-smi 2>/dev/null | head -20 | sed 's/^/         /'
  ok "rocm-smi found a GPU"
else
  bad "rocm-smi not found — is ROCm installed / are you on a Radeon instance?"
fi

hr
echo "[2/6] Python & JAX import"
python3 -c "import sys; print('         python', sys.version.split()[0])" || bad "python3 missing"
if python3 -c "import jax" 2>/dev/null; then
  JAXVER=$(python3 -c "import jax; print(jax.__version__)")
  ok "jax imported (version $JAXVER)"
else
  bad "jax not importable — install the ROCm build (see README 'Install ROCm JAX')"
fi

hr
echo "[3/6] JAX backend & devices — MUST show RocmDevice / gpu"
python3 - <<'PY'
import sys
try:
    import jax
    backend = jax.default_backend()
    devs = jax.devices()
    print("         default_backend:", backend)
    print("         devices:", devs)
    names = " ".join(type(d).__name__ for d in devs)
    is_gpu = (backend == "gpu") or ("Rocm" in names) or ("Gpu" in names)
    sys.exit(0 if is_gpu else 3)
except Exception as e:
    print("         ERROR:", e)
    sys.exit(2)
PY
rc=$?
if   [ $rc -eq 0 ]; then ok "JAX is using the AMD GPU"
elif [ $rc -eq 3 ]; then bad "JAX imported but backend is CPU — ROCm JAX not active (wrong wheel or LD_LIBRARY_PATH). Try: unset LD_LIBRARY_PATH"
else                     bad "JAX device query failed"
fi

hr
echo "[4/6] A real GPU computation"
python3 - <<'PY'
import jax, jax.numpy as jnp
x = jnp.arange(1_000_000, dtype=jnp.float32)
y = float((x * x).sum())
print("         sum(x^2) =", y, "on", x.devices())
PY
[ $? -eq 0 ] && ok "GPU matmul/reduce ran" || bad "GPU computation failed"

hr
echo "[5/6] MuJoCo + MJX import"
python3 - <<'PY'
import mujoco
from mujoco import mjx
print("         mujoco", mujoco.__version__)
PY
[ $? -eq 0 ] && ok "mujoco & mjx import" || bad "mujoco/mjx import failed (pip install mujoco mujoco-mjx)"

hr
echo "[6/6] Minimal MJX rollout on GPU (single env, a few steps)"
python3 - <<'PY'
import jax, mujoco
from mujoco import mjx

XML = """
<mujoco>
  <option timestep="0.005"/>
  <worldbody>
    <geom type="plane" size="5 5 0.1"/>
    <body pos="0 0 1">
      <freejoint/>
      <geom type="sphere" size="0.1" mass="1"/>
    </body>
  </worldbody>
</mujoco>
"""
m = mujoco.MjModel.from_xml_string(XML)
mx = mjx.put_model(m)
dx = mjx.make_data(mx)

@jax.jit
def step(dx):
    return mjx.step(mx, dx)

for _ in range(50):
    dx = step(dx)
z = float(dx.qpos[2])
print(f"         sphere fell under gravity to z={z:.3f} (expect < 1.0)")
assert z < 1.0, "physics did not advance"
PY
[ $? -eq 0 ] && ok "MJX rollout ran on GPU" || bad "MJX rollout failed — capture this error for the upstream PR"

hr
echo "SUMMARY: $pass passed, $fail failed"
if [ $fail -eq 0 ]; then
  echo "✅ Toolchain verified. You may proceed to scripts/01_train.sh"
  exit 0
else
  echo "❌ Fix the failures above BEFORE training. Save the error output —"
  echo "   ROCm-specific failures are your Phase 4 upstream-PR material."
  exit 1
fi
