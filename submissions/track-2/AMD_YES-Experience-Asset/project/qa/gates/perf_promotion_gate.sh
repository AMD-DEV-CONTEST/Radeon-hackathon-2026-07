#!/usr/bin/env bash
# Mechanical evidence-admissibility gate. It never promotes by itself.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAN="${1:-}"
BASELINE="${2:-}"
CANDIDATE="${3:-}"
FAIL=0

if [ -z "$PLAN" ] || [ -z "$BASELINE" ] || [ -z "$CANDIDATE" ]; then
  echo "Usage: perf_promotion_gate.sh PLAN BASELINE_MANIFEST CANDIDATE_MANIFEST" >&2
  exit 2
fi

python3 "$ROOT/scripts/validate_candidate_plan.py" "$PLAN" || FAIL=1
python3 "$ROOT/scripts/validate_manifest.py" "$BASELINE" || FAIL=1
python3 "$ROOT/scripts/validate_manifest.py" "$CANDIDATE" || FAIL=1
python3 "$ROOT/scripts/compare_manifests.py" "$PLAN" "$BASELINE" "$CANDIDATE" || FAIL=1

if [ "$FAIL" -ne 0 ]; then
  echo "PERFORMANCE GATE: FAIL — evidence is not admissible/comparable"
  exit 1
fi

cat <<'TXT'
PERFORMANCE GATE: MECHANICAL PASS

Quality-owner decision still required:
- primary metric improves beyond run-to-run noise;
- task completion and evidence discipline do not regress;
- privacy, permission, confirmed state, and terminal failures remain correct;
- core inference remains on the W7900/ROCm path;
- public regressions and the private blind subset contain no Critical/High issue.

This script does not reveal or calculate private promotion thresholds.
TXT
