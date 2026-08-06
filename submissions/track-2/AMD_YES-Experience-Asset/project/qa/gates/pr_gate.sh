#!/usr/bin/env bash
# Fast public gate. Contract mode works before product code. Artifact mode is
# fail-closed and requires a real canonical asset, fixture id, and progress.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
MODE=""
ASSET=""
FIXTURE_ID=""
PROGRESS=""
RETRIEVAL_TRACE=""
REQUIRE_PR_METADATA=0
FAIL=0

usage() {
  cat <<'TXT'
Usage:
  pr_gate.sh --mode contract [--require-pr-metadata]
  pr_gate.sh --mode artifact --asset FILE --fixture-id ID --progress FILE [--retrieval-trace FILE] [--require-pr-metadata]
TXT
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --asset) ASSET="${2:-}"; shift 2 ;;
    --fixture-id) FIXTURE_ID="${2:-}"; shift 2 ;;
    --progress) PROGRESS="${2:-}"; shift 2 ;;
    --retrieval-trace) RETRIEVAL_TRACE="${2:-}"; shift 2 ;;
    --require-pr-metadata) REQUIRE_PR_METADATA=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "FAIL: unknown argument $1" >&2; usage; exit 2 ;;
  esac
done

if [ "$MODE" != "contract" ] && [ "$MODE" != "artifact" ]; then
  echo "FAIL: --mode must be contract or artifact" >&2
  usage
  exit 2
fi

echo "=== repository disclosure and credential boundary ==="
PRIVATE_PATH='(^|/)(\.qa-private|private-qa|benchmarks/private|benchmarks/hidden|data/quality-owner-private)(/|$)'
SECRET_PATTERN='sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|AKIA[0-9A-Z]{16}'
while IFS= read -r -d '' relative; do
  case "$relative" in official/*) continue ;; esac
  if printf '%s\n' "$relative" | grep -Eq "$PRIVATE_PATH"; then
    echo "FAIL: quality-owner-only path would be included: $relative"
    FAIL=1
  fi
  if [ -f "$REPO/$relative" ] && grep -IHnE "$SECRET_PATTERN" "$REPO/$relative" 2>/dev/null; then
    echo "FAIL: credential-like content exists in $relative"
    FAIL=1
  fi
done < <(git -C "$REPO" ls-files -z --cached --others --exclude-standard)
[ "$FAIL" -eq 0 ] && echo "PASS: no credential-like content or quality-owner-only path is included"

echo "=== public fixture contract ==="
python3 "$ROOT/scripts/check_fixture_inventory.py" || FAIL=1

if [ "$REQUIRE_PR_METADATA" -eq 1 ]; then
  echo "=== PR metadata ==="
  python3 "$ROOT/scripts/check_pr_metadata.py" || FAIL=1
fi

if [ "$MODE" = "artifact" ]; then
  echo "=== product artifact conformance ==="
  if [ -z "$ASSET" ] || [ -z "$FIXTURE_ID" ] || [ -z "$PROGRESS" ]; then
    echo "FAIL: artifact mode requires --asset, --fixture-id, and --progress"
    FAIL=1
  elif [ ! -f "$ROOT/expected/$FIXTURE_ID.expected.json" ]; then
    echo "FAIL: unregistered public fixture id: $FIXTURE_ID"
    FAIL=1
  else
    python3 "$ROOT/scripts/check_asset_schema.py" "$ASSET" \
      --expected "$ROOT/expected/$FIXTURE_ID.expected.json" || FAIL=1
    python3 "$ROOT/scripts/check_progress_invariants.py" "$PROGRESS" || FAIL=1
    if [ -n "$RETRIEVAL_TRACE" ]; then
      python3 "$ROOT/scripts/check_retrieval_phase.py" "$RETRIEVAL_TRACE" || FAIL=1
    fi
  fi
else
  echo "INFO: contract mode does not claim product ACs have passed"
fi

echo "=== result ==="
if [ "$FAIL" -ne 0 ]; then
  echo "PR GATE: FAIL"
  exit 1
fi
echo "PR GATE: PASS ($MODE mode)"
