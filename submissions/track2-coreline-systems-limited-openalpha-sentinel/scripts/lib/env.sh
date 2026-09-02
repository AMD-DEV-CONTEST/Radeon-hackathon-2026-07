#!/usr/bin/env bash

# Shared dotenv loader for Bash entrypoints. The env files are deliberately
# shell-compatible so the same file can also be consumed by python-dotenv.
openalpha_load_env() {
  local root_dir="${1:?repository root is required}"
  local purpose="${2:-runtime}"
  local requirement="${3:-optional}"
  local env_file="${OPENALPHA_ENV_FILE:-}"

  if [[ -n "$env_file" && "$env_file" != /* ]]; then
    env_file="$root_dir/$env_file"
  fi

  if [[ -z "$env_file" ]]; then
    if [[ "$purpose" == "server" ]]; then
      [[ -f "$root_dir/.env.server" ]] && env_file="$root_dir/.env.server"
    else
      [[ -f "$root_dir/.env" ]] && env_file="$root_dir/.env"
    fi
  fi

  if [[ -z "$env_file" || ! -f "$env_file" ]]; then
    if [[ "$requirement" == "required" ]]; then
      if [[ "$purpose" == "server" ]]; then
        echo "Server configuration not found. Copy .env.example to .env.server." >&2
      else
        echo "Runtime configuration not found: ${env_file:-$root_dir/.env}" >&2
      fi
      return 1
    fi
    return 0
  fi

  if [[ "$purpose" == "server" ]]; then
    local permissions=""
    permissions="$(stat -f '%Lp' "$env_file" 2>/dev/null || stat -c '%a' "$env_file" 2>/dev/null || true)"
    permissions="${permissions: -3}"
    if [[ "$permissions" =~ ^[0-7]{3}$ ]] && (( (8#$permissions & 077) != 0 )); then
      echo "Server configuration must not be group/world-readable: $env_file" >&2
      echo "Run: chmod 600 '$env_file'" >&2
      return 1
    fi
  fi

  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  OPENALPHA_LOADED_ENV_FILE="$env_file"
  export OPENALPHA_LOADED_ENV_FILE
}

openalpha_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

openalpha_require_commands() {
  local command_name
  local missing=0
  for command_name in "$@"; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
      echo "Required command is unavailable: $command_name" >&2
      missing=1
    fi
  done
  [[ "$missing" -eq 0 ]]
}
