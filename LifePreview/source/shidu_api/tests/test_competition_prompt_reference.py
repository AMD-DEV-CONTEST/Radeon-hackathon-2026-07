from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from shidu_api.competition_prompt_reference import (
    CompetitionPromptReferenceError,
    build_competition_prompt_authority,
    validate_competition_reference_image,
)


ROOT = Path(__file__).resolve().parents[2]
FLUX_MANIFEST = (
    ROOT / "drama_factory/config/flux2_dev_fp8mixed_amd_capability.json"
)


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        character_name="苏轼",
        age_stage="middle-aged",
        historical_context="乌台诗案后，苏轼在黄州重新审视自己的生活。",
        book_identity_digest="0" * 64,
        direction_digest="3" * 64,
        trial_script_digest="1" * 64,
        research_digest="4" * 64,
        evidence_pack_digest="2" * 64,
        safety_release_decision_digest="5" * 64,
        trial_script_authority_payload={
            "payload": {
                "narration_cues": [
                    {"text": "真正的旷达，不是没有风雨，而是仍愿意向前。"}
                ],
                "six_shots": [
                    {
                        "action": "苏轼在江边停步，望向远处的月光",
                        "location": "宋代黄州江岸",
                    }
                ],
            }
        },
    )


def test_prompt_authority_is_single_image_and_bound_to_snapshot_and_t2i() -> None:
    authority = build_competition_prompt_authority(
        snapshot=_snapshot(),
        job_authority_digest="a" * 64,
        flux_manifest=FLUX_MANIFEST,
    )

    assert authority["referenceProfile"] == "competition-prompt-single-view-v1"
    assert authority["sourceMode"] == "prompt_synthesized"
    assert authority["requiredImages"] == 1
    assert authority["view"] == "front_three_quarter"
    assert authority["generationInvocationCount"] == 1
    assert authority["technicalRetryLimit"] == 1
    assert authority["workflowSha256"] == (
        "6029c0b8d2fe9133b354f01b2d693fa83622ebc1135b4638ab3f884065589618"
    )
    assert "苏轼" in authority["visualPrompt"]
    assert "黄州" in authority["visualPrompt"]
    assert "苏轼" in authority["h3Prompt"]
    assert len(authority["promptSha256"]) == 64
    assert len(authority["h3PromptSha256"]) == 64
    assert len(authority["authoritySha256"]) == 64


def test_prompt_authority_rejects_missing_frozen_research_text() -> None:
    snapshot = _snapshot()
    snapshot.historical_context = "  "

    with pytest.raises(CompetitionPromptReferenceError):
        build_competition_prompt_authority(
            snapshot=snapshot,
            job_authority_digest="a" * 64,
            flux_manifest=FLUX_MANIFEST,
        )


def test_single_reference_image_must_decode_at_pinned_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "reference.png"
    Image.new("RGB", (512, 768), (32, 24, 16)).save(path, format="PNG")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    metadata = validate_competition_reference_image(path, expected_sha256=digest)

    assert metadata == {
        "mimeType": "image/png",
        "format": "PNG",
        "width": 512,
        "height": 768,
        "frameCount": 1,
        "sha256": digest,
        "byteSize": path.stat().st_size,
    }


@pytest.mark.parametrize("size", [(511, 768), (512, 767)])
def test_single_reference_image_rejects_wrong_dimensions(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    path = tmp_path / "reference.png"
    Image.new("RGB", size, (32, 24, 16)).save(path, format="PNG")

    with pytest.raises(CompetitionPromptReferenceError):
        validate_competition_reference_image(
            path,
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )


def test_single_reference_image_rejects_undecodable_bytes(tmp_path: Path) -> None:
    path = tmp_path / "reference.png"
    path.write_bytes(b"not-an-image")

    with pytest.raises(CompetitionPromptReferenceError):
        validate_competition_reference_image(
            path,
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
