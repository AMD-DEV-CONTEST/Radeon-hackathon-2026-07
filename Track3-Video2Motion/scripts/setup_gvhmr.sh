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
# GVHMR's requirements.txt targets CUDA 12.1 + Python 3.10 throughout:
#
#   --extra-index-url https://download.pytorch.org/whl/cu121
#   torch==2.3.0+cu121          would replace the ROCm build we just installed
#   torchvision==0.18.0+cu121
#   numpy==1.23.5               no cp312 wheel; building it on 3.12 dies with
#                               "module 'pkgutil' has no attribute 'ImpImporter'"
#   pytorch3d @ .../pytorch3d-0.7.6-cp310-cp310-...whl
#
# Any one of those aborts the whole file, silently leaving out lightning,
# hydra and the rest — which then surfaces much later as a runtime
# ModuleNotFoundError. Strip the platform-specific lines and install the rest;
# torch and pytorch3d are handled separately, above and below.
grep -vE '^(--(extra-)?index-url|torch|torchvision|torchaudio|pytorch3d|numpy)' \
    "$THIRD/GVHMR/requirements.txt" > /tmp/v2m_gvhmr_reqs.txt
info "installing $(grep -cve '^\s*$' -e '^#' /tmp/v2m_gvhmr_reqs.txt) requirements (platform-specific pins removed)"
$PIP install -q $PIP_OPTS -r /tmp/v2m_gvhmr_reqs.txt
# wis3d and pycolmap are NOT optional — cv2_utils.py imports them at module level.
# ultralytics must be >= 8.4: 8.2.42 breaks on torch >= 2.6 because
# weights_only=True became the default and blocks the YOLO checkpoint load.
$PIP install -q $PIP_OPTS "numpy<2" yacs pycolmap wis3d "ultralytics>=8.4"

# hmr4d/utils/body_model/body_model.py opens with `from turtle import forward`,
# an IDE autocomplete accident: `forward` is never used (the name is immediately
# shadowed by the class's own forward() method), but importing turtle pulls in
# tkinter, which headless containers do not ship. Drop the line rather than
# installing a GUI toolkit to satisfy a dead import.
sed -i '/^from turtle import forward$/d' \
    "$THIRD/GVHMR/hmr4d/utils/body_model/body_model.py"

# GVHMR itself. Installing its dependencies is not enough — tools/demo/demo.py
# imports `hmr4d`, which lives in this repo and needs to be on the path.
# --no-deps because we have already resolved the dependency set by hand; letting
# pip re-resolve here would drag the CUDA pins back in.
$PIP install -q --no-deps -e "$THIRD/GVHMR"

step "chumpy (needs patching)"
# chumpy aborts the whole batch if installed together with others, and its
# source uses APIs removed from Python 3.11 / NumPy 1.24.
$PIP install -q $PIP_OPTS --no-build-isolation chumpy || true
# Locate chumpy WITHOUT importing it. `import chumpy` is exactly what is broken
# here, so resolving the path that way leaves CH empty and silently skips the
# patch below — the failure then surfaces much later, mid-video, as
# "module 'inspect' has no attribute 'getargspec'". find_spec only looks the
# package up on sys.path; it does not execute it.
CH=$($PYX -c "
import importlib.util, os
s = importlib.util.find_spec('chumpy')
print(os.path.dirname(s.origin) if s and s.origin else '')
" 2>/dev/null || true)
if [ -n "$CH" ]; then
  # getargspec was removed in Python 3.11; chumpy calls it at import time,
  # from a decorator at module scope, so this is fatal rather than lazy.
  sed -i 's/inspect\.getargspec/inspect.getfullargspec/g' "$CH/ch.py" || true
  # np.bool / np.int / ... were removed in NumPy 1.24.
  sed -i '/from numpy import bool, int, float, complex, object, unicode, str, nan, inf/d' "$CH/__init__.py" || true
  rm -rf "$CH/__pycache__"
  info "patched chumpy at $CH"
  $PYX -c "import chumpy; print('  chumpy', chumpy.__version__, 'imports OK')"
else
  info "chumpy not found — SMPL loading will fail"; exit 1
fi

step "pytorch3d (compiled from source — the slow step)"
# MAX_JOBS is mandatory. An unbounded build spawns 30+ cc1plus processes; on our
# machine it starved the system until sshd could no longer fork.
[ -d "$THIRD/pytorch3d" ] || git clone -q --depth 1 https://github.com/facebookresearch/pytorch3d "$THIRD/pytorch3d"
MAX_JOBS="${MAX_JOBS:-8}" FORCE_CUDA=0 $PIP install $PIP_OPTS --no-build-isolation -e "$THIRD/pytorch3d"

step "Import check"
# Installing is not the same as importing. GVHMR fails at runtime otherwise,
# after you have already waited for the pytorch3d build.
$PYX -c "
import torch, pytorch3d, lightning, hydra, cv2, ultralytics, hmr4d
print('  torch', torch.__version__, '| gpu', torch.cuda.is_available())
print('  pytorch3d', pytorch3d.__version__, '| lightning', lightning.__version__)
"

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
