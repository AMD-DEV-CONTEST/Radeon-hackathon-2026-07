"""Create one hash-bound ablation record from an observed benchmark artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from buildguard.evaluation.ablation import REQUIRED_GROUPS, MeasuredAblationRun


def digest_path(path: Path) -> str:
    digest = hashlib.sha256()
    candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    for candidate in candidates:
        if path.is_dir():
            digest.update(candidate.relative_to(path).as_posix().encode())
        with candidate.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def git_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
    ).strip()


def numeric_metrics(payload: dict[str, Any]) -> dict[str, float]:
    source = payload.get("metrics", payload)
    if not isinstance(source, dict):
        raise TypeError("metrics artifact must be an object or contain a metrics object")
    result = {
        str(key): float(value)
        for key, value in source.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if not result:
        raise ValueError("metrics artifact contains no numeric measurements")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=sorted(REQUIRED_GROUPS), required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--metrics-file", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifact", action="append", type=Path, default=[])
    parser.add_argument("--sample-count", type=int, required=True)
    parser.add_argument("--started-at", required=True, help="ISO-8601 benchmark start")
    parser.add_argument("--gpu-name", default=os.environ.get("BG_GPU_NAME"))
    parser.add_argument("--rocm-version", default=os.environ.get("BG_ROCM_VERSION"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    required_variant = REQUIRED_GROUPS[args.group][1]
    if args.variant not in required_variant:
        raise ValueError(f"variant must be one of {required_variant}")
    if not args.gpu_name or not args.rocm_version:
        raise ValueError("Provide observed --gpu-name and --rocm-version (or BG_* variables)")
    for path in (args.metrics_file, args.dataset, args.config, *args.artifact):
        if not path.exists():
            raise FileNotFoundError(path)
    payload = json.loads(args.metrics_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("metrics artifact root must be an object")
    if (
        payload.get("source") != "measured"
        or payload.get("mock") is not False
        or payload.get("status") != "PASS"
    ):
        raise ValueError(
            "metrics artifact must explicitly be a PASS measured non-mock result"
        )
    started_at = datetime.fromisoformat(args.started_at)
    if started_at.tzinfo is None:
        raise ValueError("started-at must include a timezone")
    artifacts = list(
        dict.fromkeys(
            [args.metrics_file.resolve(), *[path.resolve() for path in args.artifact]]
        )
    )
    record = MeasuredAblationRun(
        group=args.group,
        variant=args.variant,
        status="PASS",
        source="measured",
        mock=False,
        dataset_sha256=digest_path(args.dataset),
        code_revision=git_revision(),
        configuration_sha256=digest_path(args.config),
        host=platform.node(),
        gpu_name=args.gpu_name,
        rocm_version=args.rocm_version,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        sample_count=args.sample_count,
        metrics=numeric_metrics(payload),
        artifact_paths=artifacts,
        artifact_sha256={str(path): digest_path(path) for path in artifacts},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
