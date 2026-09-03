# -*- coding: utf-8 -*-
"""Normalize immutable smoke, micro and full metrics into release-gate profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "yijian-training-stage-profile-v1"
REVISION = "40c069824f4251a91eefaf281ebe4c544efd3e18"


class ProfileError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProfileError(f"{path} must contain a JSON object")
    return value


def build(stage: str, metrics_path: Path, hardware_path: Path) -> dict[str, Any]:
    metrics = read(metrics_path)
    hardware = read(hardware_path)
    if hardware.get("modelRevision") != REVISION:
        raise ProfileError("base revision mismatch")
    if float(metrics.get("peakReservedGiB") or 999) > 45:
        raise ProfileError("peak reserved VRAM exceeds 45 GiB")
    expected_steps = {"smoke": 4, "micro": 30, "full": 90}[stage]
    optimizer_steps = int(metrics.get("optimizerSteps") or 0)
    if stage == "smoke" and not optimizer_steps:
        # The first immutable v2 smoke predates explicit step recording. Four
        # max-steps over eight rows is represented by epoch=0.5 in its metrics.
        if int(metrics.get("trainExamples") or 0) != 8 or abs(float(metrics.get("epoch") or 0) - .5) > 1e-6:
            raise ProfileError("legacy smoke metrics do not prove four optimizer steps")
        optimizer_steps = 4
    if optimizer_steps != expected_steps:
        raise ProfileError(f"{stage} optimizer steps mismatch")
    if stage != "smoke" and metrics.get("passed") is not True:
        raise ProfileError(f"{stage} metrics have not passed")
    profile = {
        **metrics,
        "schemaVersion": SCHEMA,
        "stage": stage,
        "passed": True,
        "optimizerSteps": optimizer_steps,
        "modelRevision": REVISION,
        "metricsSha256": sha256_file(metrics_path),
        "hardwareSha256": sha256_file(hardware_path),
        "hardware": {
            key: hardware.get(key)
            for key in ("host", "torch", "hip", "transformers", "peft", "device", "vramGiB")
        },
    }
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("smoke", "micro", "full"), required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--hardware", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.stage, args.metrics.resolve(), args.hardware.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
