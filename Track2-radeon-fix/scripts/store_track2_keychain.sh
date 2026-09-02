#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]] || ! command -v security >/dev/null 2>&1; then
  echo "This helper requires macOS Keychain (security)." >&2
  exit 1
fi

SERVICE="${TRACK2_KEYCHAIN_SERVICE:-hermes-track2-amd}"
read -r -s -p "AMD API token (input hidden): " TOKEN
printf '\n'

if [[ -z "${TOKEN}" ]]; then
  echo "Token was empty; nothing stored." >&2
  exit 1
fi

security add-generic-password \
  -a "${USER}" \
  -s "${SERVICE}" \
  -w "${TOKEN}" \
  -U >/dev/null
unset TOKEN

echo "Stored in macOS Keychain service: ${SERVICE}"
