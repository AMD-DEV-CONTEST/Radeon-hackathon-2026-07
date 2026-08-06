#!/usr/bin/env bash
# =============================================================================
# scripts/check_env.sh — RTL-Agent v2 pre-flight environment check
#
# Verifies that all required tools are installed before running on a paid
# GPU instance. Run this FIRST, before touching the demo or benchmark.
#
# Amendment 7: Checks verilator ≥5.x (required for --binary mode) and g++.
#
# Usage:
#   chmod +x scripts/check_env.sh
#   ./scripts/check_env.sh
#
# Exit code 0 = all checks passed; non-zero = at least one failure.
# =============================================================================

set -euo pipefail

PASS=0
FAIL=0
WARN=0

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
CYN='\033[0;36m'
RST='\033[0m'

ok()   { echo -e "  ${GRN}✓${RST} $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}✗${RST} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "  ${YLW}⚠${RST} $1"; WARN=$((WARN+1)); }
info() { echo -e "  ${CYN}ℹ${RST} $1"; }

echo ""
echo -e "${CYN}═══════════════════════════════════════════════════════════${RST}"
echo -e "${CYN}  RTL-Agent v2 — Pre-flight Environment Check              ${RST}"
echo -e "${CYN}═══════════════════════════════════════════════════════════${RST}"
echo ""

# ─── 1. Python ────────────────────────────────────────────────────────────────
echo "[ Python ]"
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
    ok "python3 found: $PY_VER"
    # Check ≥3.8
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 8 ]; then
        ok "Python version ≥3.8"
    else
        fail "Python ≥3.8 required (found $PY_VER)"
    fi
else
    fail "python3 not found"
fi
echo ""

# ─── 2. Verilator (critical — Amendment 7) ────────────────────────────────────
echo "[ Verilator ]"
if command -v verilator &>/dev/null; then
    VERI_VER=$(verilator --version 2>&1 | head -1 | awk '{print $2}')
    ok "verilator found: $VERI_VER"

    # Extract major version number
    VERI_MAJOR=$(echo "$VERI_VER" | cut -d. -f1)
    if [ "$VERI_MAJOR" -ge 5 ]; then
        ok "verilator ≥5.x confirmed — --binary mode supported"
    elif [ "$VERI_MAJOR" -eq 4 ]; then
        warn "verilator 4.x detected — --binary mode may not work (need ≥5.000)"
        warn "Install verilator ≥5.x:  sudo apt-get install -y verilator  (or build from source)"
        info "Check: https://verilator.org/guide/latest/install.html"
    else
        fail "verilator version $VERI_VER is too old. Tier 2 simulation will NOT work."
    fi

    # Verify --binary flag is recognized
    if verilator --help 2>&1 | grep -q "\-\-binary"; then
        ok "verilator --binary flag is available"
    else
        fail "verilator --binary flag NOT available in this build. Tier 2 will fail."
        info "Required: verilator ≥5.000 with C++ compilation support enabled"
    fi
else
    fail "verilator NOT FOUND — install with: sudo apt-get install -y verilator"
    info "For AMD cloud instances: sudo apt-get update && sudo apt-get install -y verilator"
    fail "Tier 1 AND Tier 2 will be non-functional without verilator"
fi
echo ""

# ─── 3. C++ compiler (required for verilator --binary) ────────────────────────
echo "[ C++ Compiler ]"
if command -v g++ &>/dev/null; then
    GPP_VER=$(g++ --version 2>&1 | head -1)
    ok "g++ found: $GPP_VER"
elif command -v clang++ &>/dev/null; then
    CLANG_VER=$(clang++ --version 2>&1 | head -1)
    ok "clang++ found (acceptable substitute): $CLANG_VER"
    warn "verilator may prefer g++. If Tier 2 compile fails, install: sudo apt-get install -y g++"
else
    fail "No C++ compiler found (g++ or clang++ required for verilator --binary)"
    fail "Install with: sudo apt-get install -y build-essential"
    info "Without a C++ compiler, verilator --binary compilation will FAIL"
fi

if command -v make &>/dev/null; then
    ok "make found"
else
    warn "make not found — may be needed for complex verilator builds"
    info "Install: sudo apt-get install -y build-essential"
fi
echo ""

# ─── 4. Python packages ───────────────────────────────────────────────────────
echo "[ Python Packages ]"
REQUIRED_PKGS=("fastapi" "uvicorn" "pydantic")
OPTIONAL_PKGS=("openai" "requests")

for pkg in "${REQUIRED_PKGS[@]}"; do
    if python3 -c "import $pkg" 2>/dev/null; then
        ok "Required: $pkg"
    else
        fail "Missing required package: $pkg  →  pip install -r requirements.txt"
    fi
done

for pkg in "${OPTIONAL_PKGS[@]}"; do
    if python3 -c "import $pkg" 2>/dev/null; then
        ok "Optional: $pkg"
    else
        warn "Optional package not installed: $pkg"
        if [ "$pkg" = "openai" ]; then
            info "openai required for MOCK_MODE=false (real vLLM mode)"
        fi
        if [ "$pkg" = "requests" ]; then
            info "requests makes benchmark/run_benchmark.py SSE streaming more reliable"
        fi
    fi
done
echo ""

# ─── 5. vLLM (only check if MOCK_MODE=false is intended) ─────────────────────
echo "[ vLLM / LLM Endpoint ]"
MOCK_MODE="${MOCK_MODE:-true}"
if [ "$MOCK_MODE" = "false" ]; then
    # Try to reach the vLLM endpoint
    VLLM_URL="${VLLM_BASE_URL:-http://localhost:8000/v1}"
    if curl -sf "${VLLM_URL}/models" &>/dev/null; then
        ok "vLLM endpoint reachable: $VLLM_URL"
    else
        fail "vLLM endpoint NOT reachable at $VLLM_URL"
        info "Start vLLM with: python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-Coder-7B-Instruct"
    fi
else
    ok "MOCK_MODE=true — vLLM endpoint not required"
fi
echo ""

# ─── 6. ROCm (AMD-specific, informational only) ───────────────────────────────
echo "[ AMD ROCm (informational) ]"
if command -v rocm-smi &>/dev/null; then
    ok "rocm-smi found — AMD GPU present"
    GPU_INFO=$(rocm-smi --showproductname 2>/dev/null | grep -i "GPU" | head -2 || true)
    if [ -n "$GPU_INFO" ]; then
        info "$GPU_INFO"
    fi
elif command -v nvidia-smi &>/dev/null; then
    warn "nvidia-smi found instead of rocm-smi — this is not an AMD ROCm system"
    warn "Track 2 requires AMD/ROCm hardware for judging compliance"
else
    warn "No GPU management tool found (rocm-smi / nvidia-smi)"
    info "On AMD cloud: verify ROCm is installed and GPU is attached"
fi
echo ""

# ─── Summary ──────────────────────────────────────────────────────────────────
echo -e "${CYN}═══════════════════════════════════════════════════════════${RST}"
echo -e "  Summary: ${GRN}${PASS} passed${RST}  ${YLW}${WARN} warnings${RST}  ${RED}${FAIL} failures${RST}"
echo -e "${CYN}═══════════════════════════════════════════════════════════${RST}"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}ENVIRONMENT NOT READY — fix the failures above before running on the GPU clock.${RST}"
    echo ""
    exit 1
elif [ "$WARN" -gt 0 ]; then
    echo -e "${YLW}Environment has warnings — review before using real mode on a paid GPU.${RST}"
    echo ""
    exit 0
else
    echo -e "${GRN}All checks passed. Environment is ready.${RST}"
    echo ""
    echo "Next steps:"
    echo "  1. Start the agent:   python agent_server.py"
    echo "  2. Test mock mode:    open http://localhost:7860"
    echo "  3. Rehearse benchmark: python benchmark/run_benchmark.py --mock"
    echo "  4. Switch to real:    MOCK_MODE=false python agent_server.py"
    echo ""
    exit 0
fi
