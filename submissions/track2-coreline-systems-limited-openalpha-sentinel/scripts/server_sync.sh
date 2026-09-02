#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/server.sh
source "$ROOT_DIR/scripts/lib/server.sh"

SERVER_DRY_RUN=false
SYNC_MODEL=auto
SYNC_LLAMA=auto
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) SERVER_DRY_RUN=true ;;
    --with-model) SYNC_MODEL=true ;;
    --without-model) SYNC_MODEL=false ;;
    --with-llama-source) SYNC_LLAMA=true ;;
    --without-llama-source) SYNC_LLAMA=false ;;
    --env)
      shift
      [[ $# -gt 0 ]] || { echo "--env requires a path" >&2; exit 2; }
      OPENALPHA_ENV_FILE="$1"
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
export SERVER_DRY_RUN OPENALPHA_ENV_FILE

server_init "$ROOT_DIR"
openalpha_require_commands awk git ssh rsync tar

: "${OPENALPHA_ROOT:?OPENALPHA_ROOT is required}"
: "${OPENALPHA_DATA_DIR:?OPENALPHA_DATA_DIR is required}"
: "${OPENALPHA_RUN_DIR:?OPENALPHA_RUN_DIR is required}"
: "${OPENALPHA_LOG_DIR:?OPENALPHA_LOG_DIR is required}"
: "${OUTPUT_DIR:?OUTPUT_DIR is required}"
: "${LLAMA_SOURCE:?LLAMA_SOURCE is required}"
: "${LLAMA_COMMIT:?LLAMA_COMMIT is required}"
: "${LLAMA_ARCHIVE_PATH:=/workspace/cache/llama.cpp-$LLAMA_COMMIT.tar.gz}"
: "${LLAMA_ARCHIVE_SHA256:=65536629d57a7b7f9ec81a323311dd497e09a5d8b981225c6c56feda63cefde4}"
: "${LOCAL_LLAMA_ARCHIVE:=$ROOT_DIR/data/vendor/llama.cpp-$LLAMA_COMMIT.tar.gz}"
: "${MODEL_PATH:?MODEL_PATH is required}"

if [[ ! "$LLAMA_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "LLAMA_COMMIT must be a full 40-character commit hash." >&2
  exit 1
fi

if [[ "$OPENALPHA_ROOT" != "$REMOTE_PROJECT_DIR" ]]; then
  echo "OPENALPHA_ROOT must equal REMOTE_PROJECT_DIR before synchronization." >&2
  exit 1
fi

MANAGED_PATH_NAMES=(
  REMOTE_PROJECT_DIR OPENALPHA_DATA_DIR OPENALPHA_RUN_DIR OPENALPHA_LOG_DIR
  OUTPUT_DIR LLAMA_SOURCE LLAMA_ARCHIVE_PATH MODEL_PATH
)
MANAGED_PATH_VALUES=(
  "$REMOTE_PROJECT_DIR" "$OPENALPHA_DATA_DIR" "$OPENALPHA_RUN_DIR" "$OPENALPHA_LOG_DIR"
  "$OUTPUT_DIR" "$LLAMA_SOURCE" "$LLAMA_ARCHIVE_PATH" "$MODEL_PATH"
)
for ((i = 0; i < ${#MANAGED_PATH_VALUES[@]}; i++)); do
  server_validate_remote_path "${MANAGED_PATH_NAMES[$i]}" "${MANAGED_PATH_VALUES[$i]}"
  for ((j = 0; j < i; j++)); do
    if server_paths_overlap "${MANAGED_PATH_VALUES[$i]}" "${MANAGED_PATH_VALUES[$j]}"; then
      echo "Managed paths must not overlap: ${MANAGED_PATH_NAMES[$i]} and ${MANAGED_PATH_NAMES[$j]}" >&2
      exit 1
    fi
  done
done

resolve_local_path() {
  local value="$1"
  if [[ "$value" == /* ]]; then printf '%s\n' "$value"; else printf '%s/%s\n' "$ROOT_DIR" "$value"; fi
}

sha256_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{print $1}'
  else
    openssl dgst -sha256 | awk '{print $NF}'
  fi
}

sha256_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    openssl dgst -sha256 "$file" | awk '{print $NF}'
  fi
}

# Complete local preflight before changing any remote files.
LOCAL_MODEL_RESOLVED=""
if [[ -n "${MODEL_LOCAL_PATH:-}" ]]; then
  LOCAL_MODEL_RESOLVED="$(resolve_local_path "$MODEL_LOCAL_PATH")"
  if [[ ! -f "$LOCAL_MODEL_RESOLVED" ]]; then
    if [[ "$SYNC_MODEL" == true ]]; then
      echo "Requested model file does not exist: $LOCAL_MODEL_RESOLVED" >&2
      exit 1
    fi
    echo "Model upload skipped; local file not found: $LOCAL_MODEL_RESOLVED" >&2
  elif [[ "$SYNC_MODEL" != false ]]; then
    if [[ ! "${MODEL_SHA256:-}" =~ ^[0-9a-fA-F]{64}$ ]]; then
      echo "MODEL_SHA256 must be a full SHA-256 when uploading a model." >&2
      exit 1
    fi
    if [[ "$(sha256_file "$LOCAL_MODEL_RESOLVED")" != "$MODEL_SHA256" ]]; then
      echo "MODEL_LOCAL_PATH does not match MODEL_SHA256." >&2
      exit 1
    fi
  fi
fi

LOCAL_LLAMA_RESOLVED=""
LOCAL_LLAMA_ARCHIVE_RESOLVED="$(resolve_local_path "$LOCAL_LLAMA_ARCHIVE")"
if [[ -f "$LOCAL_LLAMA_ARCHIVE_RESOLVED" && "$SYNC_LLAMA" != false ]]; then
  if [[ "$(sha256_file "$LOCAL_LLAMA_ARCHIVE_RESOLVED")" != "$LLAMA_ARCHIVE_SHA256" ]]; then
    echo "LOCAL_LLAMA_ARCHIVE does not match LLAMA_ARCHIVE_SHA256." >&2
    exit 1
  fi
  tar -tzf "$LOCAL_LLAMA_ARCHIVE_RESOLVED" >/dev/null
fi
if [[ -n "${LOCAL_LLAMA_SOURCE:-}" ]]; then
  LOCAL_LLAMA_RESOLVED="$(resolve_local_path "$LOCAL_LLAMA_SOURCE")"
  if [[ -d "$LOCAL_LLAMA_RESOLVED" && "$SYNC_LLAMA" != false ]]; then
    if [[ ! -d "$LOCAL_LLAMA_RESOLVED/.git" ]]; then
      echo "LOCAL_LLAMA_SOURCE must be a Git checkout: $LOCAL_LLAMA_RESOLVED" >&2
      exit 1
    fi
    LLAMA_STATUS="$(git -C "$LOCAL_LLAMA_RESOLVED" status --porcelain=v1 --untracked-files=all \
      -- . ':(exclude)build' ':(exclude)build/**')"
    if [[ -n "$LLAMA_STATUS" ]]; then
      echo "Refusing to synchronize a dirty llama.cpp source tree." >&2
      printf '%s\n' "$LLAMA_STATUS" >&2
      exit 1
    fi
    if [[ "$(git -C "$LOCAL_LLAMA_RESOLVED" rev-parse HEAD)" != "$LLAMA_COMMIT" ]]; then
      echo "LOCAL_LLAMA_SOURCE is not at LLAMA_COMMIT=$LLAMA_COMMIT" >&2
      exit 1
    fi
  elif [[ "$SYNC_LLAMA" == true && ! -f "$LOCAL_LLAMA_ARCHIVE_RESOLVED" ]]; then
    echo "Requested llama.cpp source does not exist: $LOCAL_LLAMA_RESOLVED" >&2
    exit 1
  elif [[ ! -d "$LOCAL_LLAMA_RESOLVED" && ! -f "$LOCAL_LLAMA_ARCHIVE_RESOLVED" ]]; then
    echo "llama.cpp upload skipped; LOCAL_LLAMA_SOURCE is not a directory." >&2
  fi
elif [[ "$SYNC_LLAMA" == true && ! -f "$LOCAL_LLAMA_ARCHIVE_RESOLVED" ]]; then
  echo "Neither LOCAL_LLAMA_SOURCE nor LOCAL_LLAMA_ARCHIVE is available." >&2
  exit 1
fi

# Reject symlinked managed paths before any --delete transfer. This also checks
# resolved paths on the host, rather than trusting local lexical validation alone.
server_remote bash -c '
  set -euo pipefail
  paths=("$@")
  resolved=()
  for path in "${paths[@]}"; do
    current=""
    relative="${path#/}"
    IFS=/ read -r -a parts <<< "$relative"
    for part in "${parts[@]}"; do
      current="$current/$part"
      if [[ -L "$current" ]]; then
        echo "Managed remote path contains a symlink: $current" >&2
        exit 1
      fi
    done
    resolved+=("$(realpath -m -- "$path")")
  done
  for ((i = 0; i < ${#resolved[@]}; i++)); do
    for ((j = 0; j < i; j++)); do
      left="${resolved[$i]%/}"
      right="${resolved[$j]%/}"
      if [[ "$left" == "$right" || "$left" == "$right/"* || "$right" == "$left/"* ]]; then
        echo "Resolved managed remote paths overlap: $left and $right" >&2
        exit 1
      fi
    done
  done
' openalpha-path-check "${MANAGED_PATH_VALUES[@]}"

server_remote mkdir -p "$REMOTE_PROJECT_DIR"

RSYNC_ARGS=(
  -az --delete
  --exclude=.git/
  --exclude=.venv/
  --include=/.env.example
  --exclude='.env*'
  --exclude=.openalpha-deployment
  --exclude=.DS_Store
  --exclude=.coverage
  --exclude=.pytest_cache/
  --exclude='**/__pycache__/'
  --exclude=htmlcov/
  --exclude=dist/
  --exclude=build/
  --exclude='*.egg-info/'
  --exclude=data/
  --exclude='*.db'
  --exclude='*.db-*'
  --exclude='*.sqlite*'
  --exclude='*.gguf'
  --exclude=models/
  --exclude=logs/
)
if openalpha_is_true "$SERVER_DRY_RUN"; then
  RSYNC_ARGS+=(--dry-run)
fi
server_run_local rsync "${RSYNC_ARGS[@]}" -e "$SERVER_RSYNC_SSH" \
  "$ROOT_DIR/" "$SERVER_TARGET:$REMOTE_PROJECT_DIR/"

if [[ -n "$LOCAL_MODEL_RESOLVED" && -f "$LOCAL_MODEL_RESOLVED" && "$SYNC_MODEL" != false ]]; then
  : "${MODEL_PATH:?MODEL_PATH is required when uploading a model}"
  MODEL_NEXT="${MODEL_PATH}.next"
  MODEL_PREVIOUS="${MODEL_PATH}.pre-deploy"
  server_remote mkdir -p "$(dirname "$MODEL_PATH")"
  server_run_local rsync -az --partial --progress -e "$SERVER_RSYNC_SSH" \
    "$LOCAL_MODEL_RESOLVED" "$SERVER_TARGET:$MODEL_NEXT"
  server_remote bash -c '
    set -euo pipefail
    expected="$1"
    next="$2"
    target="$3"
    previous="$4"
    echo "$expected  $next" | sha256sum --check --status
    rm -f "$previous"
    if [[ -e "$target" ]]; then mv "$target" "$previous"; fi
    if ! mv "$next" "$target"; then
      if [[ -e "$previous" && ! -e "$target" ]]; then mv "$previous" "$target"; fi
      exit 1
    fi
  ' openalpha-model-swap "$MODEL_SHA256" "$MODEL_NEXT" "$MODEL_PATH" "$MODEL_PREVIOUS"
fi

if [[ -n "$LOCAL_LLAMA_RESOLVED" && -d "$LOCAL_LLAMA_RESOLVED" && "$SYNC_LLAMA" != false ]]; then
  : "${LLAMA_SOURCE:?LLAMA_SOURCE is required when uploading llama.cpp}"
  server_remote mkdir -p "$LLAMA_SOURCE"
  LLAMA_RSYNC_ARGS=(-az --delete --exclude=build/)
  if openalpha_is_true "$SERVER_DRY_RUN"; then LLAMA_RSYNC_ARGS+=(--dry-run); fi
  server_run_local rsync "${LLAMA_RSYNC_ARGS[@]}" -e "$SERVER_RSYNC_SSH" \
    "$LOCAL_LLAMA_RESOLVED/" "$SERVER_TARGET:$LLAMA_SOURCE/"
fi

if [[ -f "$LOCAL_LLAMA_ARCHIVE_RESOLVED" && "$SYNC_LLAMA" != false ]]; then
  server_remote mkdir -p "$(dirname "$LLAMA_ARCHIVE_PATH")"
  server_run_local rsync -az --partial --progress -e "$SERVER_RSYNC_SSH" \
    "$LOCAL_LLAMA_ARCHIVE_RESOLVED" "$SERVER_TARGET:$LLAMA_ARCHIVE_PATH"
fi

# Switch private configuration only after all large transfers have completed.
# The deploy wrapper restores this retained copy if bootstrap or startup fails.
server_remote bash -c \
  'if [[ -f "$1/.env" ]]; then cp -p "$1/.env" "$1/.env.pre-deploy"; chmod 600 "$1/.env.pre-deploy"; fi' \
  openalpha-env-backup "$REMOTE_PROJECT_DIR"
server_run_local rsync -az -e "$SERVER_RSYNC_SSH" \
  "$OPENALPHA_LOADED_ENV_FILE" "$SERVER_TARGET:$REMOTE_PROJECT_DIR/.env.next"
server_remote chmod 600 "$REMOTE_PROJECT_DIR/.env.next"
server_remote mv -f "$REMOTE_PROJECT_DIR/.env.next" "$REMOTE_PROJECT_DIR/.env"

DEPLOYMENT_MANIFEST="$(mktemp)"
cleanup_manifest() { rm -f "$DEPLOYMENT_MANIFEST"; }
trap cleanup_manifest EXIT
PROJECT_STATUS="$(git -C "$ROOT_DIR" status --porcelain=v1 --untracked-files=all)"
if [[ -n "$PROJECT_STATUS" ]]; then PROJECT_STATE=dirty; else PROJECT_STATE=clean; fi
{
  printf 'manifest_version=1\n'
  printf 'generated_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'project_git_head=%s\n' "$(git -C "$ROOT_DIR" rev-parse HEAD)"
  printf 'project_git_tree=%s\n' "$(git -C "$ROOT_DIR" rev-parse HEAD^{tree})"
  printf 'project_git_state=%s\n' "$PROJECT_STATE"
  printf 'project_git_status_sha256=%s\n' "$(printf '%s' "$PROJECT_STATUS" | sha256_stream)"
  printf 'project_git_diff_sha256=%s\n' "$(git -C "$ROOT_DIR" diff --no-ext-diff --binary HEAD | sha256_stream)"
  printf 'pyproject_sha256=%s\n' "$(sha256_file "$ROOT_DIR/pyproject.toml")"
  printf 'llama_repository=%s\n' "${LLAMA_REPOSITORY:-https://github.com/ROCm/llama.cpp.git}"
  printf 'llama_commit=%s\n' "${LLAMA_COMMIT:-unknown}"
  printf 'llama_archive_sha256=%s\n' "$LLAMA_ARCHIVE_SHA256"
  printf 'amdgpu_targets=%s\n' "${AMDGPU_TARGETS:-native}"
  printf 'model_sha256=%s\n' "${MODEL_SHA256:-not-configured}"
  printf 'llm_backend=%s\n' "${OPENALPHA_LLM_BACKEND:-not-configured}"
  printf 'llama_gpu_layers=%s\n' "${LLAMA_GPU_LAYERS:-not-configured}"
} > "$DEPLOYMENT_MANIFEST"
server_run_local rsync -az -e "$SERVER_RSYNC_SSH" \
  "$DEPLOYMENT_MANIFEST" "$SERVER_TARGET:$REMOTE_PROJECT_DIR/.openalpha-deployment.next"
server_remote chmod 644 "$REMOTE_PROJECT_DIR/.openalpha-deployment.next"
server_remote mv -f "$REMOTE_PROJECT_DIR/.openalpha-deployment.next" \
  "$REMOTE_PROJECT_DIR/.openalpha-deployment"

echo "Repository and configuration synchronized to $SERVER_TARGET:$REMOTE_PROJECT_DIR"
