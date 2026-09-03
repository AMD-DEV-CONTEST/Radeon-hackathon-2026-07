#!/usr/bin/env python3
"""Supervise a no-clobber ROCm submission-image build on a Docker host.

The build host does not need an AMD GPU. A successful build and CPU-only import
smoke establish image materialization and provenance only. Strict ROCm runtime
verification remains a separate Radeon-worker gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.STDOUT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        check=False,
        stdout=stdout,
        stderr=stderr,
    )


def write_exclusive(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--tag",
        default="mantis-genesis-lerobot-rocm:submission-v2-20260727-v1",
    )
    parser.add_argument(
        "--base-image",
        help=(
            "optional registry mirror reference passed only as the Dockerfile "
            "BASE_IMAGE build argument; the frozen public image identity remains "
            "recorded by the container contract"
        ),
    )
    parser.add_argument("--save-image", type=Path)
    args = parser.parse_args()

    context = args.context.resolve()
    evidence = args.evidence.resolve()
    if not context.is_dir():
        parser.error(f"context is not a directory: {context}")
    if evidence.exists():
        parser.error(f"evidence path already exists: {evidence}")
    if args.save_image is not None and args.save_image.exists():
        parser.error(f"saved image path already exists: {args.save_image}")
    evidence.mkdir(parents=True, exist_ok=False)

    write_exclusive(evidence / "started_at_utc.txt", utc_now() + "\n")
    build_argv = [
        "docker",
        "build",
        "--pull",
        "--file",
        "docker/Dockerfile.rocm-submission",
        "--tag",
        args.tag,
    ]
    if args.base_image:
        build_argv.extend(["--build-arg", f"BASE_IMAGE={args.base_image}"])
    build_argv.append(".")
    write_exclusive(
        evidence / "build_command.json",
        json.dumps(
            {
                "argv": build_argv,
                "base_image_transport_override": args.base_image,
                "context": context.as_posix(),
                "tag": args.tag,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    docker_version = run(["docker", "version"])
    write_exclusive(evidence / "docker_version.txt", docker_version.stdout)
    source_files = sorted(path for path in context.rglob("*") if path.is_file())
    with (evidence / "source.SHA256SUMS").open("x", encoding="utf-8") as stream:
        for source in source_files:
            stream.write(
                f"{sha256_file(source)}  {source.relative_to(context).as_posix()}\n"
            )

    with (evidence / "build.log").open("x", encoding="utf-8") as build_log:
        process = subprocess.run(
            build_argv,
            cwd=context,
            text=True,
            check=False,
            stdout=build_log,
            stderr=subprocess.STDOUT,
        )
    write_exclusive(evidence / "build.exit_code", f"{process.returncode}\n")
    if process.returncode != 0:
        write_exclusive(evidence / "status", "FAILED_BUILD\n")
        write_exclusive(evidence / "finished_at_utc.txt", utc_now() + "\n")
        return process.returncode or 2

    inspect = run(["docker", "image", "inspect", args.tag])
    write_exclusive(evidence / "image_inspect.json", inspect.stdout)
    smoke_code = (
        "import json, numpy, skimage, torch, lerobot, genesis; "
        "print(json.dumps({"
        "'torch':torch.__version__,"
        "'hip':torch.version.hip,"
        "'numpy':numpy.__version__,"
        "'skimage':skimage.__version__,"
        "'lerobot':lerobot.__version__,"
        "'genesis_file':genesis.__file__"
        "}, sort_keys=True))"
    )
    smoke = run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python3",
            args.tag,
            "-c",
            smoke_code,
        ]
    )
    write_exclusive(evidence / "cpu_import_smoke.log", smoke.stdout)
    write_exclusive(evidence / "cpu_import_smoke.exit_code", f"{smoke.returncode}\n")
    if smoke.returncode != 0:
        write_exclusive(evidence / "status", "FAILED_CPU_IMPORT_SMOKE\n")
        write_exclusive(evidence / "finished_at_utc.txt", utc_now() + "\n")
        return smoke.returncode or 2

    saved_image: dict[str, Any] | None = None
    if args.save_image is not None:
        args.save_image.parent.mkdir(parents=True, exist_ok=True)
        save = run(
            ["docker", "image", "save", "--output", str(args.save_image), args.tag]
        )
        write_exclusive(evidence / "image_save.log", save.stdout)
        write_exclusive(evidence / "image_save.exit_code", f"{save.returncode}\n")
        if save.returncode != 0:
            write_exclusive(evidence / "status", "FAILED_IMAGE_SAVE\n")
            write_exclusive(evidence / "finished_at_utc.txt", utc_now() + "\n")
            return save.returncode or 2
        saved_image = {
            "path": args.save_image.as_posix(),
            "size_bytes": args.save_image.stat().st_size,
            "sha256": sha256_file(args.save_image),
        }

    receipt = {
        "schema_version": 1,
        "status": "COMPLETE_BUILD_PROVENANCE",
        "tag": args.tag,
        "base_image_transport_override": args.base_image,
        "build_host_amd_gpu_required": False,
        "strict_rocm_runtime_verified": False,
        "image_inspect_sha256": sha256_file(evidence / "image_inspect.json"),
        "source_manifest_sha256": sha256_file(evidence / "source.SHA256SUMS"),
        "saved_image": saved_image,
        "claim_boundary": (
            "CPU-host image build and import provenance only. This does not prove "
            "AMD GPU visibility, Genesis gs.amdgpu execution, training, inference, "
            "task success, robustness, or official-runtime identity."
        ),
    }
    write_exclusive(
        evidence / "receipt.json",
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    )
    write_exclusive(evidence / "status", "COMPLETE_BUILD_PROVENANCE\n")
    write_exclusive(evidence / "finished_at_utc.txt", utc_now() + "\n")
    checksum_files = sorted(
        path
        for path in evidence.iterdir()
        if path.is_file() and path.name != "final_evidence.SHA256SUMS"
    )
    with (evidence / "final_evidence.SHA256SUMS").open(
        "x", encoding="utf-8"
    ) as stream:
        for path in checksum_files:
            stream.write(f"{sha256_file(path)}  {path.name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
