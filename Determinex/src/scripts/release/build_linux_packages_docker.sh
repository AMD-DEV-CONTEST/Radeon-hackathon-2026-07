#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
unset LD_LIBRARY_PATH
unset LIBRARY_PATH
unset CARGO_TARGET_DIR

# ── toolchain ────────────────────────────────────────────────────────────────
# Skipped when running from the pre-baked image (docker/release/linux-build.Dockerfile),
# which is the normal path.
#
# WHY THE GUARD EXISTS: apt + Node + rustup + the PyInstaller venv take ~24 minutes on this
# machine before any project code compiles. The first three attempts at this build each
# failed AFTER that point -- npm ci lockfile mismatch, a CRLF shebang, then
# `python: not found` -- so every one-line fix cost a fresh 24-minute wait to reach the next
# failure. Guarding the installs lets a retry start at `npm ci`.
if [ "${DETERMINEX_LINUX_TOOLCHAIN_PREBAKED:-0}" = "1" ] && command -v rustc >/dev/null 2>&1; then
  echo "[build_linux_packages] toolchain pre-baked; skipping install phase"
else
  apt-get update
  apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    file \
    libayatana-appindicator3-dev \
    librsvg2-dev \
    libssl-dev \
    libwebkit2gtk-4.1-dev \
    libxdo-dev \
    patchelf \
    pkg-config \
    python3 \
    python3-pip \
    python3-venv \
    python-is-python3 \
    libpython3.12 \
    wget \
    xz-utils \
    desktop-file-utils \
    fakeroot \
    rpm

  curl -fsSL https://deb.nodesource.com/setup_20.x -o /tmp/nodesource_setup.sh
  bash /tmp/nodesource_setup.sh
  apt-get install -y nodejs

  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup-init.sh
  sh /tmp/rustup-init.sh -y --profile minimal --default-toolchain stable
fi
export PATH="/root/.cargo/bin:$PATH"

# python-is-python3 matters more than it looks: frontend/package.json's `pretauri` hook
# shells out to `python`, Ubuntu ships only `python3`, and this build died at
# "sh: 1: python: not found" AFTER apt, Node, Rust, the venv and npm ci had all succeeded.
if ! command -v python >/dev/null 2>&1; then
  echo "[build_linux_packages] FATAL: no python on PATH; the pretauri hook needs it (apt install python-is-python3)" >&2
  exit 1
fi

export CARGO_TARGET_DIR=/tmp/determinex-linux-cargo-target
export npm_config_cache=/tmp/determinex-npm-cache
export TAURI_SIGNING_PRIVATE_KEY=""
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
SIDECAR_VENV="${SIDECAR_VENV:-/tmp/determinex-sidecar-build-venv}"

mkdir -p "$CARGO_TARGET_DIR" "$npm_config_cache"

node --version
npm --version
rustc --version
cargo --version

# Pre-baked in the image; created here only when running on a bare ubuntu.
if [ -x "$SIDECAR_VENV/bin/python" ]; then
  echo "[build_linux_packages] sidecar venv already present at $SIDECAR_VENV"
else
  python3 -m venv "$SIDECAR_VENV"
  "$SIDECAR_VENV/bin/python" -m pip install --upgrade pip wheel
  "$SIDECAR_VENV/bin/python" -m pip install \
    pyinstaller \
    litellm \
    rich \
    python-dotenv \
    tiktoken \
    numpy \
    psutil \
    pyyaml \
    anthropic \
    httpx \
    requests
fi

"$SIDECAR_VENV/bin/python" bundler/build_hive_sidecar.py --triple x86_64-unknown-linux-gnu

cd /workspace/frontend
# Strict install first, because a lockfile-exact tree is what makes a release build
# reproducible. Fall back to `npm install` when the lock cannot satisfy this platform.
#
# WHY THE FALLBACK EXISTS (2026-07-29): `npm ci` fails here with ~11 "Missing from lock
# file" errors. The committed lock is generated on Windows and resolves 787 packages; a
# Linux resolve wants 804, dropping 26 that Windows includes (abbrev, @npmcli/*,
# @isaacs/fs-minipass) and adding 43 (@emnapi/*, wasm32-wasi bindings). Neither lock is
# cross-platform complete, so npm ci can only ever succeed on the platform that generated
# it. The divergence is entirely in transitive OPTIONAL deps of dev tooling (cyclonedx-npm,
# oxc/rolldown wasm bindings) -- nothing the shipped app links against -- so falling back
# is materially safe here. The GitHub ubuntu-24.04 job runs bare `npm ci` and will hit the
# same wall until the lock is made cross-platform.
if ! npm ci --no-audit --no-fund; then
  echo "[build_linux_packages] npm ci could not satisfy the lock on linux; falling back to npm install" >&2
  npm install --no-audit --no-fund
fi
npm run tauri -- build --bundles appimage,deb,rpm

cd /workspace
python3 scripts/release/package_download_bundle.py \
  --installer-dir "$CARGO_TARGET_DIR/release/bundle" \
  --output-dir release_build_work/determinex-linux-download-bundles \
  --evidence-dir assurance/evidence/determinex_download_bundle_linux_local
