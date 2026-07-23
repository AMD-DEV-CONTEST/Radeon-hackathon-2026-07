"""
Textovid — Story Engine
Generates structured comic scripts via the free Qwen / DeepSeek API.
Zero GPU cost — runs entirely through the Radeon Cloud Model API.
"""

import json
import re
import requests
from typing import Optional
import config


# ════════════════════════════════════════════════════════════════════════
#   SYSTEM PROMPT
# ════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are a world-class comic book writer and visual storyteller. Your task is to \
generate COMPLETELY UNIQUE, original comic scripts. Every output must be fresh — \
never reuse plots, characters, or settings from existing comics, movies, or books.

You MUST respond with valid JSON ONLY. No markdown fences, no explanation, just raw JSON.

The JSON schema is:
{
  "title": "string — the comic title",
  "synopsis": "string — 2-3 sentence synopsis",
  "characters": [
    {"name": "string", "role": "string", "visual_description": "detailed appearance for AI image generation"}
  ],
  "pages": [
    {
      "page_number": 1,
      "panels": [
        {
          "panel_number": 1,
          "scene_description": "VERY detailed visual description for AI image generation. \
Include: composition, camera angle, lighting, colors, character poses, expressions, \
environment details, mood. This will be used AS-IS to generate the panel artwork. \
Be vivid and cinematic. 60-100 words.",
          "dialogue": [
            {"speaker": "Character Name", "text": "dialogue line"}
          ],
          "narration": "narrator caption text if any, else empty string",
          "sfx": "sound effect text if any (e.g. 'CRASH!', 'WHOOOOSH'), else empty string"
        }
      ]
    }
  ]
}

CRITICAL RULES:
1. scene_description must be SELF-CONTAINED visual description. NEVER reference previous panels.
2. Every character's visual_description must be detailed enough for consistent AI generation.
3. Dialogue should be natural, punchy, and reveal character.
4. Narration adds depth and atmosphere — use it for inner thoughts, time skips, world-building.
5. Sound effects should be used sparingly for maximum impact.
6. Each page should have a clear narrative beat — setup, escalation, twist, or resolution.
7. The story MUST be genuinely creative and surprising. Subvert expectations.
"""


# ════════════════════════════════════════════════════════════════════════
#   API CALL
# ════════════════════════════════════════════════════════════════════════

def call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.92) -> str:
    """
    Call the free Qwen/DeepSeek API on Radeon Cloud.
    Returns the raw assistant message content.
    """
    if not config.LLM_API_KEY:
        raise ValueError(
            "LLM_API_KEY is empty. Get your free key from "
            "https://developer.amd.com.cn/radeon/modelapis → Token Factory"
        )

    resp = requests.post(
        config.LLM_API_BASE,
        headers={
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 8000,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ════════════════════════════════════════════════════════════════════════
#   JSON EXTRACTION
# ════════════════════════════════════════════════════════════════════════

def _extract_json(raw: str) -> dict:
    """
    LLMs sometimes wrap JSON in markdown code fences. Strip them and parse.
    """
    # Remove ```json ... ``` fences
    cleaned = re.sub(r"```json\s*", "", raw)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = cleaned.strip()

    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try finding the first { ... } block
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Failed to parse LLM output as JSON. Raw output (first 500 chars):\n{raw[:500]}"
    )


# ════════════════════════════════════════════════════════════════════════
#   SCRIPT GENERATORS
# ════════════════════════════════════════════════════════════════════════

def generate_from_text(
    user_text: str,
    num_pages: int = 3,
    panels_per_page: int = 4,
    art_style: str = "Western Comic (Marvel/DC style)",
    mood: str = "Epic",
) -> dict:
    """
    Generate a comic script from a free-text story premise.
    """
    user_prompt = f"""\
Create a {mood.lower()} comic with {num_pages} pages and {panels_per_page} panels per page.

ART STYLE: {art_style}

USER'S STORY PREMISE:
{user_text}

Remember: every scene_description must be a self-contained, vivid visual description \
suitable for AI image generation. Be wildly creative."""

    raw = call_llm(SYSTEM_PROMPT, user_prompt)
    script = _extract_json(raw)
    script["_source"] = "text"
    script["_art_style"] = art_style
    script["_mood"] = mood
    return script


def generate_from_categories(
    genre: str,
    sub_genre: Optional[str] = None,
    art_style: str = "Western Comic (Marvel/DC style)",
    theme: str = "Discovery",
    mood: str = "Epic",
    num_pages: int = 3,
    uniqueness_premise: Optional[dict] = None,
) -> dict:
    """
    Generate a comic script from category selections + uniqueness engine.
    """
    if uniqueness_premise is None:
        from uniqueness import generate_unique_premise
        uniqueness_premise = generate_unique_premise(
            genre=genre, sub_genre=sub_genre, theme=theme, mood=mood
        )

    p = uniqueness_premise
    protag = p["protagonist"]

    user_prompt = f"""\
Create a {mood.lower()} {genre} comic.

UNIQUENESS DIRECTIVES (you MUST follow these):
- Plot structure: {p['plot_structure']}
- Protagonist archetype: {protag['archetype']}
- Protagonist unique traits: {', '.join(protag['traits'])}
- World/Setting: {p['setting']}
- Theme: {theme or 'emerges naturally from the story'}
{"- IMPORTANT PLOT TWIST (inject around panel " + str(p.get('twist_position', 2)) + " of the final page): " + p['twist'] if p.get('has_twist') and p.get('twist') else ""}

STRUCTURE: {num_pages} pages, {p['panels_per_page']} panels per page.
ART STYLE: {art_style}
SUB-GENRE: {sub_genre or 'your creative interpretation'}

Remember: every scene_description must be a self-contained, vivid visual description \
suitable for AI image generation. Be wildly creative and surprising."""

    raw = call_llm(SYSTEM_PROMPT, user_prompt)
    script = _extract_json(raw)
    script["_source"] = "category"
    script["_art_style"] = art_style
    script["_mood"] = mood
    script["_uniqueness"] = p
    return script


def count_total_panels(script: dict) -> int:
    """Count total panels across all pages in a script."""
    total = 0
    for page in script.get("pages", []):
        total += len(page.get("panels", []))
    return total


def flatten_panels(script: dict) -> list:
    """Return a flat list of (page_idx, panel) tuples."""
    panels = []
    for pi, page in enumerate(script.get("pages", [])):
        for panel in page.get("panels", []):
            panels.append((pi, panel))
    return panels