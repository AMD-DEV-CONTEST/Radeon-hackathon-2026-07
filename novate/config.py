"""
Central configuration for Nova, the Private Local Research Assistant.

All values can be overridden via environment variables (see .env.example).
Nothing here calls out to the network at runtime except the local
inference server, which itself runs on the same machine / AMD Radeon GPU.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a local `.env` file (see .env.example) into the process
# environment. Without this, every NOVA_* setting below silently falls back
# to its default no matter what's written in `.env`.
load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("NOVA_DATA_DIR", PROJECT_ROOT / "data" / "sample_docs"))
VECTOR_DB_DIR = Path(os.getenv("NOVA_VECTOR_DB_DIR", PROJECT_ROOT / "chroma_db"))
COLLECTION_NAME = os.getenv("NOVA_COLLECTION_NAME", "nova_knowledge_base")

# ---------------------------------------------------------------------------
# Local LLM server (llama.cpp server / vLLM, both expose an OpenAI-compatible
# /v1/chat/completions endpoint). This is the only network call Nova makes,
# and it targets localhost — the model itself runs on the AMD Radeon GPU.
# ---------------------------------------------------------------------------
LLM_SERVER_BASE_URL = os.getenv("NOVA_LLM_BASE_URL", "http://127.0.0.1:8080/v1")
LLM_MODEL_NAME = os.getenv("NOVA_LLM_MODEL_NAME", "local-model")
LLM_API_KEY = os.getenv("NOVA_LLM_API_KEY", "not-needed")  # local servers ignore this
LLM_TEMPERATURE = float(os.getenv("NOVA_LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS = int(os.getenv("NOVA_LLM_MAX_TOKENS", "512"))
LLM_TIMEOUT_S = int(os.getenv("NOVA_LLM_TIMEOUT_S", "120"))

# ---------------------------------------------------------------------------
# Embeddings (sentence-transformers, runs locally, GPU-accelerated via ROCm
# if a ROCm-enabled torch build is installed — see README).
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_NAME = os.getenv("NOVA_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDING_DEVICE = os.getenv("NOVA_EMBEDDING_DEVICE", "cuda")  # ROCm exposes itself as "cuda" to torch

# ---------------------------------------------------------------------------
# RAG retrieval
# ---------------------------------------------------------------------------
RAG_TOP_K = int(os.getenv("NOVA_RAG_TOP_K", "4"))
RAG_CHUNK_SIZE = int(os.getenv("NOVA_RAG_CHUNK_SIZE", "800"))
RAG_CHUNK_OVERLAP = int(os.getenv("NOVA_RAG_CHUNK_OVERLAP", "120"))

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
MEMORY_MAX_TURNS = int(os.getenv("NOVA_MEMORY_MAX_TURNS", "8"))

# ---------------------------------------------------------------------------
# Privacy / permission control
# Tools may only read files inside ALLOWED_TOOL_DIRS. This is Nova's
# "clear permission control & privacy protection mechanism".
# ---------------------------------------------------------------------------
ALLOWED_TOOL_DIRS = [DATA_DIR.resolve()]
ENABLE_SHELL_TOOL = os.getenv("NOVA_ENABLE_SHELL_TOOL", "false").lower() == "true"
