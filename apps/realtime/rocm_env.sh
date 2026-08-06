#!/usr/bin/env bash
# BotverseX / ROCm environment for AMD Strix Halo (gfx1151)
#
# source this file BEFORE launching uvicorn / run_api.py / lerobot-train
# so that the PyTorch 2.10+rocm7.0 wheel can talk to the system ROCm 7.2.2
# HSA runtime. Without LD_PRELOAD the HSA code-object loader segfaults on
# the gfx1151 kernel bundle (Code Object V5 mismatch).
#
# Usage:
#   source /home/amd/Downloads/botversex/apps/realtime/rocm_env.sh
#   python run_api.py          # now points at apps/realtime/.venv
#
# After sourcing, `python` and `pip` resolve to the realtime virtualenv
# (which has torch 2.10+rocm7.0). The previously-active conda base env
# (torch 2.7.1+cu126) will be temporarily hidden – just `deactivate` to
# restore it.

export ROCM_PATH=/opt/rocm
export PATH=/opt/rocm/bin:${PATH}

# critical: use system-installed ROCm 7.2.2 HSA runtime, not the older
# copy that ships inside the torch-2.10+rocm7.0 wheel. gfx1151 kernels
# need the newer loader.
export LD_PRELOAD=/opt/rocm/lib/libhsa-runtime64.so.1

# gfx1151 is natively supported by ROCm 7.x – do NOT set
# HSA_OVERRIDE_GFX_VERSION; overriding causes immediate segfaults because
# the wheel ships gfx1151 kernels but no gfx1100 ones for torch internals.
unset HSA_OVERRIDE_GFX_VERSION

# Strix Halo APU exposes ~64 GB of unified memory. Nothing special to set –
# PyTorch's HIP allocator defaults are fine. (expandable_segments is not yet
# supported on HIP as of torch 2.10+rocm7.0.)

# Auto-activate the realtime virtualenv so `python` points at the torch
# 2.10+rocm7.0 interpreter, not whatever conda env the user was in.
_ROCM_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${_ROCM_ENV_DIR}/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "${_ROCM_ENV_DIR}/.venv/bin/activate"
fi
unset _ROCM_ENV_DIR

# Pin calibration IDs for teleop/record to the known-good pair.
# Without this, resolve_device_id() picks the most recently modified JSON,
# which can silently switch to another calibration set (e.g. my_*).
export BOTVERSEX_LEADER_DEVICE_ID=ethan_leader
export BOTVERSEX_FOLLOWER_DEVICE_ID=ethan_follower
