from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ReferenceView = Literal["front", "three_quarter_left", "profile_left"]


class CharacterReferencePromptInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    character_id: Annotated[str, Field(min_length=1, max_length=160)]
    age_stage: Annotated[str, Field(min_length=1, max_length=160)]
    identity_lock: Annotated[str, Field(min_length=1, max_length=4_000)]
    attire_lock: Annotated[str, Field(min_length=1, max_length=4_000)]
    source_asset_digests: tuple[Sha256Digest, ...] = Field(min_length=1, max_length=2)
    view: ReferenceView
    attempt: Annotated[int, Field(ge=0, le=1)]
    capability_digest: Sha256Digest

    @field_validator("character_id", "age_stage", "identity_lock", "attire_lock")
    @classmethod
    def non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("character reference prompt fields cannot be blank")
        return value.strip()

    @field_validator("source_asset_digests")
    @classmethod
    def distinct_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("character reference source digests must be distinct")
        return value


@dataclass(frozen=True, slots=True)
class RenderedCharacterReferencePrompt:
    character_id: str
    age_stage: str
    source_asset_digests: tuple[str, ...]
    capability_digest: str
    view: ReferenceView
    attempt: int
    view_instruction: str
    prompt: str
    negative_prompt: str
    seed: int
    prompt_digest: str
    input_digest: str


_VIEW_INSTRUCTIONS: dict[ReferenceView, str] = {
    "front": "front view, face and shoulders square to camera",
    "three_quarter_left": "three-quarter left view, approximately 45 degrees",
    "profile_left": "left profile view, exactly 90 degrees",
}
_NEGATIVE_PROMPT = (
    "collage, contact sheet, character card, label, caption, subtitle, watermark, "
    "logo, border, frame, generated text, letters, multiple people, duplicate subject, extra face, "
    "identity drift, inconsistent clothing, copied source background"
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def render_character_reference_prompt(
    value: CharacterReferencePromptInput,
) -> RenderedCharacterReferencePrompt:
    payload = value.model_dump(mode="json")
    input_digest = _digest(payload)
    seed = int(input_digest[:16], 16)
    instruction = _VIEW_INSTRUCTIONS[value.view]
    prompt = (
        f"One independent single-view identity reference portrait for "
        f"{value.character_id}, age stage {value.age_stage}; {instruction}. "
        f"Identity lock: {value.identity_lock}. Attire lock: {value.attire_lock}. "
        "Show exactly one subject against a neutral clean studio background with even "
        "soft light, realistic facial proportions, stable hair, bone structure, clothing, "
        "framing, and camera distance. Generate only this requested view. Hard output "
        "constraints: no collage, no contact sheet, no text, no label, no subtitle, "
        "no watermark, no logo, and no border or decorative frame."
    )
    prompt_digest = _digest(
        {
            "input_digest": input_digest,
            "negative_prompt": _NEGATIVE_PROMPT,
            "prompt": prompt,
            "seed": seed,
        }
    )
    return RenderedCharacterReferencePrompt(
        character_id=value.character_id,
        age_stage=value.age_stage,
        source_asset_digests=value.source_asset_digests,
        capability_digest=value.capability_digest,
        view=value.view,
        attempt=value.attempt,
        view_instruction=instruction,
        prompt=prompt,
        negative_prompt=_NEGATIVE_PROMPT,
        seed=seed,
        prompt_digest=prompt_digest,
        input_digest=input_digest,
    )


__all__ = [
    "CharacterReferencePromptInput",
    "ReferenceView",
    "RenderedCharacterReferencePrompt",
    "render_character_reference_prompt",
]
