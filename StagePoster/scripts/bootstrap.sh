#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND_ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
  pwd
)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "bootstrap.sh must run as root on the current AMD instance." >&2
  exit 1
fi

apt-get update

apt-get install -y \
  build-essential \
  ca-certificates \
  curl \
  git \
  gnupg \
  iproute2 \
  jq \
  lsof \
  procps \
  rsync \
  sqlite3 \
  unzip

if ! command -v rocminfo >/dev/null 2>&1; then
  echo "ROCm is not installed." >&2
  echo "Use an AMD ROCm base image before running this script." >&2
  exit 1
fi

"$BACKEND_ROOT/scripts/install-go.sh"
"$BACKEND_ROOT/scripts/install-comfyui.sh"
"$BACKEND_ROOT/scripts/install-vllm.sh"
"$BACKEND_ROOT/scripts/install-cloudflared.sh"

cd "$BACKEND_ROOT"

go mod download
go test ./...

mkdir -p \
  data \
  logs \
  run \
  storage/jobs \
  storage/assets \
  storage/posters

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo
echo "Bootstrap complete."
echo
echo "Next:"
echo "1. Review $BACKEND_ROOT/.env"
echo "2. Run scripts/download-models.sh"
echo "3. Confirm workflow JSON exists"
echo "4. Run scripts/start-all.sh"
echo "5. Run scripts/smoke-test.sh"
