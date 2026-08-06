import os

import requests


def call_openrouter_api_with_messages(
    messages, model=None, max_tokens=None, debug=False, api_key=None
):
    """Call OpenRouter chat completions and return the response text.

    Args:
        messages: Chat messages.
        model: Model name (default: $MODEL env var).
        max_tokens: Max tokens in response.
        debug: If True, print debug info.
        api_key: OpenRouter API key (falls back to OPENROUTER_API_KEY env var).

    Returns:
        Response text content.
    """
    if not api_key:
        api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise Exception(
            "OPENROUTER_API_KEY not provided. Set it in the frontend or "
            "in the OPENROUTER_API_KEY environment variable."
        )

    if model is None:
        model = os.getenv("MODEL")
    if not model:
        raise Exception(
            "MODEL not specified. Set MODEL env var or pass model= parameter."
        )

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = {"model": model, "messages": messages}
    if max_tokens is not None:
        data["max_tokens"] = max_tokens

    resp = requests.post(url, headers=headers, json=data, timeout=(5, 120))
    if not resp.ok:
        raise Exception(
            f"OpenRouter API error: HTTP {resp.status_code}\n{resp.text[:1000]}"
        )

    body = resp.json()
    msg = body.get("choices", [{}])[0].get("message", {})
    content = msg.get("content") or msg.get("reasoning") or ""
    if not content:
        raise Exception(f"Empty response from model {model}")
    return content.strip()
