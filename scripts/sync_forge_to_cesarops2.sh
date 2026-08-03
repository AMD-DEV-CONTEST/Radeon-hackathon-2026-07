#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${1:-10.0.0.201}"
REMOTE_USER="${REMOTE_USER:-cesarops}"
REMOTE_BASE="${REMOTE_BASE:-/home/cesarops/cesarops_push}"
LOCAL_BASE="${LOCAL_BASE:-/home/cesarops/cesarops_push}"

echo "[sync] ${LOCAL_BASE} -> ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}"

ssh -o BatchMode=yes -o ConnectTimeout=6 "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_BASE}/forge_src' '${REMOTE_BASE}/scripts'"

rsync -az --delete \
  "${LOCAL_BASE}/forge_src/" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}/forge_src/"

rsync -az \
  "${LOCAL_BASE}/forge_cluster_config.toml" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}/forge_cluster_config.toml"

rsync -az \
  "${LOCAL_BASE}/scripts/" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}/scripts/"

echo "[sync] done"
