#!/usr/bin/env python3
"""Prepare, inspect, verify, and finalize Radeon Story Studio runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from .amd_story_studio import (
        StoryStudioManifest,
        finalize_storyboard,
        sha256_file,
    )
    from .radeon_cloud_execution import (
        RadeonCloudJob,
        build_cloud_package,
        inspect_cloud_package,
        verify_cloud_result,
    )
    from .rendering_engine import ExecutionPlan
except ImportError:
    from amd_story_studio import (
        StoryStudioManifest,
        finalize_storyboard,
        sha256_file,
    )
    from radeon_cloud_execution import (
        RadeonCloudJob,
        build_cloud_package,
        inspect_cloud_package,
        verify_cloud_result,
    )
    from rendering_engine import ExecutionPlan


def _dump(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def prepare_package(
    *,
    manifest_path: Path,
    output_directory: Path,
    remote_python: str,
    timeout_seconds: float,
) -> dict[str, object]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = StoryStudioManifest.from_path(manifest_path)
    output_directory = output_directory.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    runner = Path(__file__).with_name("amd_story_studio.py").resolve()
    plan = ExecutionPlan(
        specification_id=manifest.manifest_id,
        backend="radeon-cloud",
        model={
            **manifest.model.as_dict(),
            "core_inference": "PyTorch + Diffusers on ROCm",
            "reference_conditioning": "Diffusers image-to-image",
        },
        resolved_request={
            "manifest_id": manifest.manifest_id,
            "project_id": manifest.project_id,
            "scene_count": len(manifest.scenes),
            "total_candidates": manifest.total_images,
            "reference_conditioned_scenes": sum(
                scene.generation_mode == "image_to_image"
                for scene in manifest.scenes
            ),
            "canvas": {"width": manifest.width, "height": manifest.height},
            "fail_closed_editorial_review": True,
        },
        output_contract={
            "directory": "outputs",
            "required": [
                "run-report.json",
                "review-template.json",
                "contact-sheet.png",
                "candidates",
                "evidence",
            ],
            "media_type": "image/png",
        },
        runtime_requirements={
            "hardware": "AMD Radeon GPU from Radeon Cloud",
            "software_stack": "ROCm",
            "torch_cuda_required": True,
            "torch_hip_required": True,
            "network_required_for_model_download": True,
            "core_dtype_must_be_verified": True,
        },
        evidence={
            "manifest_sha256": sha256_file(manifest_path),
            "runner_sha256": sha256_file(runner),
            "contest_track": (
                "Track 1: Development of Multimodal Content Creation Tools"
            ),
            "unsafe_candidates_must_not_be_selected": True,
        },
    )
    job = RadeonCloudJob.from_mapping(
        {
            "schema_version": "aahj.radeon-cloud-job/v1",
            "argv": [
                remote_python,
                "amd_story_studio.py",
                "run",
                "--manifest",
                "story-studio.json",
                "--output",
                "../outputs",
            ],
            "environment": {
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "PYTHONHASHSEED": "0",
                "TOKENIZERS_PARALLELISM": "false",
            },
            "working_directory": "payload",
            "output_paths": ["outputs"],
            "timeout_seconds": timeout_seconds,
        }
    )

    plan_path = output_directory / "execution-plan.json"
    job_path = output_directory / "job.json"
    package_path = output_directory / "execution-package.tar.gz"
    plan_path.write_text(
        json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    job_path.write_text(
        json.dumps(job.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    build_cloud_package(
        execution_plan=plan,
        job=job,
        payload_files={
            "payload/amd_story_studio.py": runner,
            "payload/story-studio.json": manifest_path,
        },
        destination=package_path,
    )
    package = inspect_cloud_package(package_path)
    return {
        "manifest_id": manifest.manifest_id,
        "plan_id": plan.plan_id,
        "job_id": job.job_id,
        "package": {
            **package,
            "path": str(package_path),
            "sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        },
        "plan_path": str(plan_path),
        "job_path": str(job_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage the AAHJ AMD DevMaster Radeon Story Studio demo"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--output-directory", type=Path, required=True)
    prepare.add_argument("--remote-python", default="python3")
    prepare.add_argument("--timeout-seconds", type=float, default=3600)

    inspect = sub.add_parser("inspect-package")
    inspect.add_argument("package", type=Path)

    verify = sub.add_parser("verify-result")
    verify.add_argument("result", type=Path)
    verify.add_argument("--expected-plan-id")
    verify.add_argument("--result-root", type=Path)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--manifest", type=Path, required=True)
    finalize.add_argument("--run-report", type=Path, required=True)
    finalize.add_argument("--review", type=Path, required=True)
    finalize.add_argument("--output-directory", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.timeout_seconds <= 0:
                raise ValueError("timeout-seconds must be greater than zero")
            _dump(
                prepare_package(
                    manifest_path=args.manifest,
                    output_directory=args.output_directory,
                    remote_python=args.remote_python,
                    timeout_seconds=args.timeout_seconds,
                )
            )
            return 0
        if args.command == "inspect-package":
            _dump(inspect_cloud_package(args.package))
            return 0
        if args.command == "verify-result":
            result = verify_cloud_result(
                args.result,
                expected_plan_id=args.expected_plan_id,
                result_root=args.result_root,
            )
            _dump(
                {
                    "plan_id": result.plan_id,
                    "result_id": result.result_id,
                    "status": result.status,
                    "outputs": len(result.outputs),
                }
            )
            return 0 if result.status == "succeeded" else 1
        if args.command == "finalize":
            manifest = StoryStudioManifest.from_path(args.manifest)
            acceptance = finalize_storyboard(
                manifest,
                args.run_report,
                args.review,
                args.output_directory,
            )
            _dump(json.loads(acceptance.read_text(encoding="utf-8")))
            return 0
        raise AssertionError(args.command)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
