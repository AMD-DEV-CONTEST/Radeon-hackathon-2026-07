"""
config.py — Central configuration for the RTL Verification Agent v2.

═══════════════════════════════════════════════════════════════
 DEPLOYMENT MODES  (single env-var switch: DEPLOY_MODE)
═══════════════════════════════════════════════════════════════

 DEPLOY_MODE       │ LLM Endpoint                        │ Notes
 ──────────────────┼─────────────────────────────────────┼──────────────────────
 "mock"            │ None (pre-scripted)                 │ Zero deps, CI, demo
 ──────────────────┼─────────────────────────────────────┼──────────────────────
 "deepseek"        │ api.deepseek.com                    │ ✅ RECOMMENDED for dev
                   │ Model: deepseek-coder               │ Real, documented API,
                   │ Key:   DEEPSEEK_API_KEY             │ inexpensive.
 ──────────────────┼─────────────────────────────────────┼──────────────────────
 "amd-api"         │ developer.amd.com.cn/radeon/api/v1  │ ⚠ VERIFY FIRST — AMD
                   │ Model: Qwen/Qwen2.5-Coder-7B-Instruct│ may provide $100
                   │ Key:   AMD_API_KEY                  │ cloud credits, not a
                   │                                     │ hosted inference API.
 ──────────────────┼─────────────────────────────────────┼──────────────────────
 "amd-deepseek"    │ developer.amd.com.cn/radeon/api/v1  │ ⚠ Same caveat
                   │ Model: deepseek-coder               │
 ──────────────────┼─────────────────────────────────────┼──────────────────────
 "vllm"            │ localhost:8000/v1 (or VLLM_BASE_URL)│ FINAL SUBMISSION.
                   │ Model: Qwen/Qwen2.5-Coder-7B-Instruct│ Local GPU inference
                   │ Key:   VLLM_API_KEY                 │ on AMD ROCm via vLLM.

 Switch (Linux/Mac):     export DEPLOY_MODE=deepseek
 Switch (PowerShell):    $env:DEPLOY_MODE = "deepseek"

═══════════════════════════════════════════════════════════════
 SAFETY GUARDRAILS
═══════════════════════════════════════════════════════════════
 • MOCK_MODE=false promotes to "deepseek", NOT "amd-api".
   Set DEPLOY_MODE=vllm explicitly on the AMD cloud instance —
   never rely on auto-promotion for the final submission.
 • Runtime warnings fire if a key is missing or if vllm points
   to a non-localhost URL (would silently corrupt ROCm numbers).

═══════════════════════════════════════════════════════════════
 ROCm / vLLM OPTIMIZATION KNOBS  (40-pt rubric bucket)
═══════════════════════════════════════════════════════════════
 ENABLE_PREFIX_CACHING   — KV-block reuse for shared prefixes
 GPU_MEMORY_UTILIZATION  — fraction of VRAM for KV cache (0-1)
 MAX_NUM_SEQS            — concurrent decode sequences
 QUANTIZATION            — '' | 'awq' | 'gptq'
 VLLM_DTYPE              — 'float16' | 'bfloat16' | 'auto'
 TENSOR_PARALLEL_SIZE    — GPUs for tensor parallelism
"""

import os
import sys
from pathlib import Path

# ─── Canonical Model ──────────────────────────────────────────────────────────
# Global model used for vllm and amd-api modes.
# Updated from Qwen3.6-35B-A3B (legacy) to match local vLLM deployment.
_CANONICAL_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"

# ─── Deployment Mode ──────────────────────────────────────────────────────────
DEPLOY_MODE: str = os.getenv("DEPLOY_MODE", "mock").lower().strip()

# Backward compat: MOCK_MODE=true → "mock",  MOCK_MODE=false → "deepseek"
# IMPORTANT: false → "deepseek" (verified), NOT "amd-api" (unverified).
# Set DEPLOY_MODE=vllm explicitly on AMD cloud — never rely on this auto-promotion.
_mock_env = os.getenv("MOCK_MODE", "").lower()
if _mock_env in ("true", "1", "yes"):
    DEPLOY_MODE = "mock"
elif _mock_env in ("false", "0", "no") and DEPLOY_MODE == "mock":
    DEPLOY_MODE = "deepseek"

MOCK_MODE: bool = (DEPLOY_MODE == "mock")

# ─── API Endpoint Definitions ─────────────────────────────────────────────────
_ENDPOINTS = {
    # ── ✅ RECOMMENDED for local dev: DeepSeek Coder ──────────────────────────
    # Fully documented, inexpensive, elite RTL code generation.
    # Get key: https://platform.deepseek.com/api_keys
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model":    "deepseek-coder",
        "api_key":  os.getenv("DEEPSEEK_API_KEY", ""),
    },

    # ── ⚠ AMD Developer Portal API — verify endpoint exists before using ──────
    # AMD hackathon compute = $100 credits for self-hosted vLLM on MI300X.
    # It may NOT be a standing managed inference API with a portal key.
    # Verify: https://www.amd.com/en/developer/resources/rocm-hub/ai-devmaster.html
    "amd-api": {
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "model":    _CANONICAL_MODEL,
        "api_key":  os.getenv("AMD_API_KEY", ""),
    },
    "amd-deepseek": {
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "model":    "deepseek-coder",          # same deepseek-coder via AMD endpoint
        "api_key":  os.getenv("AMD_API_KEY", ""),
    },

    # ── LOCAL vLLM on AMD ROCm — FINAL SUBMISSION ─────────────────────────────
    # MUST set DEPLOY_MODE=vllm explicitly on the AMD instance.
    # Do NOT rely on MOCK_MODE=false auto-promotion for this mode.
    "vllm": {
        "base_url": os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
        "model":    os.getenv("MODEL_NAME",    _CANONICAL_MODEL),
        "api_key":  os.getenv("VLLM_API_KEY",  "token-rtl-agent"),
    },
}


def _resolve_endpoint():
    """
    Pick endpoint config for the current DEPLOY_MODE.
    Explicit env-var overrides always win over mode defaults.
    """
    if DEPLOY_MODE in _ENDPOINTS:
        ep       = _ENDPOINTS[DEPLOY_MODE]
        base_url = ep["base_url"]
        api_key  = ep["api_key"]
        model    = ep["model"]
    else:
        # Unknown mode — fall back to direct env vars
        base_url = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
        api_key  = os.getenv("VLLM_API_KEY",  "token-rtl-agent")
        model    = os.getenv("MODEL_NAME",     _CANONICAL_MODEL)

    # Explicit env-var overrides (win over mode defaults)
    if os.getenv("VLLM_BASE_URL"):
        base_url = os.getenv("VLLM_BASE_URL")
    if os.getenv("VLLM_API_KEY"):
        api_key  = os.getenv("VLLM_API_KEY")
    if os.getenv("MODEL_NAME"):
        model    = os.getenv("MODEL_NAME")

    # Key-specific overrides (highest priority)
    if DEPLOY_MODE == "deepseek" and os.getenv("DEEPSEEK_API_KEY"):
        api_key = os.getenv("DEEPSEEK_API_KEY")
    if DEPLOY_MODE in ("amd-api", "amd-deepseek") and os.getenv("AMD_API_KEY"):
        api_key = os.getenv("AMD_API_KEY")

    return base_url, api_key, model


VLLM_BASE_URL, VLLM_API_KEY, MODEL_NAME = _resolve_endpoint()

MAX_TOKENS:  int   = int(os.getenv("MAX_TOKENS",   "4096"))
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.05"))  # near-zero = deterministic RTL

# ─── Agent Iteration Limits ───────────────────────────────────────────────────
MAX_LINT_ITERATIONS:       int = int(os.getenv("MAX_LINT_ITERATIONS",       "5"))
MAX_FUNCTIONAL_ITERATIONS: int = int(os.getenv("MAX_FUNCTIONAL_ITERATIONS", "5"))
MAX_TOTAL_ITERATIONS:      int = int(os.getenv("MAX_TOTAL_ITERATIONS",      "10"))
MAX_ITERATIONS:            int = MAX_LINT_ITERATIONS   # backward-compat alias

VERILATOR_TIMEOUT:  int = int(os.getenv("VERILATOR_TIMEOUT",  "30"))
SIMULATION_TIMEOUT: int = int(os.getenv("SIMULATION_TIMEOUT", "30"))

# ─── AMD ROCm / vLLM Optimization Settings ───────────────────────────────────
ENABLE_PREFIX_CACHING:  bool  = os.getenv("ENABLE_PREFIX_CACHING", "true").lower() in ("true","1","yes")
GPU_MEMORY_UTILIZATION: float = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.90"))
MAX_NUM_SEQS:           int   = int(os.getenv("MAX_NUM_SEQS",          "64"))
QUANTIZATION:           str   = os.getenv("QUANTIZATION", "")
VLLM_DTYPE:             str   = os.getenv("VLLM_DTYPE",   "float16")
TENSOR_PARALLEL_SIZE:   int   = int(os.getenv("TENSOR_PARALLEL_SIZE", "1"))

# ─── Server ───────────────────────────────────────────────────────────────────
SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "7860"))

# ─── Filesystem ───────────────────────────────────────────────────────────────
BASE_DIR:      Path = Path(__file__).parent
WORKSPACE_DIR: Path = BASE_DIR / "workspace"
FRONTEND_DIR:  Path = BASE_DIR / "frontend"
LOGS_DIR:      Path = BASE_DIR / "logs"
WAVEFORMS_DIR: Path = LOGS_DIR / "waveforms"
WORKSPACE_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
WAVEFORMS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Runtime Safety Warnings ──────────────────────────────────────────────────
def _emit_warnings() -> None:
    """
    Emit stderr warnings for configurations that could silently produce wrong
    results — missing keys, unverified endpoints, non-local vLLM URLs.
    """
    if DEPLOY_MODE in ("amd-api", "amd-deepseek") and not VLLM_API_KEY:
        print(
            "\n[RTL-AGENT ⚠ WARNING] DEPLOY_MODE=amd-api but AMD_API_KEY is not set.\n"
            "  Verify the AMD Developer Portal provides a hosted inference API first.\n"
            "  If it provides cloud credits (not a managed API), use DEPLOY_MODE=deepseek.\n"
            "  AMD hackathon: https://www.amd.com/en/developer/resources/rocm-hub/ai-devmaster.html\n",
            file=sys.stderr,
        )
    if DEPLOY_MODE == "deepseek" and not VLLM_API_KEY:
        print(
            "\n[RTL-AGENT ⚠ WARNING] DEPLOY_MODE=deepseek but DEEPSEEK_API_KEY is not set.\n"
            "  Get a key at: https://platform.deepseek.com/api_keys\n",
            file=sys.stderr,
        )
    if DEPLOY_MODE == "vllm" and \
            "localhost" not in VLLM_BASE_URL and "127.0.0.1" not in VLLM_BASE_URL:
        print(
            f"\n[RTL-AGENT ⚠ WARNING] DEPLOY_MODE=vllm but VLLM_BASE_URL={VLLM_BASE_URL!r}\n"
            "  is not a localhost address. For the 40-pt ROCm criterion, vLLM must run\n"
            "  locally on the AMD GPU instance. Remote URL = TTFT numbers not from local GPU.\n",
            file=sys.stderr,
        )


# ─── Startup Banner ───────────────────────────────────────────────────────────
def print_config() -> None:
    """Print resolved configuration at startup -- called by agent_server.py."""
    _emit_warnings()

    _mode_labels = {
        "mock":         "MOCK (demo -- no LLM calls)",
        "deepseek":     "DeepSeek API - deepseek-coder  [OK] recommended for dev",
        "amd-api":      f"AMD Portal API - {_CANONICAL_MODEL}  [!] verify endpoint",
        "amd-deepseek": "AMD Portal API - deepseek-coder  [!] verify endpoint",
        "vllm":         f"LOCAL vLLM on AMD ROCm - {MODEL_NAME}  (final submission)",
    }
    label = _mode_labels.get(DEPLOY_MODE, f"CUSTOM ({DEPLOY_MODE})")

    _key_display = "--"
    if not MOCK_MODE and VLLM_API_KEY:
        _key_display = ("***" + VLLM_API_KEY[-4:]) if len(VLLM_API_KEY) > 6 else "(set)"

    print("=" * 68)
    print("  RTL Verification Agent v2 -- Two-Tier Verification Loop")
    print(f"  Deploy : {label}")
    print(f"  Model  : {MODEL_NAME}")
    if not MOCK_MODE:
        print(f"  URL    : {VLLM_BASE_URL}")
        print(f"  Key    : {_key_display}")
    print(f"  Limits : Lint={MAX_LINT_ITERATIONS} / Sim={MAX_FUNCTIONAL_ITERATIONS} / Total={MAX_TOTAL_ITERATIONS}")
    if DEPLOY_MODE == "vllm":
        print(f"  ROCm   : prefix_cache={ENABLE_PREFIX_CACHING}  gpu_mem={GPU_MEMORY_UTILIZATION}  seqs={MAX_NUM_SEQS}")
        if QUANTIZATION:
            print(f"  Quant  : {QUANTIZATION}")
    print("=" * 68)
