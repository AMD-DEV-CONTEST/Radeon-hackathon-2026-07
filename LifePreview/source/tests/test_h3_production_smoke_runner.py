from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "amd" / "run-h3-production-smoke.py"
TEMPLATE = ROOT / "drama_factory" / "workflows" / "h3_ref2va_amd_api.json"

SPEC = importlib.util.spec_from_file_location("h3_production_smoke_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _admission_snapshot(
    *,
    memory_current: int,
    oom: int = 0,
    oom_kill: int = 0,
    oom_group_kill: int = 0,
) -> dict[str, object]:
    return {
        "memoryMaxBytes": RUNNER.HARD_MEMORY_MAX_BYTES,
        "memoryCurrentBytes": memory_current,
        "memorySwapCurrentBytes": 0,
        "memorySwapMaxBytes": 0,
        "memoryEvents": {
            "oom": oom,
            "oom_kill": oom_kill,
            "oom_group_kill": oom_group_kill,
        },
    }


def test_frozen_template_compiles_exact_production_shape_with_three_references() -> None:
    references = ["identity.png", "wardrobe.png", "pose.png"]

    assert RUNNER._sha256(TEMPLATE) == RUNNER.EXPECTED_TEMPLATE_SHA256
    assert RUNNER.EXPECTED_TEMPLATE_SHA256 == (
        "f85fc557edcb22f2ca191867e96bc4551ba32755b133271e295a5ff471018789"
    )

    workflow = RUNNER._compile_workflow(TEMPLATE, references)

    conditioning = workflow["6"]["inputs"]
    assert (conditioning["width"], conditioning["height"]) == (1344, 768)
    assert conditioning["length"] == 192
    assert workflow["9"]["inputs"]["steps"] == 20
    assert workflow["14"]["inputs"]["fps"] == 24.0
    assert [workflow[str(node)]["inputs"]["image"] for node in range(16, 19)] == (
        references
    )
    assert {
        key: value
        for key, value in conditioning.items()
        if key.startswith("ref_images.ref_image_")
    } == {
        "ref_images.ref_image_0": ["16", 0],
        "ref_images.ref_image_1": ["17", 0],
        "ref_images.ref_image_2": ["18", 0],
    }
    assert set(workflow).isdisjoint({"19", "20", "21", "22", "23", "24"})
    assert workflow["1"]["inputs"]["unet_name"] == (
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    )
    assert workflow["2"]["inputs"]["clip_name"] == (
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    )
    assert workflow["3"]["inputs"]["vae_name"] == (
        "minimax_h3_video_vae_fp16.safetensors"
    )
    assert workflow["4"]["inputs"]["vae_name"] == (
        "minimax_h3_audio_vae_fp32.safetensors"
    )
    assert RUNNER.PLACEHOLDER_PATTERN.search(
        json.dumps(workflow, ensure_ascii=False)
    ) is None


def test_structural_json_closing_braces_are_not_mistaken_for_placeholders() -> None:
    workflow = RUNNER._compile_workflow(
        TEMPLATE,
        ["identity.png", "wardrobe.png", "pose.png"],
    )

    serialized = json.dumps(workflow, ensure_ascii=False)

    assert serialized.endswith("}}")
    assert RUNNER.PLACEHOLDER_PATTERN.search(serialized) is None


def test_resume_queue_is_digest_bound_and_uses_the_production_timeout(
    tmp_path: Path,
) -> None:
    queued = tmp_path / "queued.json"
    payload = {
        "schemaVersion": "amd.h3-production-smoke-queue.v1",
        "promptId": "f8664dbb-626d-41d8-821a-ae9462e77954",
        "submissionNonce": "391565f077b44c13a06aecd9ca7c4d1e",
        "workflowSha256": "c" * 64,
        "templateSha256": RUNNER.EXPECTED_TEMPLATE_SHA256,
        "startedAt": "2026-08-06T06:29:22.046196+00:00",
        "beforeSubmission": _admission_snapshot(memory_current=1),
    }
    queued.write_text(json.dumps(payload), encoding="utf-8")

    assert RUNNER._load_resume_queue(queued, expected_workflow_sha256="c" * 64) == payload
    assert RUNNER.DEFAULT_RUN_TIMEOUT_SECONDS == 25_200

    payload["workflowSha256"] = "d" * 64
    queued.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RUNNER.SmokeError, match="workflow digest"):
        RUNNER._load_resume_queue(queued, expected_workflow_sha256="c" * 64)


@pytest.mark.parametrize(
    "prompt_id",
    ["../escape", "", "prompt id", "file:///workspace/prompt"],
)
def test_resume_queue_rejects_unsafe_prompt_identity(
    tmp_path: Path,
    prompt_id: str,
) -> None:
    queued = tmp_path / "queued.json"
    queued.write_text(
        json.dumps(
            {
                "schemaVersion": "amd.h3-production-smoke-queue.v1",
                "promptId": prompt_id,
                "submissionNonce": "a" * 32,
                "workflowSha256": "c" * 64,
                "templateSha256": RUNNER.EXPECTED_TEMPLATE_SHA256,
                "startedAt": "2026-08-06T06:29:22+00:00",
                "beforeSubmission": _admission_snapshot(memory_current=1),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RUNNER.SmokeError, match="prompt id"):
        RUNNER._load_resume_queue(queued, expected_workflow_sha256="c" * 64)


def test_admission_accepts_the_last_byte_below_the_exact_80_percent_wall() -> None:
    assert RUNNER.ADMISSION_REJECT_BYTES == (
        RUNNER.HARD_MEMORY_MAX_BYTES * 80 // 100
    )

    RUNNER._validate_admission(
        _admission_snapshot(memory_current=RUNNER.ADMISSION_REJECT_BYTES - 1)
    )


def test_admission_rejects_the_exact_80_percent_boundary() -> None:
    with pytest.raises(RUNNER.SmokeError, match="at or above the 80% admission wall"):
        RUNNER._validate_admission(
            _admission_snapshot(memory_current=RUNNER.ADMISSION_REJECT_BYTES)
        )


@pytest.mark.parametrize("counter", ["oom", "oom_kill", "oom_group_kill"])
def test_admission_rejects_any_nonzero_oom_counter(counter: str) -> None:
    counter_values = {counter: 1}
    snapshot = _admission_snapshot(
        memory_current=RUNNER.ADMISSION_REJECT_BYTES - 1,
        **counter_values,
    )

    with pytest.raises(RUNNER.SmokeError, match="OOM counters require recovery"):
        RUNNER._validate_admission(snapshot)


def test_find_video_accepts_only_an_existing_output_below_the_output_root(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    video = output_root / "h3-production-smoke" / "result.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"synthetic mp4")
    history = {
        "outputs": {
            "15": {
                "videos": [
                    {
                        "filename": "result.mp4",
                        "subfolder": "h3-production-smoke",
                        "type": "output",
                    }
                ]
            }
        }
    }

    assert RUNNER._find_video(history, output_root) == video.resolve()


@pytest.mark.parametrize(
    ("filename", "subfolder"),
    [
        ("../escape.mp4", ""),
        ("escape.mp4", "../outside"),
    ],
)
def test_find_video_rejects_path_traversal(
    tmp_path: Path,
    filename: str,
    subfolder: str,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    history = {
        "outputs": {
            "15": {
                "videos": [
                    {
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": "output",
                    }
                ]
            }
        }
    }

    with pytest.raises(RUNNER.SmokeError, match="did not return an MP4"):
        RUNNER._find_video(history, output_root)


def test_probe_accepts_mocked_native_video_and_audio_streams(tmp_path: Path) -> None:
    path = tmp_path / "result.mp4"
    expected = {
        "streams": [
            {"codec_type": "video", "avg_frame_rate": "24/1"},
            {"codec_type": "audio", "sample_rate": "48000"},
        ],
        "format": {"duration": "8.000000"},
    }
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(expected),
        stderr="",
    )

    with patch.object(RUNNER.subprocess, "run", return_value=completed) as run:
        assert RUNNER._probe(path) == expected

    run.assert_called_once_with(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("codec_type", ["video", "audio"])
def test_probe_rejects_a_mocked_single_stream(
    tmp_path: Path,
    codec_type: str,
) -> None:
    stream = {"codec_type": codec_type}
    if codec_type == "video":
        stream["avg_frame_rate"] = "24/1"
    completed = SimpleNamespace(
        stdout=json.dumps(
            {
                "streams": [stream],
                "format": {"duration": "8.0"},
            }
        )
    )

    with patch.object(RUNNER.subprocess, "run", return_value=completed):
        with pytest.raises(
            RUNNER.SmokeError,
            match="must contain native video and audio streams",
        ):
            RUNNER._probe(tmp_path / "single-stream.mp4")
