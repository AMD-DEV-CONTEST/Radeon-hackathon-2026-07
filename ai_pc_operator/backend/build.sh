#!/usr/bin/env bash
# Build the Screen-AI native C core as a shared library.
# Usage: run from ai_pc_operator/backend/ or call bash build.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${SCRIPT_DIR}/native/screenai_core.c"
OUT_DIR="${SCRIPT_DIR}/native"

echo "============================================"
echo " Screen-AI Native Core Build"
echo "============================================"

if [[ "${OSTYPE:-}" == "msys" || "${OSTYPE:-}" == mingw* || "${OSTYPE:-}" == "cygwin" ]]; then
    EXT="dll"
elif [[ "${OSTYPE:-}" == darwin* ]]; then
    EXT="dylib"
else
    EXT="so"
fi

OUT_LIB="${OUT_DIR}/screenai_core.${EXT}"

if command -v gcc >/dev/null 2>&1; then
    CC="gcc"
elif command -v cc >/dev/null 2>&1; then
    CC="cc"
else
    echo "[ERROR] gcc/clang not found on PATH."
    echo "Install gcc or clang, then rerun this script."
    exit 1
fi

echo "[1/2] Compiling screenai_core.c -> screenai_core.${EXT} ..."
"${CC}" -O3 -Wall -Wextra -shared -fPIC -o "${OUT_LIB}" "${SRC}" -I"${OUT_DIR}"
echo "       OK: ${OUT_LIB}"

echo "[2/2] Done."
echo
echo "Native core built successfully."
echo "Library: ${OUT_LIB}"
