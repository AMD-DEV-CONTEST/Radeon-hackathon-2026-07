#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-}"
EXPECTED_COMMIT="${2:-}"
ALLOW_DIRTY="${3:-}"

usage() {
  echo "Usage: $0 <version> <expected-source-commit> [--allow-dirty]" >&2
  exit 2
}

[[ $# -ge 2 && $# -le 3 ]] || usage
[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-[a-z0-9][a-z0-9.-]*$ ]] || {
  echo "Invalid release version: $VERSION" >&2
  exit 2
}
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Expected source commit must be a full lowercase Git SHA-1." >&2
  exit 2
}
[[ -z "$ALLOW_DIRTY" || "$ALLOW_DIRTY" == "--allow-dirty" ]] || usage

SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
[[ "$SOURCE_COMMIT" == "$EXPECTED_COMMIT" ]] || {
  echo "Source commit mismatch: expected $EXPECTED_COMMIT, found $SOURCE_COMMIT." >&2
  exit 1
}

SOURCE_STATE="clean"
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ]]; then
  if [[ "$ALLOW_DIRTY" != "--allow-dirty" ]]; then
    echo "Refusing to package a dirty repository." >&2
    exit 1
  fi
  SOURCE_STATE="dirty-explicitly-allowed-local-candidate"
fi

NAME="AlphaNoah-A1-Edge-Agent-${VERSION}-linux-x86_64"
STAGE="$ROOT/dist/$NAME"
ARCHIVE="$ROOT/dist/$NAME.tar.gz"
CHECKSUMS="$ROOT/dist/SHA256SUMS"

[[ -f "$ROOT/frontend/dist/index.html" ]] || {
  echo "Run npm --prefix frontend run build first." >&2
  exit 1
}

rm -rf "$STAGE"
rm -f "$ARCHIVE"
mkdir -p \
  "$STAGE/app/backend" \
  "$STAGE/app/frontend" \
  "$STAGE/config" \
  "$STAGE/scripts" \
  "$STAGE/data" \
  "$STAGE/logs"
cp -R "$ROOT/src" "$STAGE/app/backend/src"
find "$STAGE/app/backend/src" -type d -name "__pycache__" -prune -exec rm -rf {} +
cp -R "$ROOT/examples" "$STAGE/app/backend/examples"
cp "$ROOT/pyproject.toml" "$ROOT/requirements.txt" "$STAGE/app/backend/"
cp -R "$ROOT/frontend/dist/." "$STAGE/app/frontend/"
cp "$ROOT/config/alphanoah.env.example" "$ROOT/config/provider.example.env" "$STAGE/config/"
cp \
  "$ROOT/scripts/common.sh" \
  "$ROOT/scripts/install.sh" \
  "$ROOT/scripts/configure.sh" \
  "$ROOT/scripts/start.sh" \
  "$ROOT/scripts/stop.sh" \
  "$ROOT/scripts/restart.sh" \
  "$ROOT/scripts/status.sh" \
  "$ROOT/scripts/healthcheck.sh" \
  "$ROOT/scripts/reset_demo.sh" \
  "$ROOT/scripts/provider_probe.py" \
  "$STAGE/scripts/"
cp "$ROOT/README_LOCAL.md" "$ROOT/PROVIDER_SETUP.md" "$STAGE/"
cp "$ROOT/DEMO_GUIDE_LOCAL.md" "$STAGE/DEMO_GUIDE.md"
cp "$ROOT/SECURITY_AND_PRIVACY.md" "$STAGE/"
printf \
  "AlphaNoah A1 Edge Agent Local Edge Release\nRelease: %s\nSource Commit: %s\nPackaging Commit: %s\nSource State: %s\nOfficial validated reference platform: AMD Ryzen AI Max+ 395 / gfx1151\n" \
  "$VERSION" \
  "$SOURCE_COMMIT" \
  "$SOURCE_COMMIT" \
  "$SOURCE_STATE" \
  > "$STAGE/RELEASE_INFO.txt"
chmod 755 "$STAGE/scripts/"*.sh
chmod 700 "$STAGE/config" "$STAGE/data" "$STAGE/logs"

unsafe="$(find "$STAGE" -type f \( \
  -name "*.pyc" -o \
  -name "*.sqlite3" -o \
  -name "alphanoah.env" -o \
  -name "*.log" -o \
  -name "*.map" \
\) -print -quit)"
[[ -z "$unsafe" ]] || {
  echo "Unsafe package content detected: $unsafe" >&2
  exit 1
}

tar -C "$ROOT/dist" -czf "$ARCHIVE" "$NAME"
(
  cd "$ROOT/dist"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$CHECKSUMS")"
  sha256sum -c "$(basename "$CHECKSUMS")"
)
echo "$ARCHIVE"
