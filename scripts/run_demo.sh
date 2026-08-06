#!/bin/bash
# scripts/run_demo.sh - CodeRisk Agent Demo Script
# For AMD AI DevMaster Hackathon Track 2

set -e

echo "=========================================="
echo "  CodeRisk Agent - Demo"
echo "  AMD AI DevMaster Hackathon Track 2"
echo "=========================================="
echo ""

# 1. Environment Check
echo "[1/5] Environment Check"
echo "----------------------------------------"
if command -v rocm-smi &> /dev/null; then
    echo "ROCm detected:"
    rocm-smi --showproductname 2>/dev/null | head -3 || echo "  (rocm-smi available but limited in container)"
else
    echo "ROCm not available (CPU-only mode)"
fi
echo "Python: $(python3 --version)"
echo ""

# 2. Quick Demo (Static Analysis)
echo "[2/5] Static Analysis Demo (no LLM)"
echo "----------------------------------------"
cd "$(dirname "$0")/.."
python3 main.py demo
echo ""

# 3. Full Analysis on Test Cases
echo "[3/5] Full Analysis on Test Cases"
echo "----------------------------------------"
python3 main.py analyze tests/test_cases/ --no-ai --output terminal
echo ""

# 4. Version Info
echo "[4/5] System Info"
echo "----------------------------------------"
python3 main.py info
echo ""

# 5. Summary
echo "[5/5] Summary"
echo "----------------------------------------"
echo "CodeRisk Agent features:"
echo "  - Agent 1: Static Analyzer (regex + Tree-sitter + Semgrep)"
echo "  - Agent 2: Semantic Analyzer (LLM-driven)"
echo "  - Agent 3: Deep Verifier (triple cross-validation + memory)"
echo "  - Agent 4: Report Generator (JSON/Markdown/Rich/SARIF)"
echo "  - Orchestrator: State machine pipeline"
echo "  - Memory Layer: Learn from history"
echo "  - CVE Client: NVD database lookup"
echo ""
echo "Demo complete!"
