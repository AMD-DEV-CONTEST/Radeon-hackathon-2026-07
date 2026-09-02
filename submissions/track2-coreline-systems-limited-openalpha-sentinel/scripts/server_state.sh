#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/scripts/lib/env.sh"
openalpha_load_env "$ROOT_DIR" runtime required

: "${OPENALPHA_DATA_DIR:?OPENALPHA_DATA_DIR is required}"
: "${OUTPUT_DIR:=$ROOT_DIR/docs/submission/generated}"
STATE_TEMPORARY=""
STATE_DATA_STAGE=""
STATE_ARTIFACT_STAGE=""

cleanup() {
  if [[ -n "$STATE_TEMPORARY" ]]; then rm -rf "$STATE_TEMPORARY"; fi
  if [[ -n "$STATE_DATA_STAGE" ]]; then rm -rf "$STATE_DATA_STAGE"; fi
  if [[ -n "$STATE_ARTIFACT_STAGE" ]]; then rm -rf "$STATE_ARTIFACT_STAGE"; fi
}
trap cleanup EXIT

validate_absolute_path() {
  local name="$1"
  local value="$2"
  local relative="${value#/}"
  if [[ "$value" != /* || "$value" == *".."* || "$value" == *"//"* \
    || "$value" == *"/./"* || "$value" == "/" || "$value" == */ \
    || "$relative" != */* ]]; then
    echo "$name must be a managed absolute path with at least two components: $value" >&2
    return 1
  fi
}

validate_state_paths() {
  local data="${OPENALPHA_DATA_DIR%/}"
  local artifacts="${OUTPUT_DIR%/}"
  validate_absolute_path OPENALPHA_DATA_DIR "$data"
  validate_absolute_path OUTPUT_DIR "$artifacts"
  if [[ "$data" == "$artifacts" || "$data" == "$artifacts/"* || "$artifacts" == "$data/"* ]]; then
    echo "OPENALPHA_DATA_DIR and OUTPUT_DIR must not overlap." >&2
    return 1
  fi
}

validate_archive() {
  local archive="$1"
  local entry
  local listing
  local member_type
  tar -tzf "$archive" >/dev/null
  while IFS= read -r entry; do
    case "$entry" in
      manifest.txt|openalpha-data|openalpha-data/*|openalpha-artifacts|openalpha-artifacts/*) ;;
      *) echo "Backup contains an unexpected path: $entry" >&2; return 1 ;;
    esac
    if [[ "$entry" == /* || "/$entry/" == *"/../"* || "/$entry/" == *"/./"* ]]; then
      echo "Backup contains an unsafe path: $entry" >&2
      return 1
    fi
  done < <(tar -tzf "$archive")
  while IFS= read -r listing; do
    member_type="${listing:0:1}"
    case "$member_type" in
      -|d) ;;
      *)
        echo "Backup contains a disallowed archive member type ($member_type)." >&2
        return 1
        ;;
    esac
  done < <(LC_ALL=C tar -tvzf "$archive")
}

backup_state() {
  local temporary
  local python_bin="${OPENALPHA_ROOT:-$ROOT_DIR}/.venv/bin/python"
  temporary="$(mktemp -d)"
  STATE_TEMPORARY="$temporary"
  mkdir -p "$temporary/openalpha-data" "$temporary/openalpha-artifacts"

  if [[ -d "$OPENALPHA_DATA_DIR" ]]; then
    tar -C "$OPENALPHA_DATA_DIR" \
      --exclude='./openalpha.db' --exclude='./openalpha.db-wal' --exclude='./openalpha.db-shm' \
      -cf - . | tar -C "$temporary/openalpha-data" -xf -
  fi
  if [[ -f "$OPENALPHA_DATA_DIR/openalpha.db" ]]; then
    "$python_bin" - "$OPENALPHA_DATA_DIR/openalpha.db" \
      "$temporary/openalpha-data/openalpha.db" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
destination = sqlite3.connect(sys.argv[2])
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
PY
  fi
  if [[ -d "$OUTPUT_DIR" ]]; then
    tar -C "$OUTPUT_DIR" -cf - . | tar -C "$temporary/openalpha-artifacts" -xf -
  fi
  {
    printf 'created_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'hostname=%s\n' "$(hostname)"
    printf 'data_dir=%s\n' "$OPENALPHA_DATA_DIR"
    printf 'artifact_dir=%s\n' "$OUTPUT_DIR"
  } > "$temporary/manifest.txt"
  tar -C "$temporary" -czf - manifest.txt openalpha-data openalpha-artifacts
}

rollback_installed_path() {
  local active="$1"
  local previous="$2"
  local failed="$3"
  local label="$4"
  if [[ -e "$active" ]]; then
    if ! mv "$active" "$failed"; then
      echo "Could not isolate restored $label; previous path retained at $previous" >&2
      return 1
    fi
  fi
  if [[ -n "$previous" ]]; then
    if [[ -e "$active" ]] || ! mv "$previous" "$active"; then
      echo "Could not put previous $label back at $active" >&2
      return 1
    fi
  fi
}

restore_state() {
  local archive="$1"
  local confirmation="${2:-}"
  local temporary
  local stamp
  local suffix
  local data_stage
  local artifact_stage=""
  local old_data=""
  local old_artifacts=""
  local failed_data
  local failed_artifacts
  local candidate

  if [[ "$confirmation" != "--yes" ]]; then
    echo "Restore requires --yes." >&2
    return 2
  fi
  [[ -f "$archive" ]] || { echo "Backup not found: $archive" >&2; return 1; }
  validate_archive "$archive"
  validate_state_paths

  temporary="$(mktemp -d)"
  STATE_TEMPORARY="$temporary"
  tar -xzf "$archive" -C "$temporary"
  [[ -d "$temporary/openalpha-data" ]] || { echo "Backup has no openalpha-data directory." >&2; return 1; }

  mkdir -p "$(dirname "$OPENALPHA_DATA_DIR")" "$(dirname "$OUTPUT_DIR")"
  data_stage="$(mktemp -d "$(dirname "$OPENALPHA_DATA_DIR")/.openalpha-data-restore.XXXXXX")"
  STATE_DATA_STAGE="$data_stage"
  tar -C "$temporary/openalpha-data" -cf - . | tar -C "$data_stage" -xf -
  if [[ -d "$temporary/openalpha-artifacts" ]]; then
    artifact_stage="$(mktemp -d "$(dirname "$OUTPUT_DIR")/.openalpha-artifacts-restore.XXXXXX")"
    STATE_ARTIFACT_STAGE="$artifact_stage"
    tar -C "$temporary/openalpha-artifacts" -cf - . | tar -C "$artifact_stage" -xf -
  fi

  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  suffix="$stamp-$$"
  failed_data="${OPENALPHA_DATA_DIR}.failed-restore-$suffix"
  failed_artifacts="${OUTPUT_DIR}.failed-restore-$suffix"
  if [[ -e "$OPENALPHA_DATA_DIR" ]]; then old_data="${OPENALPHA_DATA_DIR}.pre-restore-$suffix"; fi
  if [[ -n "$artifact_stage" && -e "$OUTPUT_DIR" ]]; then old_artifacts="${OUTPUT_DIR}.pre-restore-$suffix"; fi
  for candidate in "$old_data" "$old_artifacts" "$failed_data" "$failed_artifacts"; do
    if [[ -n "$candidate" && -e "$candidate" ]]; then
      echo "Restore retention path already exists: $candidate" >&2
      return 1
    fi
  done

  if [[ -n "$old_data" ]]; then mv "$OPENALPHA_DATA_DIR" "$old_data"; fi
  if ! mv "$data_stage" "$OPENALPHA_DATA_DIR"; then
    if [[ -n "$old_data" && ! -e "$OPENALPHA_DATA_DIR" ]]; then mv "$old_data" "$OPENALPHA_DATA_DIR" || true; fi
    echo "Could not atomically install restored data; previous data was preserved." >&2
    return 1
  fi
  STATE_DATA_STAGE=""

  if [[ -n "$artifact_stage" ]]; then
    if [[ -n "$old_artifacts" ]] && ! mv "$OUTPUT_DIR" "$old_artifacts"; then
      rollback_installed_path "$OPENALPHA_DATA_DIR" "$old_data" "$failed_data" data || true
      echo "Could not retain previous artifacts; restored data was rolled back." >&2
      return 1
    fi
    if ! mv "$artifact_stage" "$OUTPUT_DIR"; then
      if [[ -n "$old_artifacts" && ! -e "$OUTPUT_DIR" ]]; then mv "$old_artifacts" "$OUTPUT_DIR" || true; fi
      rollback_installed_path "$OPENALPHA_DATA_DIR" "$old_data" "$failed_data" data || true
      echo "Could not atomically install restored artifacts; restored data was rolled back." >&2
      return 1
    fi
    STATE_ARTIFACT_STAGE=""
  fi

  echo "State restored to $OPENALPHA_DATA_DIR" >&2
  [[ -n "$old_data" ]] && echo "Previous data retained at $old_data" >&2
  [[ -n "$old_artifacts" ]] && echo "Previous artifacts retained at $old_artifacts" >&2
}

case "${1:-}" in
  backup) validate_state_paths; backup_state ;;
  validate) [[ -f "${2:-}" ]] || { echo "Backup not found: ${2:-}" >&2; exit 1; }; validate_archive "$2" ;;
  restore) restore_state "${2:-}" "${3:-}" ;;
  *) echo "Usage: $0 backup | validate ARCHIVE | restore ARCHIVE --yes" >&2; exit 2 ;;
esac
