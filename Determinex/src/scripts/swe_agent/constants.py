"""
swe_agent/constants.py — All configuration constants for the SWE-bench agent.

Everything that was previously scattered across the top of determinex_swebench_agent.py.
Evaluated at import time — env vars must be set before the first import of this module.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse as _urlparse

# ── Role models ───────────────────────────────────────────────────────────────
BUILDER_MODEL = os.getenv("DETERMINEX_BUILDER_MODEL", "determinex-engineer-v11-dsl")
OBSERVER_MODEL = os.getenv("DETERMINEX_OBSERVER_MODEL", "determinex-observer-v6-dsl")

# ── Solve loop limits ─────────────────────────────────────────────────────────
MAX_RETRIES = int(os.getenv("DETERMINEX_MAX_RETRIES", "3"))
MAX_FILES = int(os.getenv("DETERMINEX_MAX_FILES", "8"))
CTX_LINES = int(os.getenv("DETERMINEX_CTX_LINES", "120"))
TEST_TIMEOUT = int(os.getenv("DETERMINEX_TEST_TIMEOUT", "60"))

# Phase 1: multi-path temperatures — low/mid/high variance
TEMPERATURES = [0.1, 0.4, 0.7]
VRAM_PARALLEL_THRESHOLD_MB = int(os.getenv("DETERMINEX_PARALLEL_VRAM_MB", "16000"))

# ── Compile gate schedule ─────────────────────────────────────────────────────
# 3 attempts: precision → moderate → broadening.
# Duplicate T=0.1 and high-variance T=0.4 both removed (see loop trim commit).
_GATE_TEMPS = [0.1, 0.2, 0.3]
_GATE_MAX_AUTO = 3
_GATE_MAX_TOTAL = 3

# Skip native tests — generate predictions only, Docker harness scores them.
SKIP_NATIVE_TESTS = bool(os.getenv("DETERMINEX_SKIP_NATIVE_TESTS", ""))

# Sentinel: model produced no <<<SEARCH...>>>REPLACE blocks (distinct from "" = blocks found but none matched)
_NO_BLOCKS_SENTINEL = "\x00NO_BLOCKS\x00"

# ── Local Builder (privacy-sovereign) ─────────────────────────────────────────
USE_LOCAL_BUILDER = bool(os.getenv("DETERMINEX_LOCAL_BUILDER"))
LOCAL_BUILDER_MODEL = os.getenv(
    "DETERMINEX_LOCAL_BUILDER_MODEL", "qwen2.5-coder:14b-instruct-q4_K_M"
)
LOCAL_BUILDER_SWARM = int(os.getenv("DETERMINEX_LOCAL_SWARM", "1"))

# ── Language metadata ─────────────────────────────────────────────────────────
_LANG_DISPLAY: dict[str, str] = {
    "python": "Python",
    "ruby": "Ruby",
    "php": "PHP",
    "c": "C",
    "cpp": "C++",
    "go": "Go",
    "rust": "Rust",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
}

_LANG_EXT: dict[str, str] = {
    "python": ".py",
    "ruby": ".rb",
    "php": ".php",
    "c": ".c",
    "cpp": ".cpp",
    "go": ".go",
    "rust": ".rs",
    "java": ".java",
    "javascript": ".js",
    "typescript": ".ts",
}

_LANG_EXTS: dict[str, list[str]] = {
    "python": ["*.py"],
    "java": ["*.java"],
    "go": ["*.go"],
    "rust": ["*.rs"],
    "javascript": ["*.js", "*.ts"],
    "typescript": ["*.ts", "*.js"],
    "ruby": ["*.rb"],
    "c": ["*.c", "*.h"],
    "cpp": ["*.cpp", "*.cc", "*.cxx", "*.hpp", "*.h"],
    "php": ["*.php"],
}

_LANG_COMMENT: dict[str, str] = {
    "python": "#",
    "ruby": "#",
    "php": "//",
    "c": "//",
    "cpp": "//",
    "go": "//",
    "rust": "//",
    "java": "//",
    "javascript": "//",
    "typescript": "//",
}

_LANG_FENCE: dict[str, str] = {
    "python": "python",
    "ruby": "ruby",
    "php": "php",
    "c": "c",
    "cpp": "cpp",
    "go": "go",
    "rust": "rust",
    "java": "java",
    "javascript": "javascript",
    "typescript": "typescript",
}

_LANG_COMPILE: dict[str, list[str]] = {
    "python": [sys.executable, "-m", "py_compile", "{file}"],
    "ruby": [],
    "php": ["php", "-l", "{file}"],
    "c": [],  # in-place make handled by _run_compile_check; isolated tmpfile has no project includes
    "cpp": [],  # same
    "go": [],  # handled by in-place build in _check_fixed_syntax
    "rust": [],  # cargo check in _compile_gate
    "java": [],  # maven in _compile_gate
    "javascript": [],
    "typescript": ["tsc", "--noEmit", "--strict", "{file}"],
}

# ── Ollama endpoint (SSRF-guarded) ────────────────────────────────────────────
_OLLAMA_URL_RAW = os.getenv("DETERMINEX_OLLAMA_URL", "http://localhost:11434")
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
_parsed_host = _urlparse.urlparse(_OLLAMA_URL_RAW).hostname or ""
if _parsed_host not in _ALLOWED_HOSTS:
    raise ValueError(
        f"DETERMINEX_OLLAMA_URL host '{_parsed_host}' is not allowed. "
        "Only localhost/127.0.0.1 are permitted to prevent SSRF."
    )
OLLAMA_URL = _OLLAMA_URL_RAW

# ── Inference backend routing ─────────────────────────────────────────────────
_INFERENCE_BACKEND = os.getenv("DETERMINEX_INFERENCE_BACKEND", "ollama").lower()
_ARCHITECT_BACKEND = os.getenv("DETERMINEX_ARCHITECT_BACKEND", "").lower()
_BUILDER_BACKEND = os.getenv("DETERMINEX_BUILDER_BACKEND", "").lower()

_VLLM_URL = os.getenv("DETERMINEX_VLLM_URL", "http://localhost:8000/v1")
_VLLM_MODEL = os.getenv("DETERMINEX_VLLM_MODEL", "Qwen/Qwen2.5-Coder-7B-Instruct")

_DEEPSEEK_KEY = os.getenv("DETERMINEX_DEEPSEEK_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
_DEEPSEEK_BUILDER_MODEL = os.getenv("DETERMINEX_DEEPSEEK_BUILDER_MODEL", "deepseek-v4-flash")
_DEEPSEEK_ARCHITECT_MODEL = os.getenv("DETERMINEX_DEEPSEEK_ARCHITECT_MODEL", "deepseek-v4-pro")
# Legacy single-model override — if set, applies to both roles (backwards compat)
_DEEPSEEK_MODEL = os.getenv("DETERMINEX_DEEPSEEK_MODEL", "")
_DEEPSEEK_URL = "https://api.deepseek.com/v1"

_ANTHROPIC_KEY = os.getenv("DETERMINEX_ANTHROPIC_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
_ANTHROPIC_MODEL = os.getenv("DETERMINEX_ANTHROPIC_MODEL", "claude-sonnet-4-6")
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_OPENAI_KEY = os.getenv("DETERMINEX_OPENAI_KEY", os.getenv("OPENAI_API_KEY", ""))
_OPENAI_MODEL = os.getenv("DETERMINEX_OPENAI_MODEL", "gpt-4.1")
_OPENAI_URL = os.getenv("DETERMINEX_OPENAI_URL", "https://api.openai.com/v1")

_GEMINI_KEY = os.getenv("DETERMINEX_GEMINI_KEY", os.getenv("GEMINI_API_KEY", ""))
_GEMINI_MODEL = os.getenv("DETERMINEX_GEMINI_MODEL", "gemini-2.5-pro")
# Gemini's OpenAI-compatible endpoint
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# Task-vector → LoRA adapter name
_DEFAULT_LORA_MAP: dict[str, str] = {
    "data_structure": "",
    "concurrency": "",
    "error_handling": "",
    "api_boundary": "",
    "algorithm": "determinex-engineer-dsl",
    "refactor": "determinex-engineer-dsl",
    "test_harness": "",
}
try:
    _TASK_VECTOR_TO_LORA: dict[str, str] = json.loads(
        os.getenv("DETERMINEX_LORA_MAP", json.dumps(_DEFAULT_LORA_MAP))
    )
except Exception:
    _TASK_VECTOR_TO_LORA = _DEFAULT_LORA_MAP
