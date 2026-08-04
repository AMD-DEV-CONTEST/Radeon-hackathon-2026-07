#!/usr/bin/env bash
# venv 2 of 3 — video to SMPL-X. This is the long one (pytorch3d is compiled).
source "$(dirname "$0")/common.sh"
need_cmd "$PY"; need_cmd git

mkdir -p "$THIRD"
step "Creating $VENVS/gvhmr"
"$PY" -m venv "$VENVS/gvhmr"
PIP="$VENVS/gvhmr/bin/pip"; PYX="$VENVS/gvhmr/bin/python"
# setuptools >= 81 removed pkg_resources, which lightning still imports.
$PIP install -q $PIP_OPTS --upgrade pip "setuptools<81"

step "PyTorch for ROCm"
# The AMD cloud image ships the ROCm wheels on disk (in / by default). They must
# all go in ONE command: torch pins the exact local triton build, so installing
# them one at a time fails with
#   No matching distribution found for triton==3.5.1+rocm7.2.1...
# No public index carries these exact builds, so local files are preferred and
# the index is only a fallback.
mapfile -t WHEELS < <(ls "$ROCM_WHEELS"/torch-*rocm*.whl \
                         "$ROCM_WHEELS"/torchvision-*rocm*.whl \
                         "$ROCM_WHEELS"/torchaudio-*rocm*.whl \
                         "$ROCM_WHEELS"/triton-*rocm*.whl 2>/dev/null)
if [ "${#WHEELS[@]}" -ge 4 ]; then
  info "using ${#WHEELS[@]} local ROCm wheels from $ROCM_WHEELS"
  for w in "${WHEELS[@]}"; do info "  $(basename "$w")"; done
  $PIP install -q "${WHEELS[@]}"
else
  info "no local ROCm wheels under $ROCM_WHEELS — falling back to $ROCM_INDEX"
  info "(set V2M_ROCM_WHEELS if yours are elsewhere)"
  $PIP install -q --index-url "$ROCM_INDEX" torch torchvision torchaudio pytorch-triton-rocm
fi
$PYX -c "import torch; print('  torch', torch.__version__, '| hip', torch.version.hip, '| gpu', torch.cuda.is_available())"

step "GVHMR"
[ -d "$THIRD/GVHMR" ] || git clone -q --depth 1 https://github.com/zju3dv/GVHMR "$THIRD/GVHMR"
$PIP install -q $PIP_OPTS -r "$THIRD/GVHMR/requirements.txt" || info "some requirements failed; continuing with explicit pins"
# wis3d and pycolmap are NOT optional — cv2_utils.py imports them at module level.
# ultralytics must be >= 8.4: 8.2.42 breaks on torch >= 2.6 because
# weights_only=True became the default and blocks the YOLO checkpoint load.
$PIP install -q $PIP_OPTS "numpy<2" yacs pycolmap wis3d "ultralytics>=8.4"

step "chumpy (needs patching)"
# chumpy aborts the whole batch if installed together with others, and its
# source uses APIs removed from Python 3.11 / NumPy 1.24.
$PIP install -q $PIP_OPTS --no-build-isolation chumpy || true
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
MAX_JOBS="${MAX_JOBS:-8}" FORCE_CUDA=0 $PIP install $PIP_OPTS --no-build-isolation -e "$THIRD/pytorch3d"

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
