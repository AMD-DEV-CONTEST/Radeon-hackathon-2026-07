#!/usr/bin/env bash
# venv 2 of 3 — video to SMPL-X. This is the long one (pytorch3d is compiled).
source "$(dirname "$0")/common.sh"
need_cmd "$PY"; need_cmd git

mkdir -p "$THIRD"
step "Creating $VENVS/gvhmr"
"$PY" -m venv "$VENVS/gvhmr"
PIP="$VENVS/gvhmr/bin/pip"; PYX="$VENVS/gvhmr/bin/python"
# setuptools >= 81 removed pkg_resources, which lightning still imports.
$PIP install -q --upgrade pip "setuptools<81"

step "PyTorch for ROCm"
# All four wheels in ONE command: they pin a matching local
# pytorch-triton-rocm build, so installing them separately fails with
#   No matching distribution found for triton==...+rocm...
$PIP install -q --index-url "$ROCM_INDEX" torch torchvision torchaudio pytorch-triton-rocm
$PYX -c "import torch; print('  torch', torch.__version__, '| hip', torch.version.hip)"

step "GVHMR"
[ -d "$THIRD/GVHMR" ] || git clone -q --depth 1 https://github.com/zju3dv/GVHMR "$THIRD/GVHMR"
$PIP install -q -r "$THIRD/GVHMR/requirements.txt" || info "some requirements failed; continuing with explicit pins"
# wis3d and pycolmap are NOT optional — cv2_utils.py imports them at module level.
# ultralytics must be >= 8.4: 8.2.42 breaks on torch >= 2.6 because
# weights_only=True became the default and blocks the YOLO checkpoint load.
$PIP install -q "numpy<2" yacs pycolmap wis3d "ultralytics>=8.4"

step "chumpy (needs patching)"
# chumpy aborts the whole batch if installed together with others, and its
# source uses APIs removed from Python 3.11 / NumPy 1.24.
$PIP install -q --no-build-isolation chumpy || true
CH=$($PYX -c "import chumpy,os;print(os.path.dirname(chumpy.__file__))" 2>/dev/null || true)
if [ -n "$CH" ]; then
  sed -i 's/inspect.getargspec/inspect.getfullargspec/g' "$CH/ch.py" || true
  sed -i '/from numpy import bool, int, float, complex, object, unicode, str, nan, inf/d' "$CH/__init__.py" || true
  info "patched chumpy at $CH"
fi

step "pytorch3d (compiled from source — the slow step)"
# MAX_JOBS is mandatory. An unbounded build spawns 30+ cc1plus processes; on our
# machine it starved the system until sshd could no longer fork.
[ -d "$THIRD/pytorch3d" ] || git clone -q --depth 1 https://github.com/facebookresearch/pytorch3d "$THIRD/pytorch3d"
MAX_JOBS="${MAX_JOBS:-8}" FORCE_CUDA=0 $PIP install --no-build-isolation -e "$THIRD/pytorch3d"

cat <<'MSG'

  GVHMR model checkpoints are NOT downloaded automatically.
  Follow GVHMR's README to place them under:

      $THIRD/GVHMR/inputs/checkpoints/
        body_models/   ~1.0 GB   SMPL + SMPL-X  ← registration required
        hmr2/           2.6 GB
        vitpose/        2.4 GB
        yolo/           131 MB
        dpvo/            14 MB
        gvhmr/          156 MB

  SMPL and SMPL-X are registration-gated and their licence forbids
  redistribution, so they cannot be scripted. Everything else can be
  fetched with GVHMR's own download instructions.
MSG
