#!/bin/bash
# Quick verification for judges/reviewers -- runs the three checks that
# back this submission's core claims, in order, and stops at the first
# failure. Default build only: no API keys, no network, no GPU toolchain
# beyond a Vulkan driver, no model download. Everything here is the
# default `cargo build --release` path.
#
#   1. builds clean (release profile)
#   2. 42 property-based tests pass
#   3. the 6-query demo runs fully offline (tool routing via the GPU
#      BM25 kernel, zero LLM / zero network)
#
# Usage:  bash verify.sh     (Linux/macOS/Git-Bash)

set -e
cd "$(dirname "$0")"

line() { printf '%s\n' "------------------------------------------------------------"; }

line
echo "audiocast/genomic-agent quick verification"
echo "(default build -- no API keys, no network, no model download)"
line

echo "[1/3] Building (cargo build --release)..."
cargo build --release
echo "    OK: build succeeded"
echo

echo "[2/3] Running tests (cargo test --release)..."
cargo test --release
echo "    OK: tests passed"
echo

echo "[3/3] Running the offline demo (cargo run --release -- fast)..."
echo "      6 queries, routed by the GPU BM25 kernel, no LLM/network."
cargo run --release -- fast
echo "    OK: demo completed"
echo

line
echo "All three checks passed."
echo "See README_PROFESSIONAL.md sections 4-5 for gpu-bench and"
echo "the optional local-inference feature."
line
