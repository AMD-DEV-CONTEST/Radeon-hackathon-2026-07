#!/usr/bin/env bash

set -euo pipefail

UPSTREAM_URL="https://github.com/78/xiaozhi-esp32.git"
UPSTREAM_COMMIT="417f52d7597b85f3dfc6f5283bdc66df34fbd5fe"
PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="${PACKAGE_DIR}/patches/0001-beaverbeaver-cores3.patch"
TARGET_DIR="${1:-${PACKAGE_DIR}/worktree}"

if [[ -e "${TARGET_DIR}" ]]; then
    echo "Refusing to overwrite existing target: ${TARGET_DIR}" >&2
    exit 2
fi

if [[ ! -f "${PATCH_FILE}" ]]; then
    echo "Patch is missing: ${PATCH_FILE}" >&2
    exit 2
fi

git clone "${UPSTREAM_URL}" "${TARGET_DIR}"
git -C "${TARGET_DIR}" checkout --detach "${UPSTREAM_COMMIT}"
git -C "${TARGET_DIR}" apply --check "${PATCH_FILE}"
git -C "${TARGET_DIR}" apply "${PATCH_FILE}"

echo "BeaverBeaver CoreS3 source prepared at: ${TARGET_DIR}"
echo "Configure the placeholder URLs/token before building."
