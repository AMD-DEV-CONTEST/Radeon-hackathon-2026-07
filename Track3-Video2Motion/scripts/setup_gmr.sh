#!/usr/bin/env bash
# venv 3 of 3 — retargeting.
source "$(dirname "$0")/common.sh"
need_cmd "$PY"; need_cmd git

mkdir -p "$THIRD"
step "Creating $VENVS/gmr"
"$PY" -m venv "$VENVS/gmr"
PIP="$VENVS/gmr/bin/pip"
$PIP install -q $PIP_OPTS --upgrade pip "setuptools<81"

[ -d "$THIRD/GMR" ] || git clone -q --depth 1 https://github.com/YanjieZe/GMR "$THIRD/GMR"
$PIP install -q $PIP_OPTS -e "$THIRD/GMR"

step "SMPL-X body models"
# scripts/gvhmr_to_robot.py hardcodes SMPLX_FOLDER = assets/body_models — there
# is no flag to point it elsewhere. smplx.create() then joins "smplx" onto it;
# if the folder is missing it falls through to inferring the model type from the
# basename and dies with the memorable "Unknown model type body, exiting!".
# The models are registration-gated and cannot be downloaded by a script, so
# reuse the copy GVHMR already needs.
#
# Link it unconditionally, even when the target does not exist yet. The models
# are registration-gated, so the documented order is: install, then fetch
# checkpoints. Creating the link only when the source already exists means the
# normal flow never gets one, and retargeting fails long afterwards. A dangling
# symlink states where the models belong and starts working the moment they
# land there.
SMPLX_SRC="$THIRD/GVHMR/inputs/checkpoints/body_models"
if [ -e "$THIRD/GMR/assets/body_models" ] || [ -L "$THIRD/GMR/assets/body_models" ]; then
  info "assets/body_models already present"
else
  ln -s "$SMPLX_SRC" "$THIRD/GMR/assets/body_models"
  info "linked assets/body_models -> $SMPLX_SRC"
fi
if [ ! -d "$THIRD/GMR/assets/body_models/smplx" ]; then
  info "NOTE: no SMPL-X models at $SMPLX_SRC/smplx yet."
  info "      Retargeting stays broken until GVHMR's checkpoints are in place;"
  info "      the link above picks them up automatically once they are."
fi

info "done: $VENVS/gmr"
