#!/bin/bash
# Refresh all PB intelligence artifacts in one shot.
# Run after every drain (or any time fresh eval.jsons arrive) to keep
# the matrix, action sheets, and corpus snippet library current.
#
# Usage: bash scripts/refresh_corpus_intel.sh
set -e

cd "$(dirname "$0")/.."
echo "=== 1/4 per-tool failure clusters ==="
python scripts/analysis/per_tool_failures.py
echo
echo "=== 2/4 200-tool work matrix ==="
python scripts/analysis/pb_work_matrix.py
echo
echo "=== 3/4 per-tool action sheets ==="
python scripts/analysis/pb_action_sheets.py
echo
echo "=== 4/4 corpus knowledge extractor ==="
python scripts/analysis/corpus_knowledge_extractor.py
echo
echo "=== refresh complete ==="
echo "Artifacts:"
echo "  corpus/programbench/results/PB_WORK_MATRIX_200.md"
echo "  corpus/programbench/results/action_sheets/*.md"
echo "  corpus/programbench/_snippets/transferable_patterns.md + registry.json"
echo "  c:/tmp/per_tool_failures.json"
echo "  c:/tmp/cross_tool_clusters.tsv"
