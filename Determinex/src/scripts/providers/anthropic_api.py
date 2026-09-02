"""
providers/anthropic_api.py - Determinex Anthropic (Claude) Provider

Calls the Anthropic Messages API using the anthropic SDK.
Requires: DETERMINEX_API_ANTHROPIC_ENABLED=true and ANTHROPIC_API_KEY set in .env

If the SDK is not installed or the key is missing, returns None gracefully.
Install: pip install anthropic
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("oracle.provider.anthropic_api")

# Default model -- Oracle will pass the session-specific model string
_DEFAULT_MODEL = "claude-sonnet-4-5"
_MAX_TOKENS = 2048


def _load_api_key() -> str | None:
    """Read ANTHROPIC_API_KEY from environment or .env file."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
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
    Call Anthropic Messages API (Claude).

    Args:
        system: System prompt.
        user:   User/task prompt.
        model:  Anthropic model string (e.g., 'claude-sonnet-4-5').
        cot:    If True, append CoT reasoning trigger to user prompt.

    Returns:
        Response text, or None on failure/missing credentials.
    """
    api_key = _load_api_key()
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set -- cannot use Anthropic provider")
        return None

    try:
        import anthropic
    except ImportError:
        log.error("anthropic package not installed. Run: pip install anthropic")
        return None

    prompt_text = user
    if cot:
        prompt_text = (
            f"{user}\n\n"
            "Think through this step by step. Show your reasoning process "
            "explicitly, then provide the complete final answer."
        )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt_text}],
        )
        text = message.content[0].text if message.content else ""
        if not text.strip():
            log.warning("Anthropic API returned empty response for model=%s", model)
            return None
        log.debug(
            "Anthropic: model=%s  input_tokens=%d  output_tokens=%d",
            model,
            message.usage.input_tokens,
            message.usage.output_tokens,
        )
        return text.strip()

    except anthropic.AuthenticationError:
        log.error("Anthropic API key is invalid or expired")
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit hit -- backing off")
    except anthropic.APIError as e:
        log.error("Anthropic API error: %s", e)
    except Exception as e:
        log.error("Anthropic unexpected error: %s", e)

    return None
