"""Cloud LLM provider adapter (OpenAI / DeepSeek / Qwen / Custom)."""
from services.llm_provider import OpenAIProvider

_PROVIDER_CACHE = {}

def get_cloud_provider(provider_name: str, config: dict):
    """Return a cached cloud provider instance."""
    key = f"cloud_{provider_name}"
    if key not in _PROVIDER_CACHE:
        prov_cfg = config.get("providers", {}).get(provider_name, {})
        _PROVIDER_CACHE[key] = OpenAIProvider(
            api_base=prov_cfg.get("api_base", "https://api.openai.com/v1"),
            api_key=prov_cfg.get("api_key"),
            model=prov_cfg.get("model", "gpt-4o"),
        )
    return _PROVIDER_CACHE[key]

def test_connection(provider_name: str, config: dict) -> dict:
    """Test cloud provider connectivity."""
    try:
        provider = get_cloud_provider(provider_name, config)
        resp = provider.chat([{"role": "user", "content": "Respond with exactly: OK"}], max_tokens=10)
        return {"success": True, "response": resp.strip(), "provider": provider_name}
    except Exception as e:
        return {"success": False, "error": str(e), "provider": provider_name}
