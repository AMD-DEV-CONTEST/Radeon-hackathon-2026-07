"""Model configuration profiles for common task types."""

DEFAULT_PROFILES = {
    "deepseek-chat": {
        "provider": "deepseek",
        "api_base": "https://api.deepseek.com/v1",
        "context_window": 65536,
        "suitable_for": ["quick_import", "chapter_analysis", "book_summary", "conflict_check"],
    },
    "gpt-4o": {
        "provider": "openai",
        "api_base": "https://api.openai.com/v1",
        "context_window": 128000,
        "suitable_for": ["chapter_analysis", "creative_assist", "conflict_check"],
    },
    "qwen2.5": {
        "provider": "ollama",
        "api_base": "http://localhost:11434",
        "context_window": 32768,
        "suitable_for": ["quick_import", "chapter_split", "entity_extract", "relation_extract"],
    },
}

def get_profiles() -> dict:
    return dict(DEFAULT_PROFILES)

def get_profile(model_name: str) -> dict:
    return DEFAULT_PROFILES.get(model_name, {})
