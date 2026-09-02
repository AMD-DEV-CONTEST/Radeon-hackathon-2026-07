"""
providers/local_ollama.py - Determinex Local Ollama Provider

Sends generation requests to a locally-running Ollama instance via its HTTP API.
This provider is ALWAYS enabled -- it is the zero-cost baseline teacher.

Model is passed in from the session_config (e.g., 'determinex-leviathan:v1').
If the model is not available locally, Ollama returns an error and we return None.
"""

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("oracle.provider.local_ollama")

_DEFAULT_BASE = "http://localhost:11434"


def generate(
    system: str,
    user: str,
    model: str,
    cot: bool = False,
    base_url: str = _DEFAULT_BASE,
) -> str | None:
    """
    Call Ollama /api/generate (non-streaming) with system + user prompts.

    Args:
        system:   System prompt for the teacher model.
        user:     User/task prompt.
        model:    Ollama model tag (e.g., 'determinex-leviathan:v1').
        cot:      If True, append a CoT reasoning trigger to the user prompt.
        base_url: Ollama HTTP base URL.

    Returns:
        Generated text string, or None on any failure.
    """
    prompt_text = user
    if cot:
        prompt_text = (
            f"{user}\n\n"
            "Think step by step before giving your final answer. "
            "Show your reasoning, then provide the complete solution."
        )

    # Build Ollama chat-style prompt using system + user turn
    full_prompt = f"[INST] <<SYS>>\n{system}\n<</SYS>>\n\n{prompt_text} [/INST]"

    payload = json.dumps(
        {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 2048,
            },
        }
    ).encode("utf-8")

    url = base_url.rstrip("/") + "/api/generate"

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            response_text = data.get("response", "").strip()
            if not response_text:
                log.warning("Ollama returned empty response for model=%s", model)
                return None
            return response_text

    except urllib.error.URLError as e:
        log.error("Ollama unreachable at %s: %s", url, e)
    except (json.JSONDecodeError, KeyError) as e:
        log.error("Ollama response parse error: %s", e)
    except Exception as e:
        log.error("Ollama unexpected error: %s", e)

    return None
