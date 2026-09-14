#!/usr/bin/env bash

set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="${PACKAGE_DIR}/patches/0001-beaverbeaver-cores3.patch"

if [[ ! -s "${PATCH_FILE}" ]]; then
    echo "Missing or empty public patch" >&2
    exit 1
fi

for forbidden in \
    '172[.]19[.]' \
    '192[.]168[.]' \
    'dev-token' \
    'LIVEKIT_API_SECRET' \
    'LIVEKIT_API_KEY' \
    'BEGIN OPENSSH PRIVATE KEY' \
    'BEGIN PRIVATE KEY'; do
    if grep -E -i -n -- "${forbidden}" "${PACKAGE_DIR}"/README.md "${PATCH_FILE}"; then
        echo "Forbidden private value found: ${forbidden}" >&2
        exit 1
    fi
done

if grep -E -i -n -- 'bridge_server[.]py|background_capture_receiver[.]py' "${PATCH_FILE}"; then
    echo "Private or experimental Python source leaked into the firmware patch" >&2
    exit 1
fi

echo "Public firmware package verification passed."
