"""
providers/openai_api.py - Determinex OpenAI Provider

Calls the OpenAI Chat Completions API.
Requires: DETERMINEX_API_OPENAI_ENABLED=true and OPENAI_API_KEY in .env
Install:  pip install openai
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("oracle.provider.openai_api")

_DEFAULT_MODEL = "gpt-4o"
_MAX_TOKENS = 2048


def _load_api_key() -> str | None:
    """Read OPENAI_API_KEY from environment or .env file."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
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
    Call OpenAI Chat Completions API.

    Args:
        system: System prompt.
        user:   User/task prompt.
        model:  OpenAI model string (e.g., 'gpt-4o', 'o3-mini').
        cot:    If True, append CoT reasoning trigger.

    Returns:
        Response text, or None on failure/missing credentials.
    """
    api_key = _load_api_key()
    if not api_key:
        log.error("OPENAI_API_KEY not set -- cannot use OpenAI provider")
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
            "Think through this carefully and step by step. "
            "Show your reasoning, then give the complete final answer."
        )

    try:
        client = OpenAI(api_key=api_key)
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
            log.warning("OpenAI returned empty response for model=%s", model)
            return None
        log.debug(
            "OpenAI: model=%s  tokens=%d",
            model,
            completion.usage.total_tokens if completion.usage else 0,
        )
        return text.strip()

    except AuthenticationError:
        log.error("OpenAI API key is invalid or expired")
    except RateLimitError:
        log.warning("OpenAI rate limit hit")
    except APIError as e:
        log.error("OpenAI API error: %s", e)
    except Exception as e:
        log.error("OpenAI unexpected error: %s", e)

    return None
