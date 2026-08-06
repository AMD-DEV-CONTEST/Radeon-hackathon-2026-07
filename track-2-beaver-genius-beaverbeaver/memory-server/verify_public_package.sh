#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PACKAGE_ROOT"

fail=0

for forbidden in .env .git .venv .runtime .private .codegraph .pytest_cache; do
    if [[ -e "$forbidden" ]]; then
        echo "ERROR: private or generated path is present: $forbidden" >&2
        fail=1
    fi
done

if find . -type f \( \
    -name '*.wav' -o -name '*.mp3' -o -name '*.m4a' -o \
    -name '*.jpg' -o -name '*.jpeg' -o -name '*.png' -o \
    -name '*.mp4' -o -name '*.sqlite' -o -name '*.sqlite3' -o \
    -name '*.db' -o -name '*.log' -o -name '*.pid' -o \
    -name '*.pem' -o -name '*.key' \
  \) -print -quit | grep -q .; then
    echo "ERROR: media, runtime data, or key material is present." >&2
    find . -type f \( \
      -name '*.wav' -o -name '*.mp3' -o -name '*.m4a' -o \
      -name '*.jpg' -o -name '*.jpeg' -o -name '*.png' -o \
      -name '*.mp4' -o -name '*.sqlite' -o -name '*.sqlite3' -o \
      -name '*.db' -o -name '*.log' -o -name '*.pid' -o \
      -name '*.pem' -o -name '*.key' \
    \) -print >&2
    fail=1
fi

scan_pattern='172\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|10\.[0-9]+\.[0-9]+\.[0-9]+|/home/(ivan|verachen)|oai2\.bwgdi\.com|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|Bearer [A-Za-z0-9_.=-]{12,}|sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{16}'
if rg -n --hidden -S "$scan_pattern" \
    --glob '!verify_public_package.sh' \
    --glob '!README.md' .; then
    echo "ERROR: a private address, developer path, or possible credential was found." >&2
    fail=1
fi

if ((fail)); then
    exit 1
fi

echo "Public package checks passed."
