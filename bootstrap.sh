#!/usr/bin/env bash
# One-shot launch for Clipster on an AMD Radeon (ROCm) instance.
# The platform clones this repo from the GitHub Repo URL in your template; then:
#   bash bootstrap.sh                  # provision everything (idempotent)
#   bash Clipster/scripts/services.sh start
#   bash Clipster/scripts/services.sh tunnel   # public URL for the web UI + API
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Self-heal: minimal images may ship without a CA bundle, so git/curl fail TLS.
# Detect and install ca-certificates before doing anything network-related.
if ! curl -fsS -o /dev/null https://github.com 2>/dev/null; then
  echo "[bootstrap] TLS to github.com failed — installing CA certificates"
  if command -v apt-get >/dev/null 2>&1; then
    export GIT_SSL_NO_VERIFY=1 DEBIAN_FRONTEND=noninteractive
    sudo apt-get update -y || true
    sudo apt-get install -y ca-certificates || true
    sudo update-ca-certificates || true
  else
    echo "[bootstrap] no apt-get; install ca-certificates manually" >&2
    exit 1
  fi
fi

# Some images have no compiled-in default CA path for git's curl — point it at
# the bundle explicitly (idempotent, no-op when already correct).
CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
if [[ -f "$CA_BUNDLE" ]] && ! curl -fsS -o /dev/null https://github.com 2>/dev/null; then
  git config --global http.sslCAInfo "$CA_BUNDLE"
  export GIT_SSL_CAINFO="$CA_BUNDLE" CURL_CA_BUNDLE="$CA_BUNDLE"
fi

git submodule update --init --recursive
exec Clipster/scripts/provision_radeon.sh "$@"
