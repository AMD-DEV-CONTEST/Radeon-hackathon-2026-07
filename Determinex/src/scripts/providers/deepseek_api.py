"""
providers/deepseek_api.py - Determinex DeepSeek Cloud Provider

Calls the DeepSeek cloud API (api.deepseek.com), which uses an OpenAI-compatible
interface. This is distinct from running DeepSeek locally via Ollama (local_ollama).

Requires: DETERMINEX_API_DEEPSEEK_ENABLED=true and DEEPSEEK_API_KEY in .env
Install:  pip install openai  (reuses OpenAI SDK with a different base_url)

Pricing (approx, April 2026): ~$0.14/M tokens cache hit, ~$0.27/M cache miss.
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("oracle.provider.deepseek_api")

_DEFAULT_MODEL = "deepseek-chat"  # DeepSeek-V3 (their flagship)
_DEEPSEEK_BASE = "https://api.deepseek.com"
_MAX_TOKENS = 2048


def _load_api_key() -> str | None:
    """Read DEEPSEEK_API_KEY from environment or .env file."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    return None


def generate(
    system: str,
    user: str,
    model: str = _DEFAULT_MODEL,
    cot: bool = False,
) -> str | None:
    """
    Call DeepSeek cloud API (OpenAI-compatible interface).

    Args:
        system: System prompt.
        user:   User/task prompt.
        model:  DeepSeek model string (e.g., 'deepseek-chat', 'deepseek-coder').
        cot:    If True, append CoT reasoning trigger.

    Returns:
        Response text, or None on failure/missing credentials.
    """
    api_key = _load_api_key()
    if not api_key:
        log.error("DEEPSEEK_API_KEY not set -- cannot use DeepSeek cloud provider")
        return None

    try:
        from openai import APIError, AuthenticationError, OpenAI, RateLimitError
    except ImportError:
        log.error("openai package not installed. Run: pip install openai")
        return None

    prompt_text = user
    if cot:
        prompt_text = (
            f"{user}\n\n"
            "Think through this step by step. Show your reasoning, "
            "then provide the complete answer."
        )

    try:
        client = OpenAI(api_key=api_key, base_url=_DEEPSEEK_BASE)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt_text},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=0.3,
        )
        text = completion.choices[0].message.content or ""
        if not text.strip():
            log.warning("DeepSeek API returned empty response")
            return None
        log.debug(
            "DeepSeek: model=%s  tokens=%d",
            model,
            completion.usage.total_tokens if completion.usage else 0,
        )
        return text.strip()

    except AuthenticationError:
        log.error("DeepSeek API key is invalid or expired")
    except RateLimitError:
        log.warning("DeepSeek rate limit hit")
    except APIError as e:
        log.error("DeepSeek API error: %s", e)
    except Exception as e:
        log.error("DeepSeek unexpected error: %s", e)

    return None
