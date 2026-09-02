#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/scripts/lib/env.sh"

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --env) shift; [[ $# -gt 0 ]] || { echo "--env requires a path" >&2; exit 2; }; OPENALPHA_ENV_FILE="$1" ;;
    *) echo "Usage: $0 [--env FILE] [--dry-run]" >&2; exit 2 ;;
  esac
  shift
done
export OPENALPHA_ENV_FILE
openalpha_load_env "$ROOT_DIR" server required

: "${LLAMA_REPOSITORY:=https://github.com/ROCm/llama.cpp.git}"
: "${LLAMA_COMMIT:=1b99711a5f2582ec99686eb7958844749c223cf5}"
: "${LLAMA_ARCHIVE_URL:=https://codeload.github.com/ROCm/llama.cpp/tar.gz/$LLAMA_COMMIT}"
: "${LLAMA_ARCHIVE_SHA256:=65536629d57a7b7f9ec81a323311dd497e09a5d8b981225c6c56feda63cefde4}"
: "${LOCAL_LLAMA_SOURCE:=$ROOT_DIR/data/vendor/llama.cpp}"
: "${LOCAL_LLAMA_ARCHIVE:=$ROOT_DIR/data/vendor/llama.cpp-$LLAMA_COMMIT.tar.gz}"
if [[ "$LOCAL_LLAMA_SOURCE" != /* ]]; then LOCAL_LLAMA_SOURCE="$ROOT_DIR/$LOCAL_LLAMA_SOURCE"; fi
if [[ "$LOCAL_LLAMA_ARCHIVE" != /* ]]; then LOCAL_LLAMA_ARCHIVE="$ROOT_DIR/$LOCAL_LLAMA_ARCHIVE"; fi

run() {
  local value
  printf '+' >&2
  for value in "$@"; do printf ' %q' "$value" >&2; done
  printf '\n' >&2
  if ! openalpha_is_true "$DRY_RUN"; then command "$@"; fi
}

assert_clean_llama_source() {
  local status
  status="$(git -C "$LOCAL_LLAMA_SOURCE" status --porcelain=v1 --untracked-files=all \
    -- . ':(exclude)build' ':(exclude)build/**')"
  if [[ -n "$status" ]]; then
    echo "llama.cpp source has tracked or untracked changes outside build/: $LOCAL_LLAMA_SOURCE" >&2
    printf '%s\n' "$status" >&2
    return 1
  fi
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

archive_ready() {
  [[ -f "$LOCAL_LLAMA_ARCHIVE" ]] \
    && [[ "$(sha256_file "$LOCAL_LLAMA_ARCHIVE")" == "$LLAMA_ARCHIVE_SHA256" ]] \
    && tar -tzf "$LOCAL_LLAMA_ARCHIVE" >/dev/null
}

prepare_git_checkout() {
  local check_before="${1:-true}"
  if openalpha_is_true "$check_before"; then assert_clean_llama_source; fi
  if ! git -C "$LOCAL_LLAMA_SOURCE" cat-file -e "$LLAMA_COMMIT^{commit}" 2>/dev/null; then
    run git -C "$LOCAL_LLAMA_SOURCE" fetch --depth 1 origin "$LLAMA_COMMIT"
  fi
  run git -C "$LOCAL_LLAMA_SOURCE" checkout --detach "$LLAMA_COMMIT"
  [[ "$(git -C "$LOCAL_LLAMA_SOURCE" rev-parse HEAD)" == "$LLAMA_COMMIT" ]] \
    || { echo "llama.cpp did not resolve to LLAMA_COMMIT." >&2; return 1; }
  assert_clean_llama_source
}

download_archive() {
  local partial="${LOCAL_LLAMA_ARCHIVE}.partial"
  run mkdir -p "$(dirname "$LOCAL_LLAMA_ARCHIVE")"
  run curl --fail --location --retry 10 --retry-delay 3 --retry-all-errors \
    --continue-at - --output "$partial" "$LLAMA_ARCHIVE_URL"
  if ! openalpha_is_true "$DRY_RUN"; then
    if [[ "$(sha256_file "$partial")" != "$LLAMA_ARCHIVE_SHA256" ]]; then
      echo "llama.cpp archive hash mismatch; remove $partial before retrying." >&2
      return 1
    fi
    tar -tzf "$partial" >/dev/null
  fi
  run mv "$partial" "$LOCAL_LLAMA_ARCHIVE"
}

openalpha_require_commands awk curl git tar
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  echo "sha256sum or shasum is required." >&2
  exit 1
fi
if [[ ! "$LLAMA_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "LLAMA_COMMIT must be a full 40-character commit hash." >&2
  exit 1
fi
if [[ -d "$LOCAL_LLAMA_SOURCE/.git" ]]; then
  if openalpha_is_true "$DRY_RUN"; then
    run git -C "$LOCAL_LLAMA_SOURCE" checkout --detach "$LLAMA_COMMIT"
  else
    prepare_git_checkout
  fi
  echo "llama.cpp Git source prepared at $LOCAL_LLAMA_SOURCE"
  exit 0
fi
if archive_ready; then
  echo "Verified llama.cpp source archive prepared at $LOCAL_LLAMA_ARCHIVE"
  exit 0
fi
if [[ -e "$LOCAL_LLAMA_SOURCE" ]]; then
  echo "LOCAL_LLAMA_SOURCE exists but is not a Git checkout: $LOCAL_LLAMA_SOURCE" >&2
  exit 1
fi
run mkdir -p "$(dirname "$LOCAL_LLAMA_SOURCE")"
if openalpha_is_true "$DRY_RUN"; then
  run git clone --filter=blob:none --no-checkout --depth 1 \
    "$LLAMA_REPOSITORY" "$LOCAL_LLAMA_SOURCE"
  echo "llama.cpp Git source would be prepared at $LOCAL_LLAMA_SOURCE"
  exit 0
fi
if git clone --filter=blob:none --no-checkout --depth 1 \
  "$LLAMA_REPOSITORY" "$LOCAL_LLAMA_SOURCE"; then
  prepare_git_checkout false
  echo "llama.cpp Git source prepared at $LOCAL_LLAMA_SOURCE"
else
  echo "Git clone failed; using the pinned codeload archive fallback." >&2
  download_archive
  echo "Verified llama.cpp source archive prepared at $LOCAL_LLAMA_ARCHIVE"
fi
