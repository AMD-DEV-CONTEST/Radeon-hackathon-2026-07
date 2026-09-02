#!/usr/bin/env bash
set -Eeuo pipefail

if command -v cloudflared >/dev/null 2>&1; then
  cloudflared --version
  exit 0
fi

INSTALL_MODE="${CLOUDFLARED_INSTALL_MODE:-binary}"

case "$INSTALL_MODE" in
  apt)
    apt-get update
    apt-get install -y curl ca-certificates gnupg

    mkdir -p --mode=0755 /usr/share/keyrings

    curl -fsSL \
      https://pkg.cloudflare.com/cloudflare-main.gpg \
      | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

    echo \
      "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
      > /etc/apt/sources.list.d/cloudflared.list

    apt-get update
    apt-get install -y cloudflared
    ;;

  binary)
    curl -fL \
      https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
      -o /usr/local/bin/cloudflared

    chmod +x /usr/local/bin/cloudflared
    ;;

  *)
    echo "Unsupported CLOUDFLARED_INSTALL_MODE=$INSTALL_MODE" >&2
    exit 1
    ;;
esac

cloudflared --version
