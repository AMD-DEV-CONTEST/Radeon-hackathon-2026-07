#!/usr/bin/env bash
# APT packages. Run once, needs sudo.
source "$(dirname "$0")/common.sh"

step "System packages"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    git wget curl ca-certificates build-essential cmake ninja-build \
    ffmpeg xvfb libegl1 libgl1 libglfw3 libosmesa6 \
    libeigen3-dev libyaml-dev
info "xvfb is required by GMR's retargeting script; ffmpeg by every render step."
