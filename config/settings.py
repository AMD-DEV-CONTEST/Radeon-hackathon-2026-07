import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


# --- Qwen API ---
QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL: str = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_LLM_MODEL: str = os.getenv("QWEN_LLM_MODEL", "qwen-plus")
QWEN_OMNI_MODEL: str = os.getenv("QWEN_OMNI_MODEL", "qwen3.5-omni-flash")

# --- Hunyuan API (backup) ---
HUNYUAN_API_KEY: str = os.getenv("HUNYUAN_API_KEY", "")
HUNYUAN_BASE_URL: str = os.getenv("HUNYUAN_BASE_URL", "")

# --- Neo4j ---
NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "test123456")

# --- Agent ---
MAX_CONVERSATION_HISTORY: int = int(os.getenv("MAX_CONVERSATION_HISTORY", "5"))
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1024"))

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- Paths ---
PROJECT_ROOT: Path = _PROJECT_ROOT
