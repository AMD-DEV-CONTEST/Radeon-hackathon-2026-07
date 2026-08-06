"""Configuration for the diary app (local-first).

All values are overridable via environment so the same code runs on this box or in CI.
"""

from __future__ import annotations

import os

# Local LLM (llama.cpp, ROCm) — OpenAI-compatible API.
LLM_BASE_URL = os.getenv("DIARY_LLM_BASE_URL", "http://127.0.0.1:8089/v1")
LLM_API_KEY = os.getenv("DIARY_LLM_API_KEY", "local")  # llama-server ignores it
LLM_MODEL = os.getenv("DIARY_LLM_MODEL", "local")

# Bionic-Graph (Gremlin) — the diary's graph store.
GRAPH_URL = os.getenv("DIARY_GRAPH_URL", "http://127.0.0.1:8088")
GRAPH_NAME = os.getenv("DIARY_GRAPH_NAME", "diary")
