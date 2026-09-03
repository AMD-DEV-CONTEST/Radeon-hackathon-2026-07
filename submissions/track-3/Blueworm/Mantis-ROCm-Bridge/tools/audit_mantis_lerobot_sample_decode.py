#!/usr/bin/env python3
"""Audit bounded decoded samples of a local Mantis LeRobot dataset.

Decodes only the first, midpoint, and last frame of every episode and emits a
versioned JSON receipt.  The dataset is read strictly read-only: nothing is
downloaded, nothing is mutated, and LeRobot's network layer is never invoked.

By default the primary evidence uses the real LeRobot runtime -
``LeRobotDataset(repo_id, root=<dataset_root>, download_videos=False,
force_cache_sync=False)`` decoded via ``dataset[index]`` - so the receipt proves
the genuine decode path.  ``--loader parquet`` switches to the direct-parquet
cross-check, which reads the image cell and applies ``ToTensor`` directly and is
kept only as a version-stable cross-check.  The chosen ``loader_mode`` is
recorded in the receipt so the two paths are never confused.  Refuses to
overwrite an existing output, matching the other audit CLIs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.sample_decode_gate import (
    LeRobotRuntimeFrameSource,
    LeRobotSampleFrameSource,
    audit_sample_decode,
)


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument(
        "--repo-id",
        default=None,
        help=(
            "LeRobot repo_id label passed to LeRobotDataset; required when "
            "--loader lerobot (the default)."
        ),
    )
    parser.add_argument(
        "--loader",
        choices=["lerobot", "parquet"],
        default="lerobot",
        help=(
            "decode path: 'lerobot' (default) uses the real LeRobotDataset "
            "runtime; 'parquet' uses the direct-parquet cross-check."
        ),
    )
    parser.add_argument(
        "--gate",
        type=Path,
        default=ROOT / "configs/sample-decode-gate-v1.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    dataset_root = args.dataset_root.resolve()
    if args.loader == "lerobot":
        if not args.repo_id:
            parser.error("--repo-id is required for --loader lerobot")
        frame_source = LeRobotRuntimeFrameSource(args.repo_id, dataset_root)
    else:
        frame_source = LeRobotSampleFrameSource(dataset_root)

    gate_path = args.gate.resolve()
    gate = load_json(gate_path)
    gate_sha256 = _sha256(gate_path)
    receipt = audit_sample_decode(
        frame_source,
        gate=gate,
        gate_sha256=gate_sha256,
    )
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        if args.output.exists():
            parser.error(f"refusing to overwrite output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if receipt["sample_decode_gate_pass"] else 2


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
