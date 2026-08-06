#!/usr/bin/env bash
# Generate a public milestone sign-off draft after deterministic checks.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MILESTONE="${1:-}"
shift || true
ASSET=""
FIXTURE_ID=""
PROGRESS=""
RETRIEVAL_TRACE=""
OUTPUT=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --asset) ASSET="${2:-}"; shift 2 ;;
    --fixture-id) FIXTURE_ID="${2:-}"; shift 2 ;;
    --progress) PROGRESS="${2:-}"; shift 2 ;;
    --retrieval-trace) RETRIEVAL_TRACE="${2:-}"; shift 2 ;;
    --output) OUTPUT="${2:-}"; shift 2 ;;
    *) echo "FAIL: unknown argument $1" >&2; exit 2 ;;
  esac
done

case "$MILESTONE" in M1|M2|M3|M4|M5) ;; *) echo "FAIL: milestone must be M1..M5" >&2; exit 2 ;; esac
case "$MILESTONE" in
  M4|M5)
    if [ -z "$RETRIEVAL_TRACE" ]; then
      echo "FAIL: $MILESTONE requires --retrieval-trace to verify AC-30" >&2
      exit 2
    fi
    ;;
esac
if [ -z "$OUTPUT" ]; then
  OUTPUT="/tmp/${MILESTONE,,}-signoff-$(date -u +%Y%m%dT%H%M%SZ).md"
fi

GATE_ARGS=(--mode artifact --asset "$ASSET" --fixture-id "$FIXTURE_ID" --progress "$PROGRESS")
if [ -n "$RETRIEVAL_TRACE" ]; then
  GATE_ARGS+=(--retrieval-trace "$RETRIEVAL_TRACE")
fi
bash "$ROOT/gates/pr_gate.sh" "${GATE_ARGS[@]}"

mkdir -p "$(dirname "$OUTPUT")"
cat >"$OUTPUT" <<EOF
# $MILESTONE quality sign-off draft

- Fixture: $FIXTURE_ID
- Public deterministic gate: PASS
- Affected AC: <fill from PR/evidence pack>
- Public runtime/E2E evidence: <path or run id>
- Retrieval-phase evidence (required for M4/M5): ${RETRIEVAL_TRACE:-N/A}
- Private blind result: <quality owner fills locally; never attach details>
- Blocking Critical/High defects: <none or public failure class>
- Conditional Medium defects: <owner + residual risk + deadline>
- Performance evidence/delta: <N/A or manifest/report>
- Decision: <PROMOTE or HOLD>
- Quality owner and UTC timestamp: <fill>
EOF
echo "PASS: sign-off draft created at $OUTPUT"
echo "NEXT: quality owner runs the private blind subset and fills only the result class."
