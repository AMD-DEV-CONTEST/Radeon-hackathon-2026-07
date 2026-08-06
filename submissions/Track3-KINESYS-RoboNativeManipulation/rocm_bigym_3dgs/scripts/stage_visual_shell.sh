#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SHELL_WALLS=${SHELL_WALLS:?set SHELL_WALLS to walls_fixed_kitchen.ply}
SHELL_FLOOR=${SHELL_FLOOR:?set SHELL_FLOOR to floor_perimeter.ply}
SHELL_CEILING=${SHELL_CEILING:?set SHELL_CEILING to ceiling_lights.ply}
SHELL_DIR=${SHELL_DIR:-${AMD_BIGYM_ROOT:-/workspace/amd-bigym-3dgs}/assets/dl3dv-kitchen-cutlery32}

for item in "$SHELL_WALLS" "$SHELL_FLOOR" "$SHELL_CEILING"; do
  test -f "$item" || { printf 'Missing shell input: %s\n' "$item" >&2; exit 2; }
done

mkdir -p "$SHELL_DIR"

copy_without_overwrite() {
  local source=$1
  local target=$2
  if test -e "$target"; then
    cmp -s "$source" "$target" || {
      printf 'Refusing to overwrite a different staged file: %s\n' "$target" >&2
      exit 2
    }
    return
  fi
  install -m 0644 "$source" "$target"
}

copy_without_overwrite "$SHELL_WALLS" "$SHELL_DIR/walls_fixed_kitchen.ply"
copy_without_overwrite "$SHELL_FLOOR" "$SHELL_DIR/floor_perimeter.ply"
copy_without_overwrite "$SHELL_CEILING" "$SHELL_DIR/ceiling_lights.ply"
copy_without_overwrite "$REPO_ROOT/configs/alignment-appearance-optimized.json" \
  "$SHELL_DIR/alignment-appearance-optimized.json"
copy_without_overwrite "$REPO_ROOT/configs/dl3dv-kitchen-cutlery32-profile.json" \
  "$SHELL_DIR/profile.json"

if command -v sha256sum >/dev/null; then
  sha256sum "$SHELL_DIR"/*.ply "$SHELL_DIR"/*.json
else
  shasum -a 256 "$SHELL_DIR"/*.ply "$SHELL_DIR"/*.json
fi
printf 'Visual shell staged at %s\n' "$SHELL_DIR"
