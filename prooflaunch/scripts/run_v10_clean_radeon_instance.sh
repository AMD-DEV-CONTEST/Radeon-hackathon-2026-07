#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 ARCHIVE CHECKSUM_FILE TARGET_DIRECTORY" >&2
  exit 64
fi

archive_path="$1"
checksum_path="$2"
target_path="$3"

if [[ ! -f "$archive_path" || ! -f "$checksum_path" ]]; then
  echo "archive and checksum file are required" >&2
  exit 66
fi

if [[ -z "$target_path" || "$target_path" == "/" || "$target_path" == "$HOME" ]]; then
  echo "refusing broad extraction target" >&2
  exit 64
fi

container_digest="${PROOFLAUNCH_CONTAINER_DIGEST:-}"
digest_hex="${container_digest#sha256:}"
if [[ "$container_digest" != sha256:* || "${#digest_hex}" -ne 64 || "$digest_hex" == *[!0-9a-f]* ]]; then
  echo "PROOFLAUNCH_CONTAINER_DIGEST must be a lowercase SHA-256 supplied by the control plane" >&2
  exit 65
fi

expected_sha="$(awk 'NR == 1 {print $1}' "$checksum_path")"
if command -v sha256sum >/dev/null 2>&1; then
  observed_sha="$(sha256sum "$archive_path" | awk '{print $1}')"
else
  observed_sha="$(shasum -a 256 "$archive_path" | awk '{print $1}')"
fi

if [[ "$expected_sha" != "$observed_sha" ]]; then
  echo "archive SHA-256 mismatch" >&2
  exit 65
fi

mkdir -p "$target_path"
tar -xzf "$archive_path" -C "$target_path"
project_path="$target_path/prooflaunch_submission"

if [[ ! -f "$project_path/pyproject.toml" || ! -f "$project_path/scripts/run_v10_local_suite.py" ]]; then
  echo "archive did not produce the expected project root" >&2
  exit 65
fi

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export PROOFLAUNCH_NETWORK_ALLOWED=0
export PYTHONPATH="$project_path/src"

python "$project_path/scripts/run_v10_local_suite.py" \
  --output "$project_path/evidence/v10/local-test-report.clean-instance.json"
