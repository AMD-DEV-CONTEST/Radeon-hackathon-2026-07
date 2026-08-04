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
info "done: $VENVS/gmr"
