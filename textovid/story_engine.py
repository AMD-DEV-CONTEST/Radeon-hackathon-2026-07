# -*- coding: utf-8 -*-
"""Textovid — Story engine powered by Qwen LLM via Radeon Cloud API"""

import json
import re
import requests
from config import LLM_API_URL, LLM_API_KEY, LLM_MODEL, PANELS_PER_PAGE


SYSTEM_PROMPT = """You are a comic-book writer. Given a user prompt, generate a JSON
array of exactly {n} panel descriptions for a single comic page.
Each element must have:
  - "panel": integer (1-based)
  - "caption": a short narration text (may be empty string)
  - "dialogue": what the character says (may be empty string)
  - "sfx": a sound-effect word like BOOM, CRASH, WHOOSH (may be empty string)
  - "image_prompt": a detailed Stable-Diffusion prompt in English (60-100 words)
     describing the scene for AI image generation
  - "style": one of ["manga", "superhero", "noir", "watercolor", "pixel"]

Return ONLY valid JSON, no markdown fences."""


def generate_panels(user_prompt: str, style_hint: str = "") -> list[dict]:
    """Call the Qwen LLM and return a list of panel dicts."""
    if not LLM_API_KEY:
        # Fallback: return generic panels so the app still works
        return _fallback_panels(user_prompt, style_hint)

    system = SYSTEM_PROMPT.format(n=PANELS_PER_PAGE)
    user_msg = f"Create a comic page about: {user_prompt}"
    if style_hint:
        user_msg += f"\nPreferred visual style: {style_hint}"

    try:
        resp = requests.post(
            LLM_API_URL,
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.8,
                "max_tokens": 2048,
            },
            timeout=120,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]

        # Strip markdown fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)

        panels = json.loads(text)
        if not isinstance(panels, list):
            panels = [panels]
        return panels[:PANELS_PER_PAGE]
    except Exception as exc:
        print(f"[story_engine] LLM call failed: {exc}")
        return _fallback_panels(user_prompt, style_hint)


def _fallback_panels(prompt: str, style: str) -> list[dict]:
    """Deterministic fallback when the API is unreachable."""
    style = style or "superhero"
    return [
        {
            "panel": i + 1,
            "caption": f"Panel {i+1} — {prompt[:60]}",
            "dialogue": "",
            "sfx": "",
            "image_prompt": (
                f"A {style}-style comic panel illustrating: {prompt}. "
                f"Panel {i+1} of {PANELS_PER_PAGE}. High detail, dramatic lighting."
            ),
            "style": style,
        }
        for i in range(PANELS_PER_PAGE)
    ]
