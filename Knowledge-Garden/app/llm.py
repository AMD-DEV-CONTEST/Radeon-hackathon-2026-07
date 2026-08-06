"""llm.py — local OpenAI-compatible clients for the two vLLM endpoints.

Dialogue layer (14B AWQ)  -> FT_DIALOGUE_URL  (:8000), interactive
Batch layer (32B AWQ)     -> FT_BATCH_URL     (:8001), background extraction

Every call is LOCAL (127.0.0.1). No cloud API. Timeouts + single retry.
"""
from __future__ import annotations

import json
import os
import time

from openai import OpenAI

DIALOGUE_URL = os.environ.get("FT_DIALOGUE_URL", "http://127.0.0.1:8000/v1")
BATCH_URL = os.environ.get("FT_BATCH_URL", "http://127.0.0.1:8001/v1")
DIALOGUE_MODEL = os.environ.get("FT_DIALOGUE_MODEL", "Qwen2.5-14B-AWQ")
BATCH_MODEL = os.environ.get("FT_BATCH_MODEL", "Qwen2.5-32B-AWQ")

_dialogue = OpenAI(base_url=DIALOGUE_URL, api_key="local")
_batch = OpenAI(base_url=BATCH_URL, api_key="local")

TIMEOUT_S = 180  # 批处理层超时上限（防后台任务无限占显存）
MAX_RETRY = 1


def _chat(client, model, system, user, max_tokens, timeout_s=TIMEOUT_S, json_mode=False):
    """Single chat completion with bounded timeout and one retry."""
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
        timeout=timeout_s,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    last_err = None
    for attempt in range(MAX_RETRY + 1):
        t0 = time.time()
        try:
            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content or ""
            return {"ok": True, "content": content, "latency_s": round(time.time() - t0, 2)}
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0)
    return {"ok": False, "error": last_err}


def dialogue_chat(system: str, user: str, max_tokens: int = 1024, json_mode: bool = False) -> dict:
    return _chat(_dialogue, DIALOGUE_MODEL, system, user, max_tokens, json_mode=json_mode)


def batch_chat(system: str, user: str, max_tokens: int = 2048, json_mode: bool = True) -> dict:
    return _chat(_batch, BATCH_MODEL, system, user, max_tokens, json_mode=json_mode)
