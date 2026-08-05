#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

OUTPUT_DIR=${1:-$RADEONNAV_ROOT/outputs/neupan-dune}
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR=$(cd "$OUTPUT_DIR" && pwd)

# DUNE derives its checkpoint directory from sys.path[0]. Run a copied driver
# so a retraining run never overwrites the bundled reference checkpoint.
cp "$RADEONNAV_ROOT/NeuPAN/example/dune_train_go2/dune_train_go2.py" "$OUTPUT_DIR/"
cp "$RADEONNAV_ROOT/NeuPAN/example/dune_train_go2/dune_train_go2.yaml" "$OUTPUT_DIR/"

cd "$OUTPUT_DIR"
run_python "$OUTPUT_DIR/dune_train_go2.py"

