#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/scripts/lib/env.sh"
openalpha_load_env "$ROOT_DIR" runtime required

DRY_RUN=false
SKIP_PACKAGES=false
SKIP_LLAMA_BUILD=false
SKIP_SYSTEMD=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --skip-packages) SKIP_PACKAGES=true ;;
    --skip-llama-build) SKIP_LLAMA_BUILD=true ;;
    --skip-systemd) SKIP_SYSTEMD=true ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

run() {
  local value
  printf '+' >&2
  for value in "$@"; do printf ' %q' "$value" >&2; done
  printf '\n' >&2
  if ! openalpha_is_true "$DRY_RUN"; then
    command "$@"
  fi
}

assert_clean_llama_source() {
  local status
  status="$(git -C "$LLAMA_SOURCE" status --porcelain=v1 --untracked-files=all \
    -- . ':(exclude)build' ':(exclude)build/**')"
  if [[ -n "$status" ]]; then
    echo "llama.cpp source has tracked or untracked changes outside build/: $LLAMA_SOURCE" >&2
    printf '%s\n' "$status" >&2
    return 1
  fi
}

verify_llama_archive() {
  local entry
  local listing
  local member_type
  local prefix="llama.cpp-$LLAMA_COMMIT"
  echo "$LLAMA_ARCHIVE_SHA256  $LLAMA_ARCHIVE_PATH" | sha256sum --check --status
  tar -tzf "$LLAMA_ARCHIVE_PATH" >/dev/null
  while IFS= read -r entry; do
    case "$entry" in
      "$prefix"|"$prefix/"*) ;;
      *) echo "Unexpected path in llama.cpp archive: $entry" >&2; return 1 ;;
    esac
    if [[ "$entry" == /* || "/$entry/" == *"/../"* || "/$entry/" == *"/./"* ]]; then
      echo "Unsafe path in llama.cpp archive: $entry" >&2
      return 1
    fi
  done < <(tar -tzf "$LLAMA_ARCHIVE_PATH")
  while IFS= read -r listing; do
    member_type="${listing:0:1}"
    case "$member_type" in -|d) ;; *) echo "Disallowed llama.cpp archive member type: $member_type" >&2; return 1 ;; esac
  done < <(LC_ALL=C tar -tvzf "$LLAMA_ARCHIVE_PATH")
}

install_llama_archive_source() {
  local temporary
  local prefix="llama.cpp-$LLAMA_COMMIT"
  run mkdir -p "$(dirname "$LLAMA_SOURCE")"
  temporary="$(mktemp -d "$(dirname "$LLAMA_SOURCE")/.llama-source.XXXXXX")"
  if ! tar -xzf "$LLAMA_ARCHIVE_PATH" -C "$temporary"; then
    rm -rf "$temporary"
    return 1
  fi
  run mkdir -p "$LLAMA_SOURCE"
  if ! rsync -a --delete --exclude=build/ "$temporary/$prefix/" "$LLAMA_SOURCE/"; then
    rm -rf "$temporary"
    return 1
  fi
  {
    printf 'llama_commit=%s\n' "$LLAMA_COMMIT"
    printf 'archive_sha256=%s\n' "$LLAMA_ARCHIVE_SHA256"
  } > "$LLAMA_SOURCE/.openalpha-source-archive"
  rm -rf "$temporary"
}

build_llama_safely() {
  local rollback=""
  local failed="${LLAMA_BUILD}.failed-build-$$"
  if [[ -d "$LLAMA_BUILD" ]]; then
    rollback="${LLAMA_BUILD}.pre-build-$$"
    [[ ! -e "$rollback" ]] || { echo "Build rollback path exists: $rollback" >&2; return 1; }
    cp -a --reflink=auto "$LLAMA_BUILD" "$rollback"
  fi
  if "$OPENALPHA_ROOT/scripts/setup_rocm_llama.sh"; then
    if [[ -n "$rollback" ]]; then rm -rf "$rollback"; fi
    return 0
  fi
  if [[ -n "$rollback" ]]; then
    if [[ -e "$failed" ]]; then
      echo "Failed-build retention path already exists: $failed" >&2
      return 1
    fi
    if [[ -e "$LLAMA_BUILD" ]] && ! mv "$LLAMA_BUILD" "$failed"; then
      echo "Could not isolate the failed build; rollback retained at $rollback" >&2
      return 1
    fi
    if mv "$rollback" "$LLAMA_BUILD"; then
      rm -rf "$failed"
      echo "llama.cpp build failed; the previous build was restored." >&2
    else
      echo "llama.cpp build failed and automatic build rollback also failed." >&2
    fi
  fi
  return 1
}

systemd_online() {
  command -v systemctl >/dev/null 2>&1 \
    && [[ -d /run/systemd/system ]] \
    && systemctl show-environment >/dev/null 2>&1
}

: "${OPENALPHA_ROOT:=$ROOT_DIR}"
: "${PYTHON_BIN:=python3.12}"
: "${LLAMA_REPOSITORY:=https://github.com/ROCm/llama.cpp.git}"
: "${LLAMA_COMMIT:=1b99711a5f2582ec99686eb7958844749c223cf5}"
: "${LLAMA_ARCHIVE_PATH:=/workspace/cache/llama.cpp-$LLAMA_COMMIT.tar.gz}"
: "${LLAMA_ARCHIVE_SHA256:=65536629d57a7b7f9ec81a323311dd497e09a5d8b981225c6c56feda63cefde4}"
: "${LLAMA_SOURCE:=/workspace/llama.cpp}"
: "${LLAMA_BUILD:=$LLAMA_SOURCE/build}"
: "${SERVER_INSTALL_EXTRAS:=dev}"
: "${SERVER_SERVICE_MODE:=auto}"
: "${SERVER_START_COMPONENTS:=llama,api,worker}"

if [[ ! "$LLAMA_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "LLAMA_COMMIT must be a full 40-character commit hash." >&2
  exit 1
fi

case "$SERVER_SERVICE_MODE" in
  auto|systemd|process|nohup) ;;
  *) echo "Unsupported SERVER_SERVICE_MODE: $SERVER_SERVICE_MODE" >&2; exit 1 ;;
esac
SYSTEMD_UNITS=()
IFS=',' read -r -a requested_components <<< "$SERVER_START_COMPONENTS"
for component in "${requested_components[@]}"; do
  component="${component//[[:space:]]/}"
  case "$component" in
    llama|api|worker) SYSTEMD_UNITS+=("openalpha-$component.service") ;;
    '') ;;
    *) echo "Unsupported component in SERVER_START_COMPONENTS: $component" >&2; exit 1 ;;
  esac
done

if [[ "$OPENALPHA_ROOT" != "$ROOT_DIR" ]]; then
  echo "OPENALPHA_ROOT ($OPENALPHA_ROOT) must match the deployed repository ($ROOT_DIR)." >&2
  exit 1
fi
if [[ "$LLAMA_BUILD" != "$LLAMA_SOURCE/build" ]]; then
  echo "LLAMA_BUILD must be the managed build directory $LLAMA_SOURCE/build" >&2
  exit 1
fi

if ! openalpha_is_true "$SKIP_PACKAGES" && openalpha_is_true "${SERVER_INSTALL_PACKAGES:-true}"; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Package installation requires root; rerun with --skip-packages if dependencies exist." >&2
    exit 1
  fi
  run apt-get update
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates cmake curl git build-essential rsync "$PYTHON_BIN" "${PYTHON_BIN}-venv"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && ! openalpha_is_true "$DRY_RUN"; then
  echo "Python executable is unavailable: $PYTHON_BIN" >&2
  exit 1
fi

run mkdir -p "$OPENALPHA_ROOT" "${OPENALPHA_DATA_DIR:-$OPENALPHA_ROOT/data/runtime}" \
  "${OPENALPHA_RUN_DIR:-$OPENALPHA_ROOT/data/run}" \
  "${OPENALPHA_LOG_DIR:-$OPENALPHA_ROOT/data/logs}"
run "$PYTHON_BIN" -m venv "$OPENALPHA_ROOT/.venv"
run "$OPENALPHA_ROOT/.venv/bin/python" -m pip install --upgrade pip
if [[ -n "$SERVER_INSTALL_EXTRAS" ]]; then
  run "$OPENALPHA_ROOT/.venv/bin/python" -m pip install -e "$OPENALPHA_ROOT[$SERVER_INSTALL_EXTRAS]"
else
  run "$OPENALPHA_ROOT/.venv/bin/python" -m pip install -e "$OPENALPHA_ROOT"
fi
run "$OPENALPHA_ROOT/.venv/bin/openalpha" init

if [[ -n "${MODEL_PATH:-}" ]]; then
  MODEL_READY=false
  MODEL_PARTIAL="${MODEL_PATH}.partial"
  if [[ -f "$MODEL_PATH" ]]; then
    if [[ -z "${MODEL_SHA256:-}" ]] \
      || echo "$MODEL_SHA256  $MODEL_PATH" | sha256sum --check --status; then
      MODEL_READY=true
    fi
  fi

  if ! openalpha_is_true "$MODEL_READY"; then
    if [[ -z "${MODEL_DOWNLOAD_URL:-}" ]]; then
      echo "MODEL_PATH is missing or invalid and MODEL_DOWNLOAD_URL is empty: $MODEL_PATH" >&2
      exit 1
    fi
    run mkdir -p "$(dirname "$MODEL_PATH")"
    if ! run curl --fail --location --retry 10 --retry-delay 3 --retry-all-errors \
      --continue-at - --output "$MODEL_PARTIAL" "$MODEL_DOWNLOAD_URL"; then
      echo "Model download failed without disabling TLS verification." >&2
      exit 1
    fi
    if ! openalpha_is_true "$DRY_RUN" && [[ -n "${MODEL_SHA256:-}" ]] \
      && ! echo "$MODEL_SHA256  $MODEL_PARTIAL" | sha256sum --check --status; then
      echo "Downloaded model hash does not match; remove $MODEL_PARTIAL before retrying." >&2
      exit 1
    fi
    MODEL_PREVIOUS="${MODEL_PATH}.pre-deploy"
    if ! openalpha_is_true "$DRY_RUN" && [[ -e "$MODEL_PREVIOUS" ]]; then
      echo "Unresolved model rollback file exists: $MODEL_PREVIOUS" >&2
      exit 1
    fi
    if ! openalpha_is_true "$DRY_RUN" && [[ -e "$MODEL_PATH" ]]; then
      run mv "$MODEL_PATH" "$MODEL_PREVIOUS"
    fi
    if ! run mv "$MODEL_PARTIAL" "$MODEL_PATH"; then
      if ! openalpha_is_true "$DRY_RUN" && [[ -e "$MODEL_PREVIOUS" && ! -e "$MODEL_PATH" ]]; then
        mv "$MODEL_PREVIOUS" "$MODEL_PATH" || true
      fi
      exit 1
    fi
  fi

  if ! openalpha_is_true "$DRY_RUN" && [[ -n "${MODEL_SHA256:-}" ]] \
    && ! echo "$MODEL_SHA256  $MODEL_PATH" | sha256sum --check --status; then
    echo "MODEL_SHA256 does not match $MODEL_PATH" >&2
    exit 1
  fi
fi

if ! openalpha_is_true "$SKIP_LLAMA_BUILD"; then
  if openalpha_is_true "$DRY_RUN"; then
    if [[ -f "$LLAMA_ARCHIVE_PATH" ]]; then
      run sha256sum "$LLAMA_ARCHIVE_PATH"
      run tar -tzf "$LLAMA_ARCHIVE_PATH"
    elif [[ -d "$LLAMA_SOURCE/.git" ]]; then
      run git -C "$LLAMA_SOURCE" checkout --detach "$LLAMA_COMMIT"
    else
      run git clone --filter=blob:none --no-checkout --depth 1 \
        "$LLAMA_REPOSITORY" "$LLAMA_SOURCE"
    fi
    run "$OPENALPHA_ROOT/scripts/setup_rocm_llama.sh"
  else
    CLONED_LLAMA_SOURCE=false
    if [[ -f "$LLAMA_ARCHIVE_PATH" ]]; then
      verify_llama_archive
      install_llama_archive_source
    elif [[ ! -d "$LLAMA_SOURCE" ]]; then
      run mkdir -p "$(dirname "$LLAMA_SOURCE")"
      if ! run git clone --filter=blob:none --no-checkout --depth 1 \
        "$LLAMA_REPOSITORY" "$LLAMA_SOURCE"; then
        echo "Remote Git clone failed. Run scripts/prepare_llama_source.sh locally and redeploy." >&2
        exit 1
      fi
      CLONED_LLAMA_SOURCE=true
    fi
    if [[ -d "$LLAMA_SOURCE/.git" ]]; then
      if ! openalpha_is_true "$CLONED_LLAMA_SOURCE"; then assert_clean_llama_source; fi
      if ! git -C "$LLAMA_SOURCE" cat-file -e "$LLAMA_COMMIT^{commit}" 2>/dev/null; then
        run git -C "$LLAMA_SOURCE" fetch --depth 1 origin "$LLAMA_COMMIT"
      fi
      run git -C "$LLAMA_SOURCE" checkout --detach "$LLAMA_COMMIT"
      [[ "$(git -C "$LLAMA_SOURCE" rev-parse HEAD)" == "$LLAMA_COMMIT" ]] \
        || { echo "llama.cpp did not resolve to LLAMA_COMMIT." >&2; exit 1; }
      assert_clean_llama_source
    elif [[ -f "$LLAMA_SOURCE/.openalpha-source-archive" ]]; then
      grep -Fxq "llama_commit=$LLAMA_COMMIT" "$LLAMA_SOURCE/.openalpha-source-archive"
      grep -Fxq "archive_sha256=$LLAMA_ARCHIVE_SHA256" "$LLAMA_SOURCE/.openalpha-source-archive"
    else
      echo "Refusing to build unverified llama.cpp source: $LLAMA_SOURCE" >&2
      exit 1
    fi
    build_llama_safely
  fi
fi

if ! openalpha_is_true "$SKIP_SYSTEMD"; then
  if [[ "$SERVER_SERVICE_MODE" == systemd ]] && ! systemd_online; then
    echo "SERVER_SERVICE_MODE=systemd but systemd is offline." >&2
    exit 1
  fi
  if systemd_online && [[ "$SERVER_SERVICE_MODE" == process || "$SERVER_SERVICE_MODE" == nohup ]]; then
    if [[ "$(id -u)" -ne 0 ]]; then
      echo "Disabling existing systemd units requires root." >&2
      exit 1
    fi
    run systemctl disable --now openalpha-llama.service openalpha-api.service \
      openalpha-worker.service || true
    echo "Process lifecycle mode selected; systemd units are disabled." >&2
  elif systemd_online; then
    if [[ "$(id -u)" -ne 0 ]]; then
      echo "Installing systemd units requires root." >&2
      exit 1
    fi
    run install -m 0600 "$OPENALPHA_ROOT/.env" /etc/openalpha-sentinel.env
    run install -m 0755 "$OPENALPHA_ROOT/scripts/systemd_entrypoint.sh" /usr/local/bin/openalpha-service
    run install -m 0644 "$OPENALPHA_ROOT/deploy/systemd/openalpha-api.service" /etc/systemd/system/
    run install -m 0644 "$OPENALPHA_ROOT/deploy/systemd/openalpha-worker.service" /etc/systemd/system/
    run install -m 0644 "$OPENALPHA_ROOT/deploy/systemd/openalpha-llama.service" /etc/systemd/system/
    run systemctl daemon-reload
    run systemctl disable --now openalpha-llama.service openalpha-api.service \
      openalpha-worker.service || true
    if (( ${#SYSTEMD_UNITS[@]} > 0 )); then run systemctl enable "${SYSTEMD_UNITS[@]}"; fi
  else
    echo "systemd is offline; nohup/PID lifecycle mode will be used." >&2
  fi
fi

echo "Remote bootstrap completed at $OPENALPHA_ROOT"
