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
SMPLX_SRC="$THIRD/GVHMR/inputs/checkpoints/body_models"
if [ -e "$THIRD/GMR/assets/body_models" ]; then
  info "assets/body_models already present"
elif [ -d "$SMPLX_SRC/smplx" ]; then
  ln -s "$SMPLX_SRC" "$THIRD/GMR/assets/body_models"
  info "linked assets/body_models -> $SMPLX_SRC"
else
  info "WARNING: $SMPLX_SRC/smplx not found."
  info "Retargeting will fail until SMPL-X is in place. See scripts/setup_gvhmr.sh."
fi

info "done: $VENVS/gmr"
