#!/usr/bin/env python3
"""Fail-closed verification for a packaged Parcel Sorter competition MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
from typing import Any


REQUIRED_ROOT_FILES = {
    "README.md",
    "RESULTS.json",
    "DEMO_VIDEOS.json",
    "DELIVERY_MANIFEST.json",
    "RUN_DEMO.sh",
    "VERIFY_DELIVERY.py",
    "commands/TRAINING_COMMAND.sh",
    "commands/EVALUATION_COMMAND.sh",
    "evidence/preflight",
    "evidence/posttrain/gate-decision.json",
    "model",
    "source",
}

CONTENT_FINGERPRINT_PROTOCOL = "decoded-gray-32x18-5-quantized-v1"
CONTENT_FINGERPRINT_SAMPLE_COUNT = 5
TRAINING_SEED = 11
RUNTIME_SEED = 2026080206
INFERENCE_SEEDS = (20260727, 20260728, 20260729)
MIN_COMPETITION_SUCCESSES = 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required JSON is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"required JSON is not an object: {path}")
    return payload


def _relative_file(root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} escapes the delivery root: {value}")
    target = root / relative
    if not target.is_file():
        raise ValueError(f"{label} is missing: {relative}")
    return target


def _campaign_gate(campaign: dict[str, Any], *, min_successes: int = 2) -> dict[str, bool]:
    runs = campaign.get("runs")
    if not isinstance(runs, list) or len(runs) != 3 or not all(isinstance(run, dict) for run in runs):
        return {"exactly_three_runs": False}

    pure_successes = sum(run.get("pure_vla_complete_success") is True for run in runs)
    run_checks = []
    for run in runs:
        policy = run.get("policy")
        runtime = run.get("runtime")
        run_checks.append(
            isinstance(policy, dict)
            and isinstance(runtime, dict)
            and run.get("vla_qualified") is True
            and run.get("system_control_class") == "pure_vla"
            and run.get("expert_reference_used") is False
            and run.get("task_action_correction_count") == 0
            and run.get("task_routing_authorities") == ["vla_policy"]
            and run.get("policy_authority_consistent") is True
            and int(policy.get("expert_fallback_count", -1)) == 0
            and policy.get("expert_reference_used") is False
            and int(policy.get("emergency_stop_count", -1)) == 0
            and runtime.get("gpu_count") == 1
            and runtime.get("cuda") is None
            and isinstance(runtime.get("rocm"), str)
            and bool(runtime.get("rocm"))
            and isinstance(runtime.get("gpu_name"), str)
            and bool(runtime.get("gpu_name"))
        )
    return {
        "campaign_status_passed": campaign.get("status") == "passed",
        "exactly_three_runs": int(campaign.get("trials", -1)) == 3,
        "minimum_pure_vla_successes": pure_successes >= min_successes,
        "pure_success_count_matches_runs": int(
            campaign.get("pure_vla_complete_success_count", -1)
        ) == pure_successes,
        "all_runs_pure_vla_attributed": all(run_checks),
        "zero_expert_fallback": int(campaign.get("expert_fallback_count", -1)) == 0,
        "zero_force_violations": int(campaign.get("force_violation_count", -1)) == 0,
        "all_runs_materially_actuated": int(campaign.get("vla_actuated_run_count", -1)) == 3,
        "single_radeon_all_runs": int(campaign.get("single_radeon_rocm_run_count", -1)) == 3,
    }


def _content_sample_indices(frame_count: int) -> tuple[int, ...]:
    if frame_count < CONTENT_FINGERPRINT_SAMPLE_COUNT:
        raise ValueError(
            "demo video contains fewer than five decodable frames for content fingerprinting"
        )
    return tuple(
        round(position * (frame_count - 1) / (CONTENT_FINGERPRINT_SAMPLE_COUNT - 1))
        for position in range(CONTENT_FINGERPRINT_SAMPLE_COUNT)
    )


def _quantized_gray_frame_digest(frame: Any) -> str:
    gray = frame.reformat(width=32, height=18, format="gray")
    plane = gray.planes[0]
    raw = bytes(plane)
    pixels = bytearray()
    for row in range(gray.height):
        start = row * plane.line_size
        pixels.extend(value >> 4 for value in raw[start : start + gray.width])
    return hashlib.sha256(bytes(pixels)).hexdigest()


def _decoded_content_fingerprint(path: Path) -> dict[str, Any]:
    try:
        import av
    except ImportError as exc:  # pragma: no cover - environment dependency
        raise ValueError("PyAV is required to verify demo videos") from exc
    try:
        with av.open(str(path)) as container:
            streams = [stream for stream in container.streams if stream.type == "video"]
            if len(streams) != 1:
                raise ValueError(f"expected one video stream, found {len(streams)}")
            frame_count = sum(1 for _ in container.decode(streams[0]))
        indices = _content_sample_indices(frame_count)
        wanted = set(indices)
        frame_digests: dict[int, str] = {}
        with av.open(str(path)) as container:
            stream = next(stream for stream in container.streams if stream.type == "video")
            for index, frame in enumerate(container.decode(stream)):
                if index in wanted:
                    frame_digests[index] = _quantized_gray_frame_digest(frame)
                    if len(frame_digests) == len(wanted):
                        break
        if len(frame_digests) != len(wanted):
            raise ValueError("unable to decode all demo-video fingerprint samples")
        payload = {
            "protocol": CONTENT_FINGERPRINT_PROTOCOL,
            "frame_count": frame_count,
            "sample_frame_indices": list(indices),
            "sample_frame_sha256": [frame_digests[index] for index in indices],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        return {
            "content_fingerprint_protocol": CONTENT_FINGERPRINT_PROTOCOL,
            "content_fingerprint": hashlib.sha256(canonical).hexdigest(),
            "content_sample_frame_count": frame_count,
            "content_sample_frame_indices": list(indices),
            "content_sample_frame_sha256": payload["sample_frame_sha256"],
        }
    except (OSError, ValueError, StopIteration) as exc:
        raise ValueError(f"demo video is not playable: {path}: {exc}") from exc


def _probe_video(path: Path) -> dict[str, Any]:
    return _decoded_content_fingerprint(path)


def _verify_manifest(root: Path) -> None:
    manifest = _read_json(root / "DELIVERY_MANIFEST.json")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("delivery manifest has no files")
    listed: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("delivery manifest item is not an object")
        relative = item.get("path")
        target = _relative_file(root, relative, label="manifest path")
        if relative in listed:
            raise ValueError(f"duplicate manifest path: {relative}")
        listed.add(relative)
        if item.get("size") != target.stat().st_size:
            raise ValueError(f"manifest size mismatch: {relative}")
        if item.get("sha256") != _sha256(target):
            raise ValueError(f"manifest SHA-256 mismatch: {relative}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "DELIVERY_MANIFEST.json"
    }
    if listed != actual:
        raise ValueError("delivery manifest does not exactly describe the directory")


def _verify_videos(root: Path, campaign: dict[str, Any]) -> None:
    index = _read_json(root / "DEMO_VIDEOS.json")
    videos = index.get("videos")
    if index.get("video_count") != 3 or not isinstance(videos, list) or len(videos) != 3:
        raise ValueError("delivery requires exactly three demo videos")
    runs = campaign["runs"]
    hashes: set[str] = set()
    visual_fingerprints: set[str] = set()
    episode_ids: set[str] = set()
    for run, item in zip(runs, videos, strict=True):
        if not isinstance(item, dict):
            raise ValueError("demo-video index item is not an object")
        episode_id = item.get("episode_id")
        if not isinstance(episode_id, str) or not episode_id or episode_id in episode_ids:
            raise ValueError("demo videos do not have unique episode identities")
        episode_ids.add(episode_id)
        if episode_id != run.get("episode_id"):
            raise ValueError("demo-video episode does not match campaign ordering")
        if item.get("success") is not run.get("success") or item.get(
            "pure_vla_complete_success"
        ) is not run.get("pure_vla_complete_success"):
            raise ValueError("demo-video verdict does not match campaign")
        video = _relative_file(root, item.get("packaged_path"), label="demo video")
        if video.suffix.lower() != ".mp4" or not str(video.relative_to(root)).startswith(
            "demo-videos/"
        ):
            raise ValueError("demo video is not a packaged MP4")
        digest = _sha256(video)
        if item.get("sha256") != digest or digest in hashes:
            raise ValueError("demo videos are not uniquely hash-bound")
        hashes.add(digest)
        if item.get("size") != video.stat().st_size:
            raise ValueError("demo-video size does not match index")
        probe = item.get("probe")
        if not isinstance(probe, dict) or probe.get("minimum_decoded_frames_verified") != 2:
            raise ValueError("demo-video decode evidence is incomplete")
        fingerprint = probe.get("content_fingerprint")
        if (
            probe.get("content_fingerprint_protocol") != CONTENT_FINGERPRINT_PROTOCOL
            or not isinstance(fingerprint, str)
            or not fingerprint
            or fingerprint in visual_fingerprints
        ):
            raise ValueError("demo videos are not uniquely content-bound")
        recomputed = _probe_video(video)
        if any(probe.get(key) != value for key, value in recomputed.items()):
            raise ValueError("demo-video content fingerprint does not match decoded content")
        visual_fingerprints.add(fingerprint)
    packaged = sorted((root / "demo-videos").glob("*.mp4"))
    if len(packaged) != 3:
        raise ValueError("demo-videos directory does not contain exactly three MP4 files")


def _verify_archive(root: Path) -> None:
    archive = root.with_suffix(".tar.gz")
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    if not archive.is_file() or not checksum.is_file():
        raise ValueError("delivery archive or SHA-256 sidecar is missing")
    expected_line = f"{_sha256(archive)}  {archive.name}"
    if checksum.read_text(encoding="ascii").strip() != expected_line:
        raise ValueError("delivery archive SHA-256 sidecar is invalid")
    with tarfile.open(archive, "r:gz") as stream:
        members = [member for member in stream.getmembers() if member.isfile()]
    expected_prefix = root.name + "/"
    member_names = {member.name for member in members}
    if not member_names or any(not name.startswith(expected_prefix) for name in member_names):
        raise ValueError("delivery archive has an unexpected root")
    expected_files = {
        expected_prefix + path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if member_names != expected_files:
        raise ValueError("delivery archive does not match the delivery directory")


def verify_delivery(root: Path, *, verify_archive: bool = True) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"delivery root is missing: {root}")
    for relative in REQUIRED_ROOT_FILES:
        target = root / relative
        if not target.exists():
            raise ValueError(f"required delivery artifact is missing: {relative}")
    _verify_manifest(root)
    results = _read_json(root / "RESULTS.json")
    if results.get("status") != "competition_mvp_passed":
        raise ValueError("delivery result is not marked passed")
    fixed_seed_contract = results.get("fixed_seed_contract")
    if fixed_seed_contract != {
        "training_seed": TRAINING_SEED,
        "runtime_seed": RUNTIME_SEED,
        "inference_seeds": list(INFERENCE_SEEDS),
    }:
        raise ValueError("delivery fixed seed contract is missing or changed")
    campaign_path = _relative_file(root, results.get("campaign_audit"), label="campaign audit")
    campaign = _read_json(campaign_path)
    checks = _campaign_gate(campaign, min_successes=MIN_COMPETITION_SUCCESSES)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"competition result gate failed: {failed}")
    result = results.get("result")
    pure_successes = sum(
        run["pure_vla_complete_success"] is True for run in campaign["runs"]
    )
    if (
        not isinstance(result, dict)
        or result.get("pure_vla_complete_successes") != pure_successes
        or result.get("trials") != 3
        or result.get("pure_vla_complete_successes", -1) < MIN_COMPETITION_SUCCESSES
    ):
        raise ValueError("RESULTS pure-VLA count does not match campaign")
    gate_path = _relative_file(root, results.get("gate_decision"), label="gate decision")
    gate = _read_json(gate_path)
    if (
        gate.get("decision") != "strict_pure_vla3_completed"
        or gate.get("pure_vla_closed_loop_started") is not True
        or int(gate.get("offline_screen_exit_code", -1)) != 0
    ):
        raise ValueError("packaged gate decision did not authorize strict pure-VLA delivery")
    command_files = results.get("command_files")
    if not isinstance(command_files, dict):
        raise ValueError("delivery has no exact command bindings")
    for label in ("training", "evaluation"):
        command = _relative_file(root, command_files.get(label), label=f"{label} command")
        if command.stat().st_size == 0:
            raise ValueError(f"{label} command is empty")
    rocm_evidence = results.get("rocm_evidence")
    if not isinstance(rocm_evidence, list) or not rocm_evidence:
        raise ValueError("delivery has no ROCm evidence binding")
    for relative in rocm_evidence:
        _relative_file(root, relative, label="ROCm evidence")
    _verify_videos(root, campaign)
    if verify_archive:
        _verify_archive(root)
    return {
        "root": str(root),
        "pure_vla_successes": sum(
            run["pure_vla_complete_success"] is True for run in campaign["runs"]
        ),
        "trials": 3,
        "videos": 3,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--skip-archive", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify_delivery(args.root, verify_archive=not args.skip_archive), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
