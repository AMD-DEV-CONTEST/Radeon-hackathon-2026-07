#!/usr/bin/env bash

# shellcheck source=env.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

server_print_command() {
  local value
  printf '+' >&2
  for value in "$@"; do
    printf ' %q' "$value" >&2
  done
  printf '\n' >&2
}

server_validate_port() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 1 || value > 65535 )); then
    echo "$name must be an integer between 1 and 65535: $value" >&2
    return 1
  fi
}

server_validate_remote_path() {
  local name="$1"
  local value="$2"
  local relative="${value#/}"
  if [[ ! "$value" =~ ^/[A-Za-z0-9._/-]+$ ]] \
    || [[ "$value" == *".."* || "$value" == *"//"* || "$value" == *"/./"* ]] \
    || [[ "$value" == "/" || "$value" == */ || "$value" == */. || "$relative" != */* ]]; then
    echo "$name must be a managed absolute path with at least two components: $value" >&2
    return 1
  fi
}

server_paths_overlap() {
  local left="${1%/}"
  local right="${2%/}"
  [[ "$left" == "$right" || "$left" == "$right/"* || "$right" == "$left/"* ]]
}

server_init() {
  local root_dir="${1:?repository root is required}"
  openalpha_load_env "$root_dir" server required

  : "${REMOTE_SSH_HOST:?Set REMOTE_SSH_HOST in .env.server}"
  : "${REMOTE_SSH_PORT:?Set REMOTE_SSH_PORT in .env.server}"
  : "${REMOTE_SSH_USER:=root}"
  : "${REMOTE_PROJECT_DIR:=/workspace/openalpha-sentinel}"
  : "${REMOTE_CONNECT_TIMEOUT:=10}"
  : "${REMOTE_SSH_STRICT:=true}"

  if [[ "$REMOTE_SSH_HOST" == "CHANGE_ME" ]]; then
    echo "Set REMOTE_SSH_HOST in $OPENALPHA_LOADED_ENV_FILE." >&2
    return 1
  fi
  if [[ ! "$REMOTE_SSH_HOST" =~ ^[A-Za-z0-9._:-]+$ ]]; then
    echo "REMOTE_SSH_HOST contains unsupported characters." >&2
    return 1
  fi
  if [[ ! "$REMOTE_SSH_USER" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]]; then
    echo "REMOTE_SSH_USER contains unsupported characters." >&2
    return 1
  fi
  server_validate_port REMOTE_SSH_PORT "$REMOTE_SSH_PORT"
  server_validate_remote_path REMOTE_PROJECT_DIR "$REMOTE_PROJECT_DIR"

  SERVER_TARGET="$REMOTE_SSH_USER@$REMOTE_SSH_HOST"
  SERVER_SSH_ARGS=(
    -p "$REMOTE_SSH_PORT"
    -o "ConnectTimeout=$REMOTE_CONNECT_TIMEOUT"
    -o BatchMode=yes
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=3
  )
  if [[ -n "${REMOTE_SSH_IDENTITY_FILE:-}" ]]; then
    SERVER_SSH_ARGS+=(-i "$REMOTE_SSH_IDENTITY_FILE")
  fi
  if openalpha_is_true "$REMOTE_SSH_STRICT"; then
    SERVER_SSH_ARGS+=(-o StrictHostKeyChecking=accept-new)
  else
    SERVER_SSH_ARGS+=(-o StrictHostKeyChecking=yes)
  fi

  SERVER_RSYNC_SSH="ssh"
  local option
  for option in "${SERVER_SSH_ARGS[@]}"; do
    printf -v SERVER_RSYNC_SSH '%s %q' "$SERVER_RSYNC_SSH" "$option"
  done
  export SERVER_TARGET SERVER_RSYNC_SSH
}

server_run_local() {
  server_print_command "$@"
  if openalpha_is_true "${SERVER_DRY_RUN:-false}"; then
    return 0
  fi
  command "$@"
}

server_remote() {
  local remote_command=""
  local argument
  for argument in "$@"; do
    printf -v remote_command '%s %q' "$remote_command" "$argument"
  done
  server_print_command ssh "${SERVER_SSH_ARGS[@]}" "$SERVER_TARGET" "$remote_command"
  if openalpha_is_true "${SERVER_DRY_RUN:-false}"; then
    return 0
  fi
  command ssh "${SERVER_SSH_ARGS[@]}" "$SERVER_TARGET" "$remote_command"
}

server_remote_capture() {
  local remote_command=""
  local argument
  for argument in "$@"; do
    printf -v remote_command '%s %q' "$remote_command" "$argument"
  done
  command ssh "${SERVER_SSH_ARGS[@]}" "$SERVER_TARGET" "$remote_command"
}
