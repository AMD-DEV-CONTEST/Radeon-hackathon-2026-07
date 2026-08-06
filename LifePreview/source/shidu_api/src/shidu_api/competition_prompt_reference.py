"""Competition-only single prompt reference authority.

This module deliberately does not widen the production character-reference
contract.  It freezes the competition profile in which one structured prompt
produces one ``front_three_quarter`` image with the pinned FLUX.2 T2I graph.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from creative_hub.db.canonical import canonical_json_digest


REFERENCE_PROFILE = "competition-prompt-single-view-v1"
SOURCE_MODE = "prompt_synthesized"
REFERENCE_VIEW = "front_three_quarter"
REFERENCE_ROLE = "character.reference.competition-front-three-quarter"
REFERENCE_REMOTE_NAME = "h3/reference-front-three-quarter.png"
REFERENCE_WIDTH = 512
REFERENCE_HEIGHT = 768
_SHA256_CHARS = frozenset("0123456789abcdef")
_ALLOWED_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class CompetitionPromptReferenceError(ValueError):
    """The competition prompt or its single generated image is invalid."""


def _digest_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _require_digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in _SHA256_CHARS for char in value)
    ):
        raise CompetitionPromptReferenceError(f"{label} is not a SHA-256 digest")
    return value


def _public_text(value: object, label: str, *, limit: int) -> str:
    if type(value) is not str:
        raise CompetitionPromptReferenceError(f"{label} must be text")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > limit:
        raise CompetitionPromptReferenceError(f"{label} is empty or too long")
    if any(ord(char) < 32 for char in normalized):
        raise CompetitionPromptReferenceError(f"{label} contains control characters")
    return normalized


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise CompetitionPromptReferenceError(f"{label} must be a JSON object")
    return value


def _first_script_values(snapshot: object) -> tuple[str, str, str]:
    authority = _mapping(
        getattr(snapshot, "trial_script_authority_payload", None),
        "trial script authority",
    )
    payload = _mapping(authority.get("payload"), "trial script payload")
    cues = payload.get("narration_cues")
    shots = payload.get("six_shots")
    if type(cues) is not list or not cues or type(cues[0]) is not dict:
        raise CompetitionPromptReferenceError("trial script narration is unavailable")
    if type(shots) is not list or not shots or type(shots[0]) is not dict:
        raise CompetitionPromptReferenceError("trial script shot is unavailable")
    narration = _public_text(cues[0].get("text"), "narration", limit=240)
    action = _public_text(shots[0].get("action"), "shot action", limit=500)
    location_value = shots[0].get("location", "historically grounded interior")
    location = _public_text(location_value, "shot location", limit=240)
    return narration, action, location


def _t2i_workflow_sha256(flux_manifest: Path) -> str:
    try:
        value = json.loads(Path(flux_manifest).read_text(encoding="utf-8"))
        capability = _mapping(value.get("capability"), "FLUX capability")
        workflows = capability.get("workflows")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompetitionPromptReferenceError("FLUX capability is unavailable") from exc
    if type(workflows) is not list:
        raise CompetitionPromptReferenceError("FLUX workflow authority is invalid")
    matches = [
        item
        for item in workflows
        if type(item) is dict and item.get("role") == "text_to_image"
    ]
    if len(matches) != 1 or matches[0].get("status") != "verified":
        raise CompetitionPromptReferenceError("verified FLUX T2I workflow is unavailable")
    return _require_digest(matches[0].get("sha256"), "FLUX T2I workflow SHA")


def build_competition_prompt_authority(
    *,
    snapshot: object,
    job_authority_digest: str,
    flux_manifest: Path,
) -> dict[str, Any]:
    """Freeze one structured prompt from the clicked book/research snapshot."""

    job_digest = _require_digest(job_authority_digest, "job authority digest")
    character = _public_text(
        getattr(snapshot, "character_name", None), "character name", limit=120
    )
    age_stage = _public_text(
        getattr(snapshot, "age_stage", None), "age stage", limit=80
    )
    context = _public_text(
        getattr(snapshot, "historical_context", None),
        "historical context",
        limit=1200,
    )
    book_digest = _require_digest(
        getattr(snapshot, "book_identity_digest", None), "book identity digest"
    )
    direction_digest = _require_digest(
        getattr(snapshot, "direction_digest", None), "direction digest"
    )
    script_digest = _require_digest(
        getattr(snapshot, "trial_script_digest", None), "trial script digest"
    )
    research_digest = _require_digest(
        getattr(snapshot, "research_digest", None), "research digest"
    )
    evidence_digest = _require_digest(
        getattr(snapshot, "evidence_pack_digest", None), "evidence pack digest"
    )
    safety_digest = _require_digest(
        getattr(snapshot, "safety_release_decision_digest", None),
        "safety release decision digest",
    )
    narration, action, location = _first_script_values(snapshot)
    workflow_sha = _t2i_workflow_sha256(Path(flux_manifest))
    # The character asset is prepared before the user's final video-job click.
    # Its identity must therefore be stable across the preparation request and
    # the later clicked job.  ``job_digest`` is still validated above so legacy
    # callers cannot silently omit their authority, but it is deliberately not
    # part of the reusable reference cache key.
    seed_authority = ":".join(
        (
            book_digest,
            direction_digest,
            script_digest,
            research_digest,
            evidence_digest,
            safety_digest,
            workflow_sha,
            "competition-prompt-single-view-v1",
        )
    )
    seed = int(hashlib.sha256(seed_authority.encode()).hexdigest()[:15], 16)
    visual_prompt = (
        f"A single historically grounded cinematic portrait of {character}, {age_stage}, "
        f"front three-quarter view, at {location}. Context: {context}. "
        f"The subject is {action}. One person, identity-clear face, period-correct attire, "
        "clean composition, no text, no watermark, no collage, 512x768 portrait."
    )
    h3_prompt = (
        f"Use the single reference image as the identity anchor for {character}. "
        f"Scene: {location}; action: {action}; calm front three-quarter performance. "
        f"Spoken line in native audio: {narration}"
    )
    prompt_sha = _digest_bytes(visual_prompt.encode("utf-8"))
    h3_prompt_sha = _digest_bytes(h3_prompt.encode("utf-8"))
    identity = {
        "schemaVersion": "amd.competition-prompt-reference-authority.v1",
        "referenceProfile": REFERENCE_PROFILE,
        "sourceMode": SOURCE_MODE,
        "requiredImages": 1,
        "view": REFERENCE_VIEW,
        "characterName": character,
        "ageStage": age_stage,
        "historicalContext": context,
        "bookIdentitySha256": book_digest,
        "directionSha256": direction_digest,
        "trialScriptSha256": script_digest,
        "researchSha256": research_digest,
        "evidencePackSha256": evidence_digest,
        "safetyReleaseDecisionSha256": safety_digest,
        "visualPrompt": visual_prompt,
        "promptSha256": prompt_sha,
        "h3Prompt": h3_prompt,
        "h3PromptSha256": h3_prompt_sha,
        "seed": seed,
        "workflowSha256": workflow_sha,
        "generationInvocationCount": 1,
        "technicalRetryLimit": 1,
    }
    return {**identity, "authoritySha256": canonical_json_digest(identity)}


def validate_competition_reference_image(
    path: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Decode and attest the one competition reference image."""

    expected = _require_digest(expected_sha256, "reference image SHA")
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise CompetitionPromptReferenceError("reference image is unavailable")
    byte_size = candidate.stat().st_size
    if not 0 < byte_size <= 25 * 1024 * 1024:
        raise CompetitionPromptReferenceError("reference image size is invalid")
    actual = _digest_bytes(candidate.read_bytes())
    if actual != expected:
        raise CompetitionPromptReferenceError("reference image SHA changed")
    try:
        with Image.open(candidate) as opened:
            image_format = str(opened.format or "").upper()
            width, height = opened.size
            frames = int(getattr(opened, "n_frames", 1))
            opened.verify()
        with Image.open(candidate) as decoded:
            decoded.load()
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise CompetitionPromptReferenceError("reference image cannot be decoded") from exc
    if image_format not in _ALLOWED_FORMATS or frames != 1:
        raise CompetitionPromptReferenceError("reference image format is invalid")
    if (width, height) != (REFERENCE_WIDTH, REFERENCE_HEIGHT):
        raise CompetitionPromptReferenceError("reference image dimensions are invalid")
    return {
        "mimeType": _ALLOWED_FORMATS[image_format],
        "format": image_format,
        "width": width,
        "height": height,
        "frameCount": frames,
        "sha256": actual,
        "byteSize": byte_size,
    }


def validate_imported_competition_reference_image(
    path: Path,
    *,
    expected_sha256: str,
    expected_width: int = 880,
    expected_height: int = 1168,
) -> dict[str, Any]:
    """Decode the fixed imported competition asset without claiming FLUX origin."""

    expected = _require_digest(expected_sha256, "imported reference image SHA")
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise CompetitionPromptReferenceError("imported reference image is unavailable")
    byte_size = candidate.stat().st_size
    if not 0 < byte_size <= 25 * 1024 * 1024 or _digest_bytes(candidate.read_bytes()) != expected:
        raise CompetitionPromptReferenceError("imported reference image bytes changed")
    try:
        with Image.open(candidate) as opened:
            image_format = str(opened.format or "").upper()
            width, height = opened.size
            frames = int(getattr(opened, "n_frames", 1))
            opened.verify()
        with Image.open(candidate) as decoded:
            decoded.load()
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise CompetitionPromptReferenceError(
            "imported reference image cannot be decoded"
        ) from exc
    if (
        image_format not in _ALLOWED_FORMATS
        or frames != 1
        or width != expected_width
        or height != expected_height
    ):
        raise CompetitionPromptReferenceError(
            "imported reference image media authority changed"
        )
    return {
        "mimeType": _ALLOWED_FORMATS[image_format],
        "format": image_format,
        "width": width,
        "height": height,
        "frameCount": frames,
        "sha256": expected,
        "byteSize": byte_size,
    }


__all__ = [
    "CompetitionPromptReferenceError",
    "REFERENCE_HEIGHT",
    "REFERENCE_PROFILE",
    "REFERENCE_REMOTE_NAME",
    "REFERENCE_ROLE",
    "REFERENCE_VIEW",
    "REFERENCE_WIDTH",
    "SOURCE_MODE",
    "build_competition_prompt_authority",
    "validate_competition_reference_image",
    "validate_imported_competition_reference_image",
]
