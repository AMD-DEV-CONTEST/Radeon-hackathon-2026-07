"""
LLM / GPU Service Health Check.
Probes an OpenAI-compatible endpoint for reachability and model info.
"""

import os
import json
import urllib.request


def check_llm_health(base_url: str | None = None) -> dict:
    """Check if the LLM endpoint is reachable and return available models.

    Args:
        base_url: LLM service URL. Defaults to env LLM_BASE_URL or
                  http://localhost:8000/v1.

    Returns:
        dict with keys: reachable, base_url, models, error
    """
    base_url = base_url or os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
    result: dict = {"reachable": False, "base_url": base_url, "models": [], "error": None}
    try:
        req = urllib.request.Request(f"{base_url}/models", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            result["reachable"] = True
            result["models"] = [m.get("id", "?") for m in data.get("data", [])]
    except Exception as e:
        result["error"] = str(e)
    return result
