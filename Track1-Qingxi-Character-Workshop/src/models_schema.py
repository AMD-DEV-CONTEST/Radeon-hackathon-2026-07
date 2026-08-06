from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from src.world import load_world


def _default_affinities(primary: str, names: list[str]) -> dict[str, int]:
    """Sensible spread when the LLM produced all-zero / missing scores."""
    scores: dict[str, int] = {}
    for n in names:
        if n == primary:
            scores[n] = 88
        else:
            scores[n] = 25 + (abs(hash(n + primary)) % 35)
    return scores


class CharacterCard(BaseModel):
    name: str
    one_liner: str
    appearance: str
    personality: str
    backstory: str
    primary_affinity: str
    affinities: dict[str, int]
    spirit_domain: str
    ability_showcase: str
    image_prompt: str
    image_negative: str = ""
    motion_prompt: str = ""

    @field_validator("name", "one_liner", "appearance", "personality", "backstory",
                     "spirit_domain", "ability_showcase", "image_prompt",
                     "image_negative", "motion_prompt", mode="before")
    @classmethod
    def coerce_strings(cls, v: Any) -> str:
        """Accept nested dict/list for any string field and flatten it."""
        return _coerce_str(v)

    @field_validator("name", "one_liner", "appearance", "image_prompt")
    @classmethod
    def non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("field must be non-empty")
        return v

    @model_validator(mode="after")
    def check_affinities(self) -> CharacterCard:
        world = load_world()
        names = world.affinity_names()
        if self.primary_affinity not in names:
            raise ValueError(f"primary_affinity must be one of {names}")
        fixed: dict[str, int] = {}
        any_nonzero = False
        for n in names:
            raw = int(self.affinities.get(n, 0))
            if raw > 0:
                any_nonzero = True
            fixed[n] = max(0, min(100, raw))
        if not any_nonzero:
            # LLM failed to provide meaningful scores -> synthesize a good spread
            fixed = _default_affinities(self.primary_affinity, names)
        self.affinities = fixed
        return self

    def lore_markdown(self) -> str:
        lines = [
            f"# {self.name}",
            f"*{self.one_liner}*",
            "",
            f"**Affinity:** {self.primary_affinity}",
            f"**Appearance:** {self.appearance}",
            f"**Personality:** {self.personality}",
            f"**Backstory:** {self.backstory}",
            f"**Spirit Domain:** {self.spirit_domain}",
            f"**Ability Showcase:** {self.ability_showcase}",
            "",
            "**Six Affinities:** "
            + ", ".join(f"{k} {v}" for k, v in self.affinities.items()),
        ]
        return "\n".join(lines)


def _coerce_str(value: Any) -> str:
    """Flatten dict/list values to a readable string (LLMs sometimes emit
    nested objects for plain-string fields like `appearance`)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_coerce_str(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_coerce_str(v) for v in value)
    if value is None:
        return ""
    return str(value)


def extract_json_object(text: str) -> str:
    """Return the first parseable JSON object found anywhere in `text`.

    Tolerant of leading prose, trailing prose, markdown fences, and truncated
    output: scans each '{' and uses raw_decode so we take the FIRST complete
    object even if the LLM appended junk (or got cut off mid-generation).
    """
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[m.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return json.dumps(obj, ensure_ascii=False)
    raise ValueError("no JSON object found")


def parse_character_json(text: str) -> CharacterCard:
    raw = extract_json_object(text)
    data: dict[str, Any] = json.loads(raw)
    return CharacterCard.model_validate(data)