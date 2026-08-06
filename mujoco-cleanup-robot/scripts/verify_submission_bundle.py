"""Verify the portable judge bundle without running the GPU simulation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_SUBMISSION = PROJECT_ROOT / "final_submission"
OBJECT_NAMES = ("can", "bottle", "cup", "banana")


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def record(name: str, passed: bool) -> None:
        checks[name] = bool(passed)
        if not passed:
            failures.append(name)

    def verify_file(
        name: str,
        path: Path,
        *,
        sha256: str,
        size_bytes: int | None = None,
    ) -> None:
        exists = path.is_file()
        record(f"{name}.exists", exists)
        if not exists:
            return
        if size_bytes is not None:
            record(f"{name}.size", path.stat().st_size == size_bytes)
        record(f"{name}.sha256", _sha256(path) == sha256)

    lock = _json(FINAL_SUBMISSION / "tidybot_full_learned_v1.json")
    models = lock["models"]
    verify_file(
        "model.lap_route",
        FINAL_SUBMISSION / "models/lap_route/policy.pt",
        sha256=models["lap_route"]["sha256"],
    )
    for object_name in OBJECT_NAMES:
        verify_file(
            f"model.object_route.{object_name}",
            FINAL_SUBMISSION / f"models/object_routes/{object_name}.pt",
            sha256=models["object_routes"][object_name]["sha256"],
        )
        verify_file(
            f"model.arm.{object_name}",
            FINAL_SUBMISSION / f"models/arm/{object_name}.pt",
            sha256=models["arm"][object_name]["sha256"],
        )
    verify_file(
        "model.detector",
        FINAL_SUBMISSION / "models/detector/best.pt",
        sha256=models["detector"]["sha256"],
    )

    video_validation = _json(FINAL_SUBMISSION / "metrics/video_validation.json")
    record("videos.validation_report", video_validation.get("valid") is True)
    videos = video_validation.get("videos", [])
    record("videos.count", isinstance(videos, list) and len(videos) == 7)
    if isinstance(videos, list):
        for index, item in enumerate(videos):
            if not isinstance(item, dict):
                record(f"video.{index}.record", False)
                continue
            relative_path = str(item.get("path", ""))
            verify_file(
                f"video.{relative_path}",
                FINAL_SUBMISSION / relative_path,
                sha256=str(item.get("sha256", "")),
                size_bytes=int(item.get("size_bytes", -1)),
            )

    summary = _json(FINAL_SUBMISSION / "metrics/summary.json")
    result = _json(FINAL_SUBMISSION / "metrics/result.json")
    objects = summary.get("objects", [])
    record("result.success", summary.get("success") is True and result.get("success") is True)
    record("result.one_lap", summary.get("one_lap_complete") is True)
    record(
        "result.four_objects",
        isinstance(objects, list)
        and [item.get("object_name") for item in objects] == list(OBJECT_NAMES),
    )
    record(
        "result.sensor_verified",
        isinstance(objects, list)
        and all(item.get("sensor_verified") is True for item in objects),
    )
    record(
        "result.stable_deposits",
        isinstance(objects, list)
        and all(item.get("stable_deposit") is True for item in objects),
    )
    record(
        "result.video_ledger",
        result.get("control_steps") == result.get("video_frames")
        and int(result.get("video_frames", 0)) > 0,
    )
    record("result.integrity_clean", result.get("integrity", {}).get("clean") is True)
    record("result.no_teacher", summary.get("runtime_teacher_used") is False)
    record("result.no_action_replay", summary.get("runtime_action_replay_used") is False)
    record("result.no_ik", summary.get("runtime_ik_used") is False)
    record(
        "result.no_object_truth_control",
        summary.get("runtime_object_truth_used_for_control") is False,
    )

    record("source.repository.README.md", (PROJECT_ROOT.parent / "README.md").is_file())
    for relative_path in (
        "THIRD_PARTY_NOTICES.md",
        "requirements-rocm.txt",
        "docs/full_learned_run_2026-08-06.md",
        "final_submission/tidybot_full_learned_v1.json",
        "scripts/verify_submission_bundle.py",
        "src/realtime_cleanup/__init__.py",
        "src/realtime_cleanup/integrity.py",
        "src/realtime_cleanup/perception.py",
        "src/realtime_cleanup/provenance.py",
        "src/realtime_cleanup/rocm_telemetry.py",
        "src/realtime_cleanup/telemetry.py",
        "src/realtime_cleanup/tidybot_fixed_arm_policy.py",
        "src/realtime_cleanup/tidybot_full_runtime.py",
        "src/realtime_cleanup/tidybot_full_task.py",
        "src/realtime_cleanup/tidybot_io.py",
        "src/realtime_cleanup/tidybot_perception.py",
        "src/realtime_cleanup/tidybot_route_policy.py",
        "src/realtime_cleanup/tidybot_workspace.py",
        "src/realtime_cleanup/types.py",
        "src/stretch_cleanup/__init__.py",
        "src/stretch_cleanup/integrity.py",
        "src/stretch_cleanup/mobile_platforms.py",
        "src/stretch_cleanup/scene.py",
        "src/stretch_cleanup/tidybot_success.py",
        "scripts/run_tidybot_full_learned.py",
        "scripts/run_with_rocm_telemetry.py",
    ):
        record(f"source.{relative_path}", (PROJECT_ROOT / relative_path).is_file())

    manifest_path = PROJECT_ROOT / "SUBMISSION_MANIFEST.json"
    record("manifest.exists", manifest_path.is_file())
    if manifest_path.is_file():
        manifest = _json(manifest_path)
        records = manifest.get("files", [])
        record("manifest.records", isinstance(records, list) and len(records) > 0)
        manifest_files_valid = isinstance(records, list)
        if isinstance(records, list):
            for item in records:
                if not isinstance(item, dict):
                    manifest_files_valid = False
                    break
                path = PROJECT_ROOT / str(item.get("path", ""))
                if (
                    not path.is_file()
                    or path.stat().st_size != int(item.get("size_bytes", -1))
                    or _sha256(path) != item.get("sha256")
                ):
                    manifest_files_valid = False
                    break
        record("manifest.files", manifest_files_valid)

    report = {
        "valid": not failures,
        "project_root": str(PROJECT_ROOT),
        "checks": len(checks),
        "model_files": 9,
        "video_files": len(videos) if isinstance(videos, list) else 0,
        "failures": failures,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
