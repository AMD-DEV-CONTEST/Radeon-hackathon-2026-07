#!/bin/bash
# ROCm delta harness — run inside Radeon Cloud instance after SSH access is granted
# This file is for reference / automation; actual execution requires instance running.

set -euo pipefail

echo "[delta] Starting Caprigo ROCm harness..."
echo "[delta] Cloud: Radeon (credits remaining: 10 at time of file creation)"
echo "[delta] Target backend: vLLM / Ollama on ROCm (TBD — set via env)"

# Placeholders for the before/after measurement
# 1. Launch backend (vLLM serve or ollama serve) — user must choose
# 2. Set CAPRIGO_LLM_PROVIDER / URL / MODEL
# 3. Run bench_agent_delta equivalent
# 4. Output CSV to artifacts/
# 5. Update docs/AMD.md results table

echo "[delta] Harness prepared but NOT executed yet — instance not launched by assistant (no SSH/browser access without user-provided command)."
echo "[delta] See Caprigo/docs/AMD.md section 3 for manual steps."
