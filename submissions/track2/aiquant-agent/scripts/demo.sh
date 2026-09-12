#!/bin/bash
# aiQuant Demo Script — for video recording
# Usage: bash scripts/demo.sh
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_BASE="http://localhost:8010"

echo "=== aiQuant Demo ==="
echo ""

# 1. Check AMD GPU
echo "[1] Checking AMD Radeon GPU..."
rocm-smi | head -20
echo ""

# 2. Check LLM server
echo "[2] Checking LLM server (Qwen3-8B on AMD GPU)..."
curl -s http://localhost:13305/v1/models | python3 -m json.tool 2>/dev/null || \
    echo "  LLM server not ready. Start with: lemonade serve <model_path> --host 0.0.0.0 --port 13305"
echo ""

# 3. Check aiQuant API
echo "[3] Checking aiQuant API..."
curl -s "$API_BASE/api/health" | python3 -m json.tool 2>/dev/null || \
    echo "  API not ready. Start with: bash scripts/start.sh"
echo ""

# 4. Send demo factor mining request
echo "[4] Sending factor mining request..."
echo "    Universe: CSI 300"
echo "    Iterations: 1"
echo ""
curl -N -X POST "$API_BASE/api/research/factor-evolve/stream" \
    -H "Content-Type: application/json" \
    -d '{
        "loop_n": 1,
        "universe": "沪深300",
        "all_duration": "30m"
    }' 2>/dev/null | while IFS= read -r line; do
    # Pretty print SSE events
    if [[ "$line" == data:* ]]; then
        echo "$line" | python3 -c "
import sys, json
line = sys.stdin.read().strip()
if line.startswith('data: '):
    try:
        d = json.loads(line[6:])
        t = d.get('type','')
        s = d.get('stage','')
        e = d.get('elapsed_sec','')
        c = d.get('content','')[:120]
        print(f'[{e:>6}s] {t:20s} | {s:20s} | {c}')
    except: pass
" 2>/dev/null
    fi
done

echo ""
echo "=== Demo Complete ==="
echo "Visualization: http://localhost:19899"
