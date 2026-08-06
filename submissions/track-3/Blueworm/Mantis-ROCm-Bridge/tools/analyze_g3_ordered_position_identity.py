#!/usr/bin/env python3
"""Correct ordered-slot discontinuities in static G3 evaluator evidence.

The strict evaluator records three bowl positions in task-dependent order,
not with persistent entity identifiers. Treating a list slot as a physical
bowl can therefore create a large false displacement when two entries swap.
This analyzer restores temporal identity by choosing, at every frame, the
minimum-total-displacement assignment to the previous frame.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


Point = tuple[float, float, float]
Assignment = tuple[int, int, int]
IDENTITY_ASSIGNMENT: Assignment = (0, 1, 2)


def _point(value: Any) -> Point:
    if not isinstance(value, list) or len(value) < 3:
        raise ValueError(f"invalid 3D position: {value!r}")
    point = tuple(float(item) for item in value[:3])
    if not all(math.isfinite(item) for item in point):
        raise ValueError(f"non-finite 3D position: {value!r}")
    return point  # type: ignore[return-value]


def _squared_distance(left: Point, right: Point) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right))


def _distance(left: Point, right: Point) -> float:
    return math.sqrt(_squared_distance(left, right))


def associate_ordered_positions(
    frames: Sequence[Sequence[Point]],
) -> tuple[list[list[Point]], list[Assignment]]:
    """Return temporally associated identity tracks and frame assignments."""

    if not frames:
        return [], []
    if any(len(frame) != 3 for frame in frames):
        raise ValueError("every frame must contain exactly three positions")

    previous = list(frames[0])
    associated = [previous.copy()]
    assignments = [IDENTITY_ASSIGNMENT]

    for frame in frames[1:]:
        assignment = min(
            itertools.permutations(range(3)),
            key=lambda candidate: sum(
                _squared_distance(previous[identity], frame[candidate[identity]])
                for identity in range(3)
            ),
        )
        typed_assignment: Assignment = tuple(assignment)  # type: ignore[assignment]
        current = [
            frame[typed_assignment[identity]]
            for identity in range(3)
        ]
        associated.append(current)
        assignments.append(typed_assignment)
        previous = current

    return associated, assignments


def _track_metrics(points: Sequence[Point]) -> dict[str, Any]:
    if not points:
        raise ValueError("empty position track")
    initial = points[0]
    final = points[-1]
    xy = [
        math.hypot(point[0] - initial[0], point[1] - initial[1])
        for point in points
    ]
    displacement = [_distance(point, initial) for point in points]
    step = [
        _distance(points[index], points[index - 1])
        for index in range(1, len(points))
    ]
    return {
        "sample_count": len(points),
        "initial_xyz_m": list(initial),
        "final_xyz_m": list(final),
        "maximum_displacement_from_initial_m": max(displacement),
        "maximum_xy_displacement_from_initial_m": max(xy),
        "maximum_positive_z_from_initial_m": max(
            point[2] - initial[2] for point in points
        ),
        "maximum_consecutive_step_m": max(step, default=0.0),
    }


def analyze_ordered_position_rows(
    rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    frames: list[list[Point]] = []
    for row in rows:
        ordered = row.get("ordered_positions_xyz_m")
        if not isinstance(ordered, list) or len(ordered) < 3:
            continue
        frames.append([_point(value) for value in ordered[:3]])
    if not frames:
        raise ValueError("no valid ordered_positions_xyz_m frames")

    associated, assignments = associate_ordered_positions(frames)
    raw_tracks = [
        [frame[slot] for frame in frames]
        for slot in range(3)
    ]
    identity_tracks = [
        [frame[identity] for frame in associated]
        for identity in range(3)
    ]
    assignment_counts = Counter(
        ",".join(str(index) for index in assignment)
        for assignment in assignments
    )
    raw_metrics = [_track_metrics(track) for track in raw_tracks]
    identity_metrics = [_track_metrics(track) for track in identity_tracks]
    maximum_raw_xy = max(
        metric["maximum_xy_displacement_from_initial_m"]
        for metric in raw_metrics
    )
    maximum_identity_xy = max(
        metric["maximum_xy_displacement_from_initial_m"]
        for metric in identity_metrics
    )
    nonidentity_rows = sum(
        assignment != IDENTITY_ASSIGNMENT
        for assignment in assignments
    )
    ordering_artifact = (
        nonidentity_rows > 0
        and maximum_raw_xy > 0.05
        and maximum_raw_xy > 10.0 * maximum_identity_xy
    )
    return {
        "schema_version": 1,
        "frame_count": len(frames),
        "association_method": (
            "exhaustive three-object minimum squared displacement "
            "to previous associated frame"
        ),
        "assignment_counts": dict(sorted(assignment_counts.items())),
        "nonidentity_assignment_row_count": nonidentity_rows,
        "raw_ordered_slot_metrics": raw_metrics,
        "temporally_associated_identity_metrics": identity_metrics,
        "maximum_raw_slot_xy_displacement_m": maximum_raw_xy,
        "maximum_associated_identity_xy_displacement_m": maximum_identity_xy,
        "ordering_artifact_detected": ordering_artifact,
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"{path}:{number} is not a JSON object")
        rows.append(value)
    return rows


def analyze_seed(input_root: Path, seed: int) -> dict[str, Any]:
    evaluator_path = (
        input_root
        / "g3_batch"
        / f"seed{seed}"
        / "strict_evaluator.jsonl"
    )
    result = analyze_ordered_position_rows(read_jsonl(evaluator_path))
    result.update(
        {
            "seed": seed,
            "source_path": str(evaluator_path),
            "source_sha256": hashlib.sha256(
                evaluator_path.read_bytes()
            ).hexdigest(),
        }
    )
    return result


def write_outputs(
    output_dir: Path,
    analyses: Sequence[dict[str, Any]],
) -> None:
    if output_dir.exists():
        raise FileExistsError(f"refusing existing output: {output_dir}")
    output_dir.mkdir(parents=True)

    aggregate = {
        "schema_version": 1,
        "seed_count": len(analyses),
        "seeds": [analysis["seed"] for analysis in analyses],
        "all_ordering_artifacts_detected": all(
            analysis["ordering_artifact_detected"]
            for analysis in analyses
        ),
        "analyses": list(analyses),
    }
    (output_dir / "identity_correction.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with (output_dir / "identity_correction.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "seed",
                "frame_count",
                "nonidentity_assignment_row_count",
                "maximum_raw_slot_xy_displacement_m",
                "maximum_associated_identity_xy_displacement_m",
                "maximum_associated_identity_positive_z_m",
                "maximum_associated_identity_consecutive_step_m",
                "ordering_artifact_detected",
                "source_sha256",
            ),
        )
        writer.writeheader()
        for analysis in analyses:
            identities = analysis[
                "temporally_associated_identity_metrics"
            ]
            writer.writerow(
                {
                    "seed": analysis["seed"],
                    "frame_count": analysis["frame_count"],
                    "nonidentity_assignment_row_count": analysis[
                        "nonidentity_assignment_row_count"
                    ],
                    "maximum_raw_slot_xy_displacement_m": analysis[
                        "maximum_raw_slot_xy_displacement_m"
                    ],
                    "maximum_associated_identity_xy_displacement_m": analysis[
                        "maximum_associated_identity_xy_displacement_m"
                    ],
                    "maximum_associated_identity_positive_z_m": max(
                        metric["maximum_positive_z_from_initial_m"]
                        for metric in identities
                    ),
                    "maximum_associated_identity_consecutive_step_m": max(
                        metric["maximum_consecutive_step_m"]
                        for metric in identities
                    ),
                    "ordering_artifact_detected": analysis[
                        "ordering_artifact_detected"
                    ],
                    "source_sha256": analysis["source_sha256"],
                }
            )

    lines = [
        "# Static G3 ordered-position identity correction",
        "",
        "| Seed | Non-identity rows | Raw-slot max XY (m) | "
        "Associated-identity max XY (m) | Artifact |",
        "|---:|---:|---:|---:|:---:|",
    ]
    for analysis in analyses:
        lines.append(
            "| {seed} | {rows} | {raw:.9f} | {tracked:.9f} | {artifact} |".format(
                seed=analysis["seed"],
                rows=analysis["nonidentity_assignment_row_count"],
                raw=analysis["maximum_raw_slot_xy_displacement_m"],
                tracked=analysis[
                    "maximum_associated_identity_xy_displacement_m"
                ],
                artifact=(
                    "yes"
                    if analysis["ordering_artifact_detected"]
                    else "no"
                ),
            )
        )
    lines.extend(
        [
            "",
            "The strict evaluator's ordered list is not a persistent entity-ID "
            "sequence. Raw list-slot displacement must not be interpreted as "
            "physical bowl displacement when the minimum-displacement "
            "association changes.",
            "",
        ]
    )
    (output_dir / "identity_correction.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    manifest_files = (
        "identity_correction.csv",
        "identity_correction.json",
        "identity_correction.md",
    )
    manifest_lines = []
    for name in manifest_files:
        digest = hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
        manifest_lines.append(f"{digest}  {name}")
    (output_dir / "analysis_files.SHA256SUMS").write_text(
        "\n".join(manifest_lines) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=(101, 106, 110),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    analyses = [
        analyze_seed(args.input_root, seed)
        for seed in args.seeds
    ]
    write_outputs(args.output_dir, analyses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
