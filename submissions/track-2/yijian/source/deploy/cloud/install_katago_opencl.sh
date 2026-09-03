#!/usr/bin/env bash
set -euo pipefail

PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
SOURCE_ARCHIVE="${KATAGO_SOURCE_ARCHIVE:-$PERSIST_ROOT/KataGo-v1.16.5-build-source.tgz}"
SOURCE_DIR="${KATAGO_SOURCE_DIR:-$PERSIST_ROOT/katago-v1.16.5}"
BUILD_DIR="$SOURCE_DIR/build"
EXPECTED_ARCHIVE_SHA256="7ba3ef402d64af1ca6e5c0560675e39cfa05ae4275087147187e53ba040c9998"

command -v cmake >/dev/null
command -v ninja >/dev/null
command -v clinfo >/dev/null
clinfo -l | grep -F 'gfx1100' >/dev/null

if [[ ! -f "$SOURCE_DIR/cpp/CMakeLists.txt" ]]; then
  [[ -f "$SOURCE_ARCHIVE" ]] || {
    echo "Missing pinned source archive: $SOURCE_ARCHIVE" >&2
    exit 1
  }
  printf '%s  %s\n' "$EXPECTED_ARCHIVE_SHA256" "$SOURCE_ARCHIVE" | sha256sum --check -
  mkdir -p "$SOURCE_DIR"
  tar -xzf "$SOURCE_ARCHIVE" -C "$SOURCE_DIR"
fi

cmake -S "$SOURCE_DIR/cpp" -B "$BUILD_DIR" -G Ninja \
  -DUSE_BACKEND=OPENCL \
  -DNO_LIBZIP=1 \
  -DNO_GIT_REVISION=1 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --parallel "${KATAGO_BUILD_JOBS:-32}"
"$BUILD_DIR/katago" version

mkdir -p \
  "$PERSIST_ROOT/katago-models" \
  "$PERSIST_ROOT/katago-home/opencltuning" \
  "$PERSIST_ROOT/benchmarks" \
  "$PERSIST_ROOT/logs/katago-analysis"

echo "KataGo OpenCL build is ready: $BUILD_DIR/katago"

