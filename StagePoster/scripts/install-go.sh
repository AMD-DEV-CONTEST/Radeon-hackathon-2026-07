#!/usr/bin/env bash
set -Eeuo pipefail

GO_VERSION="${GO_VERSION:-1.25.0}"
ARCH="${GO_ARCH:-amd64}"
OS="${GO_OS:-linux}"

CURRENT=""
if command -v go >/dev/null 2>&1; then
  CURRENT="$(go version | awk '{print $3}' | sed 's/^go//')"
fi

if [[ "$CURRENT" == "$GO_VERSION" ]]; then
  echo "Go $GO_VERSION is already installed."
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ARCHIVE="go${GO_VERSION}.${OS}-${ARCH}.tar.gz"
URL="https://go.dev/dl/${ARCHIVE}"

echo "Downloading $URL"

curl -fL \
  "$URL" \
  -o "$TMP/$ARCHIVE"

rm -rf /usr/local/go

tar -C /usr/local \
  -xzf "$TMP/$ARCHIVE"

ln -sf /usr/local/go/bin/go /usr/local/bin/go
ln -sf /usr/local/go/bin/gofmt /usr/local/bin/gofmt

go version
