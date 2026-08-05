"""
providers — Determinex Teacher Provider Adapters
==============================================
DATA ENGINE ONLY. These adapters are used exclusively by deepseek_data_engine.py
to generate teacher-student training pairs. They are NOT used by the main
inference pipeline (determinex_hive.py, executor.py, determinex_swebench_agent.py),
which routes through hive/api_client.py via LiteLLM instead.

Each module exposes a single function:

    generate(system: str, user: str, model: str, cot: bool) -> str | None

Returns the teacher's response text, or None on failure.
Failures are logged but never raise — the engine falls back to the next ranked teacher.

Provider modules:
    local_ollama   — Ollama HTTP API (always available, zero cost)
    anthropic_api  — Claude via Anthropic SDK (requires DETERMINEX_API_ANTHROPIC_ENABLED=true)
    google_api     — Gemini via Google GenerativeAI SDK (requires DETERMINEX_API_GOOGLE_ENABLED=true)
    deepseek_api   — DeepSeek cloud API (requires DETERMINEX_API_DEEPSEEK_ENABLED=true)
    openai_api     — OpenAI API (requires DETERMINEX_API_OPENAI_ENABLED=true)
"""

from .anthropic_api import generate as anthropic_generate
from .deepseek_api import generate as deepseek_generate
from .google_api import generate as google_generate
from .local_ollama import generate as local_ollama_generate
from .openai_api import generate as openai_generate

PROVIDER_MAP = {
    "local_ollama": local_ollama_generate,
    "api_anthropic": anthropic_generate,
    "api_google": google_generate,
    "api_deepseek": deepseek_generate,
    "api_openai": openai_generate,
}

__all__ = ["PROVIDER_MAP"]
