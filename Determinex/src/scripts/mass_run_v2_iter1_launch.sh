#!/bin/bash
# Iter 1 launch sequence — fires the moment mass_run_v2_base completes.
#
# Provenance contract: every cross-run delta (base → iter1 → iter2) must be
# anchored by a complete meta event in the ledger BEFORE eval starts.
# Pre-record + a post-pack update capture both intent and byte-level proof.
set -euo pipefail

DETERMINEX_ROOT="${DETERMINEX_ROOT:-/c/Dev/Determinex}"
ITER_OUT="T:/determinex-programbench/mass_run_v2_iter1"
PB_DIR="T:/Dev/ProgramBench"
RUN_ID="mass_run_v2_iter1"
BASE_RUN_ID="mass_run_v2_base"
SCAFFOLD_VERSION="clap_unknown_arg_v1"
PATCH_FAMILY="rc_2_unknown_option"

cd "$DETERMINEX_ROOT"

echo "[iter1] $(date -Iseconds) — scaffolding into $ITER_OUT"
DETERMINEX_PB_SCAFFOLD_OUT="$ITER_OUT" python3 scripts/mass_run_v2_scaffold.py

echo "[iter1] $(date -Iseconds) — packing submissions"
DETERMINEX_PB_SCAFFOLD_OUT="$ITER_OUT" python3 scripts/mass_run_v2_pack.py

# Pick the first packaged submission as the representative artifact for byte-level
# proof of what actually shipped (the pre-flight meta only had scaffold_sha256).
REPRESENTATIVE_ARTIFACT="$(ls "$ITER_OUT"/*/submission.tar.gz 2>/dev/null | head -n 1 || true)"
if [ -z "$REPRESENTATIVE_ARTIFACT" ]; then
    echo "[iter1] ERROR — no submission.tar.gz produced; aborting before eval."
    exit 1
fi
echo "[iter1] $(date -Iseconds) — representative artifact: $REPRESENTATIVE_ARTIFACT"

# Append the second meta event — overlays the pre-staged meta with the real
# artifact sha. query_run_meta() picks the most-recent record automatically.
python3 scripts/run_ledger.py --record-run-meta \
  --run-id "$RUN_ID" \
  --base-run-id "$BASE_RUN_ID" \
  --scaffold-version "$SCAFFOLD_VERSION" \
  --patch-family "$PATCH_FAMILY" \
  --output-root "$ITER_OUT" \
  --representative-artifact "$REPRESENTATIVE_ARTIFACT" \
  --notes "Post-pack meta. Submissions packed; ready for official eval. Pre-staged meta now superseded with byte-level proof."

echo "[iter1] $(date -Iseconds) — running official eval through resource guard profile (workers=1, branch-workers=1, docker-cpus=2)"
cd "$PB_DIR"
PYTHONUTF8=1 uv run programbench eval "$ITER_OUT" --workers 1 --branch-workers 1 --docker-cpus 1 --force 2>&1 \
  | tee "$DETERMINEX_ROOT/logs/mass_run_v2/iter1_$(date +%Y%m%d_%H%M).log"

cd "$DETERMINEX_ROOT"

echo "[iter1] $(date -Iseconds) — backfilling eval JSONs into ledger"
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from run_ledger import backfill_programbench_eval_jsons
from pathlib import Path
n = backfill_programbench_eval_jsons(run_id='$RUN_ID', eval_root=Path('$ITER_OUT'))
print(f'[iter1] backfilled {n} eval JSONs')
"

echo "[iter1] $(date -Iseconds) — final cockpit snapshot"
python3 scripts/programbench_live_monitor.py --run-id "$RUN_ID" --advise
