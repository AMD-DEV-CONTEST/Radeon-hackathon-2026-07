"""
providers/google_api.py - Determinex Google (Gemini) Provider

Calls the Google Generative AI API using the google-generativeai SDK.
Requires: DETERMINEX_API_GOOGLE_ENABLED=true and GOOGLE_API_KEY set in .env

If the SDK is not installed or the key is missing, returns None gracefully.
Install: pip install google-generativeai
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("oracle.provider.google_api")

_DEFAULT_MODEL = "gemini-2.5-pro-preview-03-25"
_MAX_TOKENS = 2048


def _load_api_key() -> str | None:
    """Read GOOGLE_API_KEY from environment or .env file."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GOOGLE_API_KEY="):
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
    Call Google Generative AI API (Gemini).

    Args:
        system: System prompt (injected as the first turn with role 'model' preamble).
        user:   User/task prompt.
        model:  Gemini model string (e.g., 'gemini-2.5-pro-preview-03-25').
        cot:    If True, append CoT reasoning trigger to user prompt.

    Returns:
        Response text, or None on failure/missing credentials.
    """
    api_key = _load_api_key()
    if not api_key:
        log.error("GOOGLE_API_KEY not set -- cannot use Google provider")
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        log.error("google-generativeai package not installed. Run: pip install google-generativeai")
        return None

    prompt_text = user
    if cot:
        prompt_text = (
            f"{user}\n\n"
            "Think through this problem carefully and step by step. "
            "Show your reasoning, then give the complete final answer."
        )

    try:
        genai.configure(api_key=api_key)

        generation_config = genai.GenerationConfig(
            max_output_tokens=_MAX_TOKENS,
            temperature=0.3,
        )

        gemini_model = genai.GenerativeModel(
            model_name=model,
            system_instruction=system,
            generation_config=generation_config,
        )

        response = gemini_model.generate_content(prompt_text)
        text = response.text.strip() if response.text else ""

        if not text:
            log.warning("Google API returned empty response for model=%s", model)
            return None

        return text

    except Exception as e:
        # google-generativeai raises various exceptions; catch broadly and log
        err_type = type(e).__name__
        if "quota" in str(e).lower() or "rate" in str(e).lower():
            log.warning("Google API rate limit or quota exceeded: %s", e)
        elif "key" in str(e).lower() or "auth" in str(e).lower():
            log.error("Google API authentication error: %s", e)
        else:
            log.error("Google API error (%s): %s", err_type, e)

    return None
