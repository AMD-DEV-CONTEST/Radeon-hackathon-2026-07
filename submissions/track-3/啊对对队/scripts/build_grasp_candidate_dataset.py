#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_scoring import (
    build_grasp_candidate_dataset,
    load_grasp_split_protocol,
    sha256_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an auditable grasp-candidate label dataset from formal counterfactuals."
    )
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument(
        "--manifest",
        type=Path,
        action="append",
        default=[],
        help="consume only validated complete/reused labels from a collection manifest",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def manifest_label_paths(path: Path, protocol_sha256: str) -> list[Path]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("protocol_sha256")) != protocol_sha256:
        raise ValueError(f"collection manifest protocol does not match: {path}")
    result: list[Path] = []
    for row in payload.get("runs", ()):
        status = str(row.get("status"))
        if status == "skipped_inactive_gate":
            continue
        if status not in {"complete", "reused"}:
            raise ValueError(
                f"collection manifest is incomplete at status {status!r}: {path}"
            )
        if str(row.get("source_status")) != "complete":
            raise ValueError(
                f"collection manifest row has no complete labels: {path}"
            )
        source = Path(str(row["output"]))
        if sha256_file(source) != str(row.get("sha256")):
            raise ValueError(f"collection label hash does not match manifest: {source}")
        result.append(source)
    if not result:
        raise ValueError(f"collection manifest contains no complete labels: {path}")
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    assignments = load_grasp_split_protocol(args.protocol)
    protocol_sha256 = sha256_file(args.protocol)
    input_paths = list(args.input)
    for manifest in args.manifest:
        input_paths.extend(manifest_label_paths(manifest.resolve(), protocol_sha256))
    if not input_paths:
        raise ValueError("provide at least one --input or --manifest")
    sources: list[tuple[str, dict[str, Any], str, str]] = []
    for path in input_paths:
        resolved = path.resolve()
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        key = (str(payload["profile"]), int(payload["episode"]))
        try:
            split = assignments[key]
        except KeyError as exc:
            raise ValueError(
                f"counterfactual source is not assigned by the frozen protocol: {key}"
            ) from exc
        try:
            source = str(resolved.relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
        except ValueError:
            source = str(resolved)
        sources.append((source, payload, sha256_file(resolved), split))
    dataset = build_grasp_candidate_dataset(sources)
    dataset["protocol"] = str(args.protocol.resolve())
    dataset["protocol_sha256"] = protocol_sha256
    return dataset


def main() -> int:
    args = parse_args()
    payload = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "dataset_sha256": payload["dataset_sha256"],
                "row_count": payload["row_count"],
                "group_count": payload["group_count"],
                "splits": payload["splits"],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
