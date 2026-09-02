#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
secret_dir="$repo_root/.secrets"
mkdir -p "$secret_dir"
chmod 700 "$secret_dir"

grafana_password="$secret_dir/grafana-admin-password"
if [[ ! -s "$grafana_password" ]]; then
  umask 077
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 30 | tr -d '\n' > "$grafana_password"
  else
    python3 -c 'import secrets; print(secrets.token_urlsafe(30), end="")' > "$grafana_password"
  fi
  # Compose implements local secrets as bind mounts. The parent directory remains
  # private while the mounted file must be readable by Grafana's non-root user.
  chmod 644 "$grafana_password"
  echo "Created local Grafana administrator secret."
fi
chmod 644 "$grafana_password"

radeon_key="$secret_dir/radeon-model-api-key"
if [[ ! -e "$radeon_key" ]]; then
  umask 077
  : > "$radeon_key"
  chmod 644 "$radeon_key"
  echo "Created an empty Radeon API key file. Populate it only before championship mode."
fi
chmod 644 "$radeon_key"
