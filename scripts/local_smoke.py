"""Local developer smoke test script for Bunker.

Verifies active inference configuration, checks Ollama health endpoint if
backend is set to 'ollama', and tests main service imports without requiring
heavy model downloads or external cloud connections.
"""

import sys
import os
from pathlib import Path
import logging
import urllib.request
import json

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_config
from src.dspy_runtime import BUNKER_LM

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("local_smoke")

def check_ollama_health() -> bool:
    """Verify Ollama server health via local HTTP API."""
    try:
        url = "http://localhost:11434/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                logger.info(f"Ollama server is healthy. Installed models: {models}")
                return True
    except Exception as e:
        logger.warning(f"Ollama health check warning: {e}")
        return False

def main():
    config = get_config()
    backend = getattr(config.inference, "backend", "vllm")
    logger.info("=== Bunker Local Developer Smoke Test ===")
    logger.info(f"Active Backend: {backend}")
    logger.info(f"Ollama Model: {config.inference.ollama_model}")
    logger.info(f"Ollama Base URL: {config.inference.ollama_base_url}")
    logger.info(f"vLLM Primary Model: {config.inference.primary_model}")
    logger.info(f"DSPy LM Model String: {BUNKER_LM.model}")
    logger.info(f"DSPy LM API Base: {BUNKER_LM.kwargs.get('api_base')}")

    if backend.lower() == "ollama":
        healthy = check_ollama_health()
        if not healthy:
            logger.warning("Ollama server at http://localhost:11434 is not responding.")
            logger.warning("To run live Ollama tests, start Ollama and run: 'ollama pull qwen3:0.6b'.")

    try:
        import src.main as main_app
        logger.info("Main application module (src.main) imported successfully.")
    except Exception as e:
        logger.error(f"Failed to import main application module: {e}")
        sys.exit(1)

    logger.info("Local smoke check passed cleanly.")
    sys.exit(0)

if __name__ == "__main__":
    main()
