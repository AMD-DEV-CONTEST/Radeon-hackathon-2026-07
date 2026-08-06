#!/usr/bin/env bash
set -u -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
PYTHON_BIN="${YIJIAN_CLOUD_PYTHON:-$PERSIST_ROOT/venv/bin/python}"
KATAGO="${YIJIAN_KATAGO_BIN:-$PERSIST_ROOT/katago-v1.16.5/build/katago}"
KATAGO_MODEL="${YIJIAN_KATAGO_MODEL:-$PERSIST_ROOT/katago-models/kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz}"
KATAGO_CONFIG="${YIJIAN_KATAGO_CONFIG:-$PROJECT_ROOT/deploy/cloud/katago_analysis_w7900.cfg}"
OUTPUT_ROOT="$PERSIST_ROOT/benchmarks/qwen3-14b-coexist"
UTILIZATIONS=(0.72 0.75 0.78)

for path in "$PYTHON_BIN" "$KATAGO" "$KATAGO_MODEL" "$KATAGO_CONFIG"; do
  [[ -e "$path" ]] || { echo "缺少共存压测前置制品：$path" >&2; exit 2; }
done
mkdir -p "$OUTPUT_ROOT"
passed=()
failed=()
for utilization in "${UTILIZATIONS[@]}"; do
  echo "=== vLLM gpu-memory-utilization=$utilization ==="
  bash "$SCRIPT_DIR/stop_qwen3_14b_agent.sh" || exit $?
  if YIJIAN_VLLM_GPU_MEMORY_UTILIZATION="$utilization" \
      bash "$SCRIPT_DIR/start_qwen3_14b_agent.sh" && \
    YIJIAN_VLLM_GPU_MEMORY_UTILIZATION="$utilization" \
      "$PYTHON_BIN" "$SCRIPT_DIR/stress_qwen3_katago_coexist.py" \
        --katago "$KATAGO" \
        --katago-model "$KATAGO_MODEL" \
        --katago-config "$KATAGO_CONFIG" \
        --cycles 30 --p95-limit 12 \
        --vllm-log "$PERSIST_ROOT/logs/qwen3-14b-agent-8083.log" \
        --output "$OUTPUT_ROOT/util-$utilization.json"; then
    passed+=("$utilization")
  else
    failed+=("$utilization")
  fi
done
bash "$SCRIPT_DIR/stop_qwen3_14b_agent.sh" || true

"$PYTHON_BIN" - "$OUTPUT_ROOT/summary.json" "${passed[*]}" "${failed[*]}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output = Path(sys.argv[1])
passed = sys.argv[2].split()
failed = sys.argv[3].split()
value = {
    "schemaVersion": "yijian-w7900-coexist-matrix-v1",
    "createdAt": datetime.now(timezone.utc).isoformat(),
    "passed": bool(passed),
    "recommendedGpuMemoryUtilization": min(map(float, passed)) if passed else None,
    "passingProfiles": passed,
    "failedProfiles": failed,
    "profileReports": [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(output.parent.glob("util-*.json"))
    ],
}
output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(value, ensure_ascii=False))
PY

[[ ${#passed[@]} -gt 0 ]] || exit 4
echo "共存矩阵完成；优先锁定最低通过档 ${passed[0]}。"
