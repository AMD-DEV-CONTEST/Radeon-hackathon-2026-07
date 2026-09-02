"""Local LLM runtime adapter (Ollama)."""
import requests, logging
from services.llm_provider import OllamaProvider

log = logging.getLogger(__name__)

def get_local_provider(config: dict):
    """Return an Ollama provider instance."""
    return OllamaProvider(
        base_url=config.get("api_base", "http://localhost:11434"),
        model=config.get("model", "qwen2.5"),
    )

def check_runtime(base_url: str = "http://localhost:11434") -> dict:
    """Check if Ollama is running and list available models."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            return {"running": True, "models": models, "model_count": len(models)}
        return {"running": False, "error": f"HTTP {resp.status_code}"}
    except requests.ConnectionError:
        return {"running": False, "error": "Connection refused"}
    except Exception as e:
        return {"running": False, "error": str(e)}

def pull_model(model_name: str, base_url: str = "http://localhost:11434") -> dict:
    """Pull a model via Ollama API."""
    try:
        resp = requests.post(f"{base_url}/api/pull", json={"name": model_name}, timeout=300)
        return {"success": resp.status_code == 200, "model": model_name}
    except Exception as e:
        return {"success": False, "error": str(e)}

def test_connection(config: dict) -> dict:
    """Test local provider with a simple prompt."""
    try:
        provider = get_local_provider(config)
        resp = provider.chat([{"role": "user", "content": "Respond with exactly: OK"}], max_tokens=10)
        return {"success": True, "response": resp.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}
