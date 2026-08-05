#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

python3 - <<'PY'
from app.policy.local_only import require_local_vllm_base_url

print(f"Validated base URL: {require_local_vllm_base_url()}")
PY

forbidden_pattern='api\.openai\.com|api\.deepseek\.com|dashscope|developer\.amd\.com\.cn/radeon/api|api-inference\.huggingface\.co'
scan_roots=(app benchmarks config scripts)

if command -v rg >/dev/null 2>&1; then
  scan_command=(rg -n -i "$forbidden_pattern" "${scan_roots[@]}" --glob '!verify_local_only.sh')
else
  scan_command=(grep -RInE --exclude=verify_local_only.sh "$forbidden_pattern" "${scan_roots[@]}")
fi

if "${scan_command[@]}"; then
  echo "ERROR: A public model endpoint pattern was found in runtime code/config." >&2
  exit 1
fi
echo "Runtime scan passed: no known public model endpoint found."

if [[ "${VERIFY_LISTENER:-1}" == "0" ]]; then
  echo "Listener check skipped by VERIFY_LISTENER=0."
  exit 0
fi

if command -v ss >/dev/null 2>&1; then
  listener="$(ss -ltnp 2>/dev/null | awk '$4 ~ /:8000$/ {print}')"
  if [[ -z "$listener" ]]; then
    echo "ERROR: no TCP listener found on port 8000." >&2
    exit 1
  fi
  printf '%s\n' "$listener"
  if printf '%s\n' "$listener" | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\*|\[::\]):8000'; then
    echo "ERROR: port 8000 is exposed beyond loopback." >&2
    exit 1
  fi
  echo "Listener check passed: port 8000 is loopback-only."
elif [[ -r /proc/net/tcp ]]; then
  python3 scripts/verify_loopback_listener.py 8000
else
  echo "ERROR: neither ss nor /proc/net/tcp is available for listener verification." >&2
  exit 1
fi
