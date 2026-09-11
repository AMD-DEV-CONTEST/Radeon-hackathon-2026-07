#!/usr/bin/env python3
"""Build a self-contained competition MVP bundle from a passed pure-VLA gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from typing import Any


REQUIRED_SOURCE_PATHS = (
    "configs",
    "scripts",
    "src",
    "tests",
    "Dockerfile.rocm",
    "UPSTREAM_LOCK.json",
    "README.md",
    "README_CN.md",
    "SUBMISSION_CHECKLIST.md",
    "SUBMISSION_CHECKLIST_CN.md",
    "docs/COMPETITION_MVP_DELIVERY_CN.md",
)

CONTENT_FINGERPRINT_PROTOCOL = "decoded-gray-32x18-5-quantized-v1"
CONTENT_FINGERPRINT_SAMPLE_COUNT = 5
TRAINING_SEED = 11
RUNTIME_SEED = 2026080206
INFERENCE_SEEDS = (20260727, 20260728, 20260729)
MIN_COMPETITION_SUCCESSES = 2
MAX_COMPETITION_SUCCESSES = 3


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


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    else:
        raise ValueError(f"required delivery source is missing: {source}")


def _find_exact_command(root: Path, filename: str, *, label: str) -> Path:
    candidates = sorted(path for path in root.rglob(filename) if path.is_file())
    if len(candidates) != 1:
        raise ValueError(
            f"delivery requires exactly one {label} command named {filename}; found {len(candidates)}"
        )
    if candidates[0].stat().st_size == 0:
        raise ValueError(f"{label} command is empty: {candidates[0]}")
    return candidates[0]


def _external_command(path: Path | None, *, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} command was not supplied")
    resolved = path.resolve()
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError(f"{label} command is missing or empty: {resolved}")
    return resolved


def _find_rocm_evidence(root: Path, *, output_prefix: Path) -> list[str]:
    candidates = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and any(token in path.name.lower() for token in ("rocm", "telemetry"))
    )
    if not candidates:
        raise ValueError(f"delivery requires AMD/ROCm evidence under: {root}")
    return [
        (output_prefix / path.relative_to(root)).as_posix()
        for path in candidates
    ]


def _campaign_gate(campaign: dict[str, Any], *, min_successes: int) -> dict[str, Any]:
    if not MIN_COMPETITION_SUCCESSES <= min_successes <= MAX_COMPETITION_SUCCESSES:
        raise ValueError(
            "competition delivery minimum must remain between 2 and 3 pure-VLA successes"
        )
    runs = campaign.get("runs") or []
    trials = int(campaign.get("trials", -1))
    pure_successes = int(campaign.get("pure_vla_complete_success_count", -1))
    expert_reference_count = sum(
        bool(run.get("expert_reference_used")) for run in runs if isinstance(run, dict)
    )
    checks = {
        "campaign_status_passed": campaign.get("status") == "passed",
        "exactly_three_trials": trials == 3 and len(runs) == 3,
        "minimum_pure_vla_successes": pure_successes >= min_successes,
        "all_runs_vla_qualified": int(campaign.get("vla_qualified_run_count", -1)) == 3,
        "all_runs_materially_actuated": int(campaign.get("vla_actuated_run_count", -1)) == 3,
        "single_radeon_all_runs": int(campaign.get("single_radeon_rocm_run_count", -1)) == 3,
        "zero_expert_fallback": int(campaign.get("expert_fallback_count", -1)) == 0,
        "zero_expert_reference": expert_reference_count == 0,
        "zero_force_violations": int(campaign.get("force_violation_count", -1)) == 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "successes": int(campaign.get("successes", -1)),
        "pure_vla_complete_successes": pure_successes,
        "trials": trials,
        "success_rate": campaign.get("success_rate"),
        "wilson_95": campaign.get("wilson_95"),
        "expert_reference_count": expert_reference_count,
        "expert_fallback_count": campaign.get("expert_fallback_count"),
        "force_violation_count": campaign.get("force_violation_count"),
        "vla_qualified_run_count": campaign.get("vla_qualified_run_count"),
        "single_radeon_rocm_run_count": campaign.get("single_radeon_rocm_run_count"),
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
    except ImportError as exc:
        raise ValueError("PyAV is required to fingerprint demo video content") from exc

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
        raise ValueError(f"demo video content fingerprint failed: {path}: {exc}") from exc


def _probe_video(path: Path) -> dict[str, Any]:
    try:
        import av
    except ImportError as exc:
        raise ValueError("PyAV is required to verify demo videos") from exc

    try:
        with av.open(str(path)) as container:
            streams = [stream for stream in container.streams if stream.type == "video"]
            if len(streams) != 1:
                raise ValueError(f"expected one video stream, found {len(streams)}")
            stream = streams[0]
            decoded = container.decode(stream)
            first_frame = next(decoded, None)
            second_frame = next(decoded, None)
            if first_frame is None or second_frame is None:
                raise ValueError("video contains fewer than two decodable frames")
            duration_seconds = None
            if stream.duration is not None and stream.time_base is not None:
                duration_seconds = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration_seconds = float(container.duration / av.time_base)
            if duration_seconds is not None and duration_seconds <= 0:
                raise ValueError("video duration is not positive")
            width = int(getattr(stream.codec_context, "width", 0) or 0)
            height = int(getattr(stream.codec_context, "height", 0) or 0)
            if width <= 0 or height <= 0:
                raise ValueError("video dimensions are invalid")
            return {
                "codec": str(getattr(stream.codec_context, "name", "unknown")),
                "width": width,
                "height": height,
                "duration_seconds": duration_seconds,
                "minimum_decoded_frames_verified": 2,
                **_decoded_content_fingerprint(path),
            }
    except (OSError, ValueError, StopIteration) as exc:
        raise ValueError(f"demo video is not playable: {path}: {exc}") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_episode_name(value: Any) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "episode")).strip("-.")
    return name or "episode"


def _validate_demo_videos(
    campaign: dict[str, Any], *, posttrain: Path
) -> list[dict[str, Any]]:
    runs = campaign.get("runs") or []
    if len(runs) != 3 or not all(isinstance(run, dict) for run in runs):
        raise ValueError("demo delivery requires exactly three campaign runs")

    posttrain = posttrain.resolve()
    sources: set[Path] = set()
    content_hashes: set[str] = set()
    visual_fingerprints: set[str] = set()
    episode_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, run in enumerate(runs, start=1):
        episode_id = str(run.get("episode_id") or "")
        if not episode_id or episode_id in episode_ids:
            raise ValueError("demo videos require three unique episode identities")
        episode_ids.add(episode_id)
        media = run.get("media") or {}
        source_text = media.get("video_path")
        if media.get("video_requested") is not True or media.get("video_saved") is not True:
            raise ValueError(f"strict rollout has no saved demo video: {episode_id}")
        if not source_text:
            raise ValueError(f"strict rollout video path is missing: {episode_id}")
        source_candidate = Path(str(source_text))
        if not source_candidate.is_absolute():
            source_candidate = posttrain / source_candidate
        source = source_candidate.resolve()
        if not _is_within(source, posttrain):
            raise ValueError(f"demo video is outside post-training evidence: {source}")
        if source in sources:
            raise ValueError(f"duplicate demo video source: {source}")
        sources.add(source)
        if source.suffix.lower() != ".mp4" or not source.is_file():
            raise ValueError(f"required demo MP4 is missing: {source}")
        if source.stat().st_size < 1024:
            raise ValueError(f"demo video is unexpectedly small: {source}")
        source_sha256 = _sha256(source)
        if source_sha256 in content_hashes:
            raise ValueError(f"duplicate demo video content: {source}")
        content_hashes.add(source_sha256)
        validated.append(
            {
                "index": index,
                "run": run,
                "episode_id": episode_id,
                "source": source,
            }
        )
    for item in validated:
        probe = _probe_video(item["source"])
        fingerprint = probe.get("content_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("demo video content fingerprint is missing")
        if fingerprint in visual_fingerprints:
            raise ValueError(f"duplicate demo video visual content: {item['source']}")
        visual_fingerprints.add(fingerprint)
        item["probe"] = probe
    return validated


def _copy_demo_videos(
    validated: list[dict[str, Any]], *, output: Path
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    destination_root = output / "demo-videos"
    destination_root.mkdir(parents=True, exist_ok=False)
    for item in validated:
        index = int(item["index"])
        run = item["run"]
        episode_id = str(item["episode_id"])
        source = item["source"]
        probe = item["probe"]
        destination = destination_root / f"{index:02d}-{_safe_episode_name(episode_id)}.mp4"
        shutil.copy2(source, destination)
        records.append(
            {
                "episode_id": episode_id,
                "success": bool(run.get("success")),
                "pure_vla_complete_success": bool(
                    run.get("pure_vla_complete_success")
                ),
                "vla_qualified": bool(run.get("vla_qualified")),
                "source_summary": run.get("source_summary"),
                "source_summary_sha256": run.get("source_summary_sha256"),
                "source_video_path": str(source),
                "packaged_path": destination.relative_to(output).as_posix(),
                "size": destination.stat().st_size,
                "sha256": _sha256(destination),
                "probe": probe,
            }
        )
    return records


def _package_demo_videos(
    campaign: dict[str, Any], *, posttrain: Path, output: Path
) -> list[dict[str, Any]]:
    return _copy_demo_videos(
        _validate_demo_videos(campaign, posttrain=posttrain), output=output
    )


def _write_demo_script(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-/workspace/rdna/bin/python}"
OUTPUT="${1:-${ROOT_DIR}/demo-output}"
test ! -e "${OUTPUT}" || { echo "ERROR: demo output already exists" >&2; exit 3; }
export PYTHONPATH="${ROOT_DIR}/source/src${PYTHONPATH:+:${PYTHONPATH}}"
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export TOKENIZERS_PARALLELISM=false
cd "${ROOT_DIR}/source"
source scripts/activate_radeon_env.sh
"${PYTHON}" scripts/run_with_rocm_telemetry.py \
  --output "${OUTPUT}/telemetry" --interval-seconds 1 -- \
  "${PYTHON}" scripts/collect_mobile_suction_dataset_rocm.py \
  --config configs/mobile_pi05_single_box_v14_v7_strict_smoke_3.json \
  --output "${OUTPUT}/rollouts" --backend rocm --audit-only --wrist-rgbd \
  --max-episodes 3 --smolvla-checkpoint "${ROOT_DIR}/model" \
  --policy-mode pi05_incremental --policy-hz 3 \
  --pi05-chunk-execution-protocol first-action-hold-v1 \
  --pi05-chunk-execution-steps 1 --require-vla-goal-verdict \
  --require-vla-grasp-mode --task-routing-authority vla_policy \
  --record-media-all-episodes --workers 1
"${PYTHON}" scripts/summarize_mobile_vla_campaign.py \
  --collection-summary "${OUTPUT}/rollouts/collection-summary.json" \
  --output "${OUTPUT}/campaign-audit.json"
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_verify_script(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parent
target = root / "source" / "scripts" / "verify_competition_mvp_delivery.py"
sys.argv = [str(target), "--root", str(root)]
runpy.run_path(str(target), run_name="__main__")
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--posttrain-evidence", type=Path, required=True)
    parser.add_argument("--preflight-evidence", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--training-command",
        type=Path,
        help="actual immutable training command; defaults to exact_train_command.sh under preflight evidence",
    )
    parser.add_argument(
        "--evaluation-command",
        type=Path,
        help="actual immutable strict-evaluation command; defaults to exact-command.sh under posttrain evidence",
    )
    parser.add_argument("--min-successes", type=int, default=2)
    args = parser.parse_args()

    if not MIN_COMPETITION_SUCCESSES <= args.min_successes <= MAX_COMPETITION_SUCCESSES:
        raise ValueError(
            "--min-successes must be 2 or 3; the competition threshold is fixed at >=2/3"
        )

    checkpoint = args.checkpoint.resolve()
    posttrain = args.posttrain_evidence.resolve()
    preflight = args.preflight_evidence.resolve()
    code_root = args.code_root.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"immutable delivery output already exists: {output}")

    gate_path = posttrain / "gate-decision.json"
    gate = _read_json(gate_path)
    if (
        gate.get("decision") != "strict_pure_vla3_completed"
        or gate.get("pure_vla_closed_loop_started") is not True
        or int(gate.get("offline_screen_exit_code", -1)) != 0
    ):
        raise ValueError("post-training gate did not authorize a competition delivery")
    campaign_path = Path(str(gate.get("campaign_audit") or "")).resolve()
    if not _is_within(campaign_path, posttrain):
        raise ValueError("campaign audit must be inside post-training evidence")
    campaign = _read_json(campaign_path)
    result = _campaign_gate(campaign, min_successes=args.min_successes)
    if not result["passed"]:
        failed = [name for name, passed in result["checks"].items() if not passed]
        raise ValueError(f"competition MVP result gate failed: {failed}")
    validated_demo_videos = _validate_demo_videos(campaign, posttrain=posttrain)
    training_command = (
        _external_command(args.training_command, label="training")
        if args.training_command is not None
        else _find_exact_command(preflight, "exact_train_command.sh", label="training")
    )
    evaluation_command = (
        _external_command(args.evaluation_command, label="evaluation")
        if args.evaluation_command is not None
        else _find_exact_command(posttrain, "exact-command.sh", label="evaluation")
    )
    rocm_evidence = _find_rocm_evidence(
        posttrain, output_prefix=Path("evidence") / "posttrain"
    )

    output.mkdir(parents=True)
    _copy_path(checkpoint, output / "model")
    _copy_path(preflight, output / "evidence" / "preflight")
    _copy_path(posttrain, output / "evidence" / "posttrain")
    commands = output / "commands"
    commands.mkdir()
    shutil.copy2(training_command, commands / "TRAINING_COMMAND.sh")
    shutil.copy2(evaluation_command, commands / "EVALUATION_COMMAND.sh")
    demo_videos = _copy_demo_videos(validated_demo_videos, output=output)
    (output / "DEMO_VIDEOS.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "protocol": "parcel-sorter-strict-pure-vla-demo-videos-v1",
                "video_count": len(demo_videos),
                "videos": demo_videos,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    source_root = output / "source"
    source_root.mkdir()
    for relative in REQUIRED_SOURCE_PATHS:
        _copy_path(code_root / relative, source_root / relative)
    (output / "README.md").write_text(
        "# Parcel Sorter PI0.5 Competition MVP\n\n"
        "This immutable package contains the passed strict pure-VLA three-rollout "
        "competition result, all three bound MP4 recordings, checkpoint, source snapshot, "
        "frozen evidence, exact training/evaluation commands, and AMD ROCm evidence.\n\n"
        "The fixed contract is training seed 11, runtime seed 2026080206, and "
        "inference seeds 20260727/20260728/20260729; the package verifier enforces it.\n\n"
        "Run `python VERIFY_DELIVERY.py` before submitting the sibling `.tar.gz` and `.sha256` files. "
        "For a fresh local demonstration, run `bash RUN_DEMO.sh <new-output-directory>`.\n",
        encoding="utf-8",
    )
    _write_demo_script(output / "RUN_DEMO.sh")
    _write_verify_script(output / "VERIFY_DELIVERY.py")

    results = {
        "schema_version": 1,
        "protocol": "parcel-sorter-competition-mvp-delivery-v1",
        "status": "competition_mvp_passed",
        "checkpoint": "model",
        "result": result,
        "gate_decision": "evidence/posttrain/gate-decision.json",
        "campaign_audit": (
            Path("evidence")
            / "posttrain"
            / campaign_path.relative_to(posttrain)
        ).as_posix(),
        "gate_decision_sha256": _sha256(gate_path),
        "campaign_audit_sha256": _sha256(campaign_path),
        "command_files": {
            "training": "commands/TRAINING_COMMAND.sh",
            "evaluation": "commands/EVALUATION_COMMAND.sh",
        },
        "rocm_evidence": rocm_evidence,
        "demo_video_index": "DEMO_VIDEOS.json",
        "demo_video_count": len(demo_videos),
        "fixed_seed_contract": {
            "training_seed": TRAINING_SEED,
            "runtime_seed": RUNTIME_SEED,
            "inference_seeds": list(INFERENCE_SEEDS),
        },
        "claim_boundary": (
            "Competition simulation MVP only: complete strict pure-VLA task success "
            "on the frozen three-run smoke design, not real-robot or paper-grade evidence."
        ),
    }
    (output / "RESULTS.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "DELIVERY_MANIFEST.json":
            files.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    manifest = {
        "schema_version": 1,
        "protocol": "parcel-sorter-competition-delivery-manifest-v1",
        "files": files,
    }
    (output / "DELIVERY_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    archive = output.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(output, arcname=output.name)
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(f"{_sha256(archive)}  {archive.name}\n", encoding="ascii")
    subprocess.run([sys.executable, str(output / "VERIFY_DELIVERY.py")], check=True)
    print(
        json.dumps(
            {
                "output": str(output),
                "archive": str(archive),
                "archive_sha256": _sha256(archive),
                "pure_vla_successes": result["pure_vla_complete_successes"],
                "trials": result["trials"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
