#!/usr/bin/env python3
"""Analyze observation-only G3 dynamic diagnostic replays.

The analyzer deliberately separates measurements from causal claims.  It
audits the 250 Hz -> 30 Hz clock, ACT queue chronology, command/readback
tracking, named-bowl motion, robot-bowl contacts, and recorded link-origin
kinematics.  It does not modify a replay and cannot determine the collision
state of an unobserved commanded target configuration.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


PHYSICAL_JOINT_NAMES = (
    "left_shoulder_pitch_joint",
    "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "left_wrist_yaw_joint",
    "left_wrist_pitch_joint",
    "left_wrist_roll_joint",
    "left_clamp_right_joint",
    "left_clamp_left_joint",
    "right_shoulder_pitch_joint",
    "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint",
    "right_elbow_joint",
    "right_wrist_yaw_joint",
    "right_wrist_pitch_joint",
    "right_wrist_roll_joint",
    "right_clamp_right_joint",
    "right_clamp_left_joint",
)


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


def _available_value(item: Any) -> Any:
    if not isinstance(item, dict) or item.get("available") is not True:
        return None
    return item.get("value")


def _finite_vector(value: Any, length: int | None = None) -> list[float] | None:
    if not isinstance(value, list):
        return None
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if length is not None and len(result) != length:
        return None
    if not all(math.isfinite(item) for item in result):
        return None
    return result


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile of an empty sequence")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _named_positions(
    row: dict[str, Any],
    collection: str,
) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    values = row.get("kinematic_state", {}).get(collection, [])
    if not isinstance(values, list):
        return result
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        position = _finite_vector(
            _available_value(item.get("position_xyz_m")),
            3,
        )
        if position is not None:
            result[item["name"]] = position
    return result


def _motion_metrics(
    tracks: dict[str, list[list[float]]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, points in sorted(tracks.items()):
        initial = points[0]
        displacement = [_distance(initial, point) for point in points]
        xy = [
            math.hypot(point[0] - initial[0], point[1] - initial[1])
            for point in points
        ]
        result[name] = {
            "sample_count": len(points),
            "initial_xyz_m": initial,
            "final_xyz_m": points[-1],
            "maximum_displacement_from_initial_m": max(displacement),
            "maximum_xy_displacement_from_initial_m": max(xy),
            "maximum_positive_z_from_initial_m": max(
                point[2] - initial[2] for point in points
            ),
        }
    return result


def _contact_events(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return de-duplicated robot-bowl events from the bowl collection."""

    result: list[dict[str, Any]] = []
    bowls = row.get("contact_state", {}).get("bowls", [])
    if not isinstance(bowls, list):
        return result
    for bowl in bowls:
        if not isinstance(bowl, dict):
            continue
        contacts = bowl.get("contacts", [])
        if not isinstance(contacts, list):
            continue
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            fields = contact.get("fields", {})
            extracted_fields: dict[str, dict[str, Any]] = {}
            if isinstance(fields, dict):
                for name in (
                    "distance",
                    "force",
                    "normal",
                    "penetration",
                    "position",
                ):
                    field = fields.get(name)
                    if isinstance(field, dict):
                        extracted_fields[name] = {
                            "supported": bool(field.get("supported")),
                            "source": field.get("source"),
                            "value": field.get("value"),
                            "error": field.get("error"),
                        }
            result.append(
                {
                    "entity_name": bowl.get("entity_name"),
                    "resolved_pair": contact.get("resolved_pair"),
                    "label_a": contact.get("label_a"),
                    "label_b": contact.get("label_b"),
                    "geom_a": contact.get("geom_a"),
                    "geom_b": contact.get("geom_b"),
                    "forbidden_by_frozen_classifier": bool(
                        contact.get("forbidden_by_frozen_classifier")
                    ),
                    "fields": extracted_fields,
                }
            )
    return result


def _queue_expected(index: int, chunk_size: int) -> tuple[int, int, int, int]:
    action_index = index % chunk_size
    chunk_index = index // chunk_size
    before = 0 if action_index == 0 else chunk_size - action_index
    after = chunk_size - action_index - 1
    return action_index, chunk_index, before, after


def _tracking_vector(row: dict[str, Any]) -> list[float] | None:
    item = (
        row.get("command_target_readback", {})
        .get("full_physical_target_readback_18d", {})
        .get("target_minus_readback_error")
    )
    return _finite_vector(_available_value(item), len(PHYSICAL_JOINT_NAMES))


def _link_approach(
    rows: Sequence[dict[str, Any]],
    link_name: str | None,
    bowl_name: str | None,
    window: int = 3,
) -> dict[str, Any] | None:
    if link_name is None or bowl_name is None or not rows:
        return None

    available_link_names = _named_positions(rows[-1], "robot_links")
    measured_link = link_name if link_name in available_link_names else None
    if measured_link is None and link_name.startswith("right_wrist_"):
        measured_link = "right_wrist_yaw_link"
    if measured_link is None and link_name.startswith("left_wrist_"):
        measured_link = "left_wrist_yaw_link"
    if measured_link not in available_link_names:
        return None

    selected = list(rows[max(0, len(rows) - window) :])
    samples: list[tuple[float, list[float], list[float]]] = []
    for row in selected:
        links = _named_positions(row, "robot_links")
        bowls = _named_positions(row, "bowls")
        timestamp = row.get("clock", {}).get("policy_timestamp_s")
        if (
            measured_link in links
            and bowl_name in bowls
            and isinstance(timestamp, (int, float))
        ):
            samples.append(
                (float(timestamp), links[measured_link], bowls[bowl_name])
            )
    if len(samples) < 2:
        return None

    start_time, start_link, start_bowl = samples[0]
    end_time, end_link, end_bowl = samples[-1]
    elapsed = end_time - start_time
    if elapsed <= 0:
        return None
    velocity = [
        (end_link[index] - start_link[index]) / elapsed
        for index in range(3)
    ]
    start_distance = _distance(start_link, start_bowl)
    end_distance = _distance(end_link, end_bowl)
    return {
        "requested_collision_link": link_name,
        "measured_proxy_link": measured_link,
        "bowl": bowl_name,
        "sample_count": len(samples),
        "elapsed_s": elapsed,
        "link_velocity_xyz_m_s": velocity,
        "link_speed_m_s": math.sqrt(sum(item * item for item in velocity)),
        "link_origin_to_bowl_origin_initial_m": start_distance,
        "link_origin_to_bowl_origin_final_m": end_distance,
        "link_origin_approach_rate_m_s": (
            start_distance - end_distance
        )
        / elapsed,
        "interpretation_boundary": (
            "Origin distance is descriptive; it is not signed mesh clearance."
        ),
    }


def _collision_names(
    terminal_contacts: Sequence[dict[str, Any]],
) -> tuple[str | None, str | None]:
    for contact in terminal_contacts:
        labels = (contact.get("label_a"), contact.get("label_b"))
        link_name: str | None = None
        bowl_name: str | None = None
        for label in labels:
            if not isinstance(label, str):
                continue
            if label.startswith("mantis:"):
                parts = label.split(":")
                if len(parts) >= 2:
                    link_name = parts[1]
            if label.startswith("bowl"):
                bowl_name = label.split(":", 1)[0]
        if link_name is not None and bowl_name is not None:
            return link_name, bowl_name
    return None, None


def analyze_rows(
    rows: Sequence[dict[str, Any]],
    *,
    terminal_reason: str,
    terminal_policy_step: int | None,
    official_terminal_reason: str | None = None,
    official_terminal_policy_step: int | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("dynamic diagnostic input is empty")

    policy_index_mismatches = 0
    clock_hold_mismatches = 0
    simulator_chain_mismatches = 0
    queue_mismatches = 0
    hold_histogram: Counter[int] = Counter()
    saturation_histogram: Counter[str] = Counter()
    tracking_l2: list[float] = []
    joint_abs_errors: list[list[float]] = [
        [] for _ in PHYSICAL_JOINT_NAMES
    ]
    bowl_tracks: dict[str, list[list[float]]] = {}
    contact_row_count = 0
    contact_event_count = 0
    all_contacts: list[dict[str, Any]] = []
    minimum_link_origin_distance = math.inf
    minimum_link_origin_pair: dict[str, Any] | None = None

    for index, row in enumerate(rows):
        clock = row.get("clock", {})
        if row.get("policy_step") != index or clock.get("policy_step") != index:
            policy_index_mismatches += 1
        observed_hold = clock.get("observed_physics_hold_length")
        requested_hold = clock.get("requested_physics_hold_length")
        if isinstance(observed_hold, int):
            hold_histogram[observed_hold] += 1
        if observed_hold != requested_hold:
            clock_hold_mismatches += 1
        if index > 0:
            prior_after = rows[index - 1].get("clock", {}).get(
                "simulator_step_after_hold"
            )
            current_before = clock.get("simulator_step_before_hold")
            if prior_after != current_before:
                simulator_chain_mismatches += 1

        queue = row.get("act_queue", {})
        chunk_size = queue.get("chunk_size")
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            queue_mismatches += 1
        else:
            expected = _queue_expected(index, chunk_size)
            observed = (
                queue.get("action_index_within_chunk"),
                queue.get("chunk_sequence_index"),
                queue.get("queue_before_selection", {}).get("length"),
                queue.get("queue_after_selection", {}).get("length"),
            )
            if observed != expected:
                queue_mismatches += 1
        if queue.get("select_action_call_index") != index + 1:
            queue_mismatches += 1

        command = row.get("command_target_readback", {})
        names = command.get("saturated_action_names", [])
        if isinstance(names, list):
            saturation_histogram.update(
                name for name in names if isinstance(name, str)
            )

        error = _tracking_vector(row)
        if error is not None:
            tracking_l2.append(math.sqrt(sum(item * item for item in error)))
            for joint_index, item in enumerate(error):
                joint_abs_errors[joint_index].append(abs(item))

        bowls = _named_positions(row, "bowls")
        links = _named_positions(row, "robot_links")
        for name, position in bowls.items():
            bowl_tracks.setdefault(name, []).append(position)
        for link_name, link_position in links.items():
            for bowl_name, bowl_position in bowls.items():
                distance = _distance(link_position, bowl_position)
                if distance < minimum_link_origin_distance:
                    minimum_link_origin_distance = distance
                    minimum_link_origin_pair = {
                        "policy_step": index,
                        "link_name": link_name,
                        "bowl_name": bowl_name,
                        "distance_m": distance,
                    }

        contacts = _contact_events(row)
        if contacts:
            contact_row_count += 1
            contact_event_count += len(contacts)
            all_contacts.extend(
                [{"policy_step": index, **contact} for contact in contacts]
            )

    terminal_contacts = _contact_events(rows[-1])
    collision_link, collision_bowl = _collision_names(terminal_contacts)
    terminal_error = _tracking_vector(rows[-1])
    terminal_joint_errors = []
    if terminal_error is not None:
        terminal_joint_errors = sorted(
            (
                {
                    "joint_index": index,
                    "joint_name": name,
                    "target_minus_readback_rad": terminal_error[index],
                    "absolute_error_rad": abs(terminal_error[index]),
                }
                for index, name in enumerate(PHYSICAL_JOINT_NAMES)
            ),
            key=lambda item: item["absolute_error_rad"],
            reverse=True,
        )

    per_joint = []
    for index, name in enumerate(PHYSICAL_JOINT_NAMES):
        values = joint_abs_errors[index]
        per_joint.append(
            {
                "joint_index": index,
                "joint_name": name,
                "maximum_absolute_error_rad": max(values, default=None),
                "p95_absolute_error_rad": (
                    _nearest_rank(values, 0.95) if values else None
                ),
            }
        )

    terminal_delta = None
    if (
        terminal_policy_step is not None
        and official_terminal_policy_step is not None
    ):
        terminal_delta = (
            terminal_policy_step - official_terminal_policy_step
        )

    clock_queue_exact = (
        policy_index_mismatches == 0
        and clock_hold_mismatches == 0
        and simulator_chain_mismatches == 0
        and queue_mismatches == 0
    )
    source_mesh_contacts = [
        contact
        for contact in all_contacts
        if "source_mesh_collision" in str(contact.get("resolved_pair"))
    ]
    return {
        "schema_version": 1,
        "record_count": len(rows),
        "terminal": {
            "reason": terminal_reason,
            "policy_step": terminal_policy_step,
            "official_reference_reason": official_terminal_reason,
            "official_reference_policy_step": official_terminal_policy_step,
            "policy_step_delta_from_official": terminal_delta,
        },
        "clock_and_queue_audit": {
            "policy_index_mismatch_count": policy_index_mismatches,
            "clock_hold_mismatch_count": clock_hold_mismatches,
            "simulator_step_chain_mismatch_count": (
                simulator_chain_mismatches
            ),
            "act_queue_mismatch_count": queue_mismatches,
            "physics_hold_histogram": {
                str(key): value for key, value in sorted(hold_histogram.items())
            },
            "exact": clock_queue_exact,
        },
        "tracking": {
            "sample_count": len(tracking_l2),
            "maximum_l2_error_rad": max(tracking_l2, default=None),
            "p95_l2_error_rad": (
                _nearest_rank(tracking_l2, 0.95) if tracking_l2 else None
            ),
            "terminal_l2_error_rad": (
                math.sqrt(sum(item * item for item in terminal_error))
                if terminal_error is not None
                else None
            ),
            "per_joint": per_joint,
            "terminal_joint_errors_descending": terminal_joint_errors,
        },
        "action_saturation": {
            "row_event_count": sum(saturation_histogram.values()),
            "by_virtual_action_name": dict(
                sorted(saturation_histogram.items())
            ),
        },
        "named_bowl_motion": _motion_metrics(bowl_tracks),
        "robot_bowl_contacts": {
            "contact_row_count": contact_row_count,
            "contact_event_count": contact_event_count,
            "source_mesh_collision_event_count": len(source_mesh_contacts),
            "events": all_contacts,
            "terminal_events": terminal_contacts,
        },
        "link_origin_distance": {
            "minimum_observed_pair": minimum_link_origin_pair,
            "collision_approach_last_three_ticks": _link_approach(
                rows,
                collision_link,
                collision_bowl,
            ),
            "interpretation_boundary": (
                "Recorded link origins are not collision-mesh clearance."
            ),
        },
        "hypothesis_status": {
            "scheduler_or_queue_drift": (
                "falsified_in_observed_replay"
                if clock_queue_exact
                else "not_falsified"
            ),
            "no_effective_robot_bowl_interaction": (
                "observed" if contact_event_count == 0 else "not_observed"
            ),
            "source_mesh_collision_family": (
                "observed" if source_mesh_contacts else "not_observed"
            ),
            "controller_tracking_error": (
                "measured_descriptively"
                if tracking_l2
                else "unavailable"
            ),
            "trajectory_vs_controller_causality": "unresolved",
            "causal_boundary": (
                "The log observes executed readback and commanded joints, but "
                "not collision geometry evaluated at the commanded target. "
                "Tracking error alone cannot identify whether the target path, "
                "controller dynamics, or both caused contact."
            ),
        },
    }


def _load_receipt(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} is not a JSON object")
    return value


def analyze_seed(
    batch_root: Path,
    seed: int,
    official_batch_root: Path | None = None,
) -> dict[str, Any]:
    seed_root = batch_root / f"seed{seed}"
    diagnostics_path = seed_root / "dynamic_diagnostics.jsonl"
    receipt_path = seed_root / "receipt.json"
    receipt = _load_receipt(receipt_path)

    official_receipt: dict[str, Any] = {}
    official_receipt_path: Path | None = None
    if official_batch_root is not None:
        official_receipt_path = (
            official_batch_root / f"seed{seed}" / "receipt.json"
        )
        official_receipt = _load_receipt(official_receipt_path)

    result = analyze_rows(
        read_jsonl(diagnostics_path),
        terminal_reason=str(receipt.get("terminal_reason")),
        terminal_policy_step=receipt.get("terminal_policy_step"),
        official_terminal_reason=official_receipt.get("terminal_reason"),
        official_terminal_policy_step=official_receipt.get(
            "terminal_policy_step"
        ),
    )
    result.update(
        {
            "seed": seed,
            "diagnostic_source_path": str(diagnostics_path),
            "diagnostic_source_sha256": hashlib.sha256(
                diagnostics_path.read_bytes()
            ).hexdigest(),
            "receipt_source_sha256": hashlib.sha256(
                receipt_path.read_bytes()
            ).hexdigest(),
            "official_receipt_source_path": (
                str(official_receipt_path)
                if official_receipt_path is not None
                else None
            ),
            "official_receipt_source_sha256": (
                hashlib.sha256(official_receipt_path.read_bytes()).hexdigest()
                if official_receipt_path is not None
                else None
            ),
        }
    )
    return result


def _maximum_bowl_metric(
    analysis: dict[str, Any],
    field: str,
) -> float:
    bowls = analysis["named_bowl_motion"].values()
    return max((float(item[field]) for item in bowls), default=0.0)


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
        "all_clock_and_queue_exact": all(
            analysis["clock_and_queue_audit"]["exact"]
            for analysis in analyses
        ),
        "all_tracking_available": all(
            analysis["tracking"]["sample_count"] == analysis["record_count"]
            for analysis in analyses
        ),
        "causal_conclusion": (
            "Clock and queue drift are excluded in these replays. Seed 101 "
            "records no effective robot-bowl interaction; collision seeds "
            "record the frozen source-mesh collision family. A commanded-"
            "target collision counterfactual is still required before "
            "selecting controller dynamics versus policy trajectory as the "
            "single correction variable."
        ),
        "analyses": list(analyses),
    }
    json_path = output_dir / "dynamic_attribution.json"
    json_path.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    csv_path = output_dir / "per_seed_dynamic_attribution.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fields = (
            "seed",
            "terminal_reason",
            "terminal_policy_step",
            "official_terminal_policy_step",
            "terminal_step_delta",
            "record_count",
            "clock_and_queue_exact",
            "maximum_tracking_l2_error_rad",
            "p95_tracking_l2_error_rad",
            "terminal_tracking_l2_error_rad",
            "saturation_row_event_count",
            "robot_bowl_contact_event_count",
            "source_mesh_collision_event_count",
            "maximum_named_bowl_displacement_m",
            "maximum_named_bowl_positive_z_m",
            "diagnostic_source_sha256",
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for analysis in analyses:
            terminal = analysis["terminal"]
            tracking = analysis["tracking"]
            contacts = analysis["robot_bowl_contacts"]
            writer.writerow(
                {
                    "seed": analysis["seed"],
                    "terminal_reason": terminal["reason"],
                    "terminal_policy_step": terminal["policy_step"],
                    "official_terminal_policy_step": terminal[
                        "official_reference_policy_step"
                    ],
                    "terminal_step_delta": terminal[
                        "policy_step_delta_from_official"
                    ],
                    "record_count": analysis["record_count"],
                    "clock_and_queue_exact": analysis[
                        "clock_and_queue_audit"
                    ]["exact"],
                    "maximum_tracking_l2_error_rad": tracking[
                        "maximum_l2_error_rad"
                    ],
                    "p95_tracking_l2_error_rad": tracking[
                        "p95_l2_error_rad"
                    ],
                    "terminal_tracking_l2_error_rad": tracking[
                        "terminal_l2_error_rad"
                    ],
                    "saturation_row_event_count": analysis[
                        "action_saturation"
                    ]["row_event_count"],
                    "robot_bowl_contact_event_count": contacts[
                        "contact_event_count"
                    ],
                    "source_mesh_collision_event_count": contacts[
                        "source_mesh_collision_event_count"
                    ],
                    "maximum_named_bowl_displacement_m": (
                        _maximum_bowl_metric(
                            analysis,
                            "maximum_displacement_from_initial_m",
                        )
                    ),
                    "maximum_named_bowl_positive_z_m": (
                        _maximum_bowl_metric(
                            analysis,
                            "maximum_positive_z_from_initial_m",
                        )
                    ),
                    "diagnostic_source_sha256": analysis[
                        "diagnostic_source_sha256"
                    ],
                }
            )

    markdown_path = output_dir / "dynamic_attribution.md"
    lines = [
        "# G3 R1/R2 Dynamic Attribution",
        "",
        "| seed | terminal | records | clock/queue | max tracking L2 "
        "(rad) | contacts | max bowl motion (m) |",
        "|---:|---|---:|---|---:|---:|---:|",
    ]
    for analysis in analyses:
        lines.append(
            "| {seed} | {reason}@{step} | {records} | {clock} | "
            "{tracking:.9f} | {contacts} | {motion:.9f} |".format(
                seed=analysis["seed"],
                reason=analysis["terminal"]["reason"],
                step=analysis["terminal"]["policy_step"],
                records=analysis["record_count"],
                clock=(
                    "exact"
                    if analysis["clock_and_queue_audit"]["exact"]
                    else "mismatch"
                ),
                tracking=analysis["tracking"]["maximum_l2_error_rad"],
                contacts=analysis["robot_bowl_contacts"][
                    "contact_event_count"
                ],
                motion=_maximum_bowl_metric(
                    analysis,
                    "maximum_displacement_from_initial_m",
                ),
            )
        )
    lines.extend(
        [
            "",
            "## Joint conclusion",
            "",
            aggregate["causal_conclusion"],
            "",
            "The collision replay is CUDA development evidence only. It is "
            "not official AMD/ROCm G3 evidence and does not establish "
            "robustness, generalization, or real-robot safety.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    manifested = (json_path, csv_path, markdown_path)
    manifest_path = output_dir / "analysis_files.SHA256SUMS"
    manifest_path.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in manifested
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--official-batch-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    arguments = parser.parse_args()

    analyses = [
        analyze_seed(
            arguments.batch_root,
            seed,
            arguments.official_batch_root,
        )
        for seed in arguments.seeds
    ]
    write_outputs(arguments.output_dir, analyses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
