from __future__ import annotations

from collections import defaultdict
import math
import statistics
from typing import Any, Iterable, Mapping, Sequence

from .grasp_scoring import canonical_payload_sha256


PROBE_FEATURE_SCHEMA_VERSION = 1
PROBE_FEATURE_NAMES = (
    "probe_completed",
    "probe_safety_aborted",
    "contact_acquired",
    "terminal_grasp_contact",
    "terminal_parcel_lifted",
    "probe_frame_count",
    "verify_frame_count",
    "lift_frame_count",
    "contact_acquisition_frames",
    "approach_peak_force_n",
    "verify_mean_force_n",
    "verify_force_std_n",
    "verify_peak_force_n",
    "lift_mean_force_n",
    "lift_force_std_n",
    "lift_peak_force_n",
    "terminal_force_n",
    "probe_peak_force_n",
    "parcel_lift_delta_m",
    "ee_lift_delta_m",
    "relative_drift_x_m",
    "relative_drift_y_m",
    "relative_drift_z_m",
    "relative_drift_norm_m",
    "max_relative_step_m",
    "max_downward_relative_step_m",
    "loaded_contact_fraction",
)
PROBE_POLICIES = (
    "veto-static",
    "force-first",
    "stability-first",
    "support-first",
)
_BOUNDARY_STAGES = frozenset({"place", "release", "complete", "abort"})


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _finite_vector(value: Any, length: int, name: str) -> tuple[float, ...]:
    result = tuple(_finite_float(item, name) for item in value)
    if len(result) != length:
        raise ValueError(f"{name} must contain {length} values")
    return result


def _force_statistics(rows: Sequence[Mapping[str, Any]]) -> tuple[float, float, float]:
    if not rows:
        return 0.0, 0.0, 0.0
    values = [_finite_float(row["contact_force_n"], "contact_force_n") for row in rows]
    return (
        float(statistics.fmean(values)),
        float(statistics.pstdev(values)),
        max(values),
    )


def _validated_trace(rollout: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    report = rollout.get("report")
    if not isinstance(report, Mapping):
        raise ValueError("probe rollout requires a report")
    raw_trace = report.get("trace")
    if not isinstance(raw_trace, Sequence) or isinstance(raw_trace, (str, bytes)):
        raise ValueError("probe rollout requires a trace sequence")
    trace = tuple(row for row in raw_trace if isinstance(row, Mapping))
    if len(trace) != len(raw_trace) or not trace:
        raise ValueError("probe trace rows must be non-empty mappings")
    previous_frame = -1
    for row in trace:
        frame = int(row["frame"])
        if frame <= previous_frame:
            raise ValueError("probe trace frames must be strictly increasing")
        previous_frame = frame
        _finite_float(row["contact_force_n"], "contact_force_n")
        _finite_vector(row["ee_position_m"], 3, "ee_position_m")
        _finite_vector(row["parcel_position_m"], 3, "parcel_position_m")
        _finite_vector(
            row["ee_parcel_relative_position_m"],
            3,
            "ee_parcel_relative_position_m",
        )
        if not str(row.get("stage", "")):
            raise ValueError("probe trace row requires a stage")
    return trace


def _probe_prefix(
    trace: Sequence[Mapping[str, Any]],
    *,
    allow_incomplete: bool = False,
) -> tuple[Mapping[str, Any], ...]:
    saw_lift = False
    for index, row in enumerate(trace):
        stage = str(row["stage"])
        saw_lift = saw_lift or stage == "lift"
        if stage in _BOUNDARY_STAGES:
            if stage == "place" and not saw_lift:
                raise ValueError("place boundary appeared before lift")
            return tuple(trace[: index + 1])
    if allow_incomplete:
        return tuple(trace)
    raise ValueError("probe trace has no pre-place boundary observation")


def extract_controller_faithful_probe(
    payload: Mapping[str, Any],
    rollout: Mapping[str, Any],
    *,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    """Extract only state observed before the first transport/place action.

    The boundary row is included because its state is observed before the
    boundary command is executed. No row after that boundary can influence the
    feature vector.
    """
    contract = payload.get("contract")
    if not isinstance(contract, Mapping):
        raise ValueError("probe source requires a contract")
    if not bool(contract.get("controller_faithful")):
        raise ValueError("probe source must be controller faithful")
    if not bool(contract.get("fresh_scene_per_rollout")):
        raise ValueError("probe source must use a fresh scene per rollout")
    force_limit_n = _finite_float(contract.get("force_abort_n"), "force_abort_n")
    if force_limit_n <= 0:
        raise ValueError("force_abort_n must be positive")

    trace = _validated_trace(rollout)
    prefix = _probe_prefix(trace, allow_incomplete=allow_incomplete)
    boundary = prefix[-1]
    active_start = next(
        (index for index, row in enumerate(prefix) if str(row["stage"]) == "grasp"),
        0,
    )
    active = prefix[active_start:]
    verify_rows = tuple(row for row in active if str(row["stage"]) == "verify")
    lift_rows = tuple(row for row in active if str(row["stage"]) == "lift")
    loaded_rows = (*verify_rows, *lift_rows, boundary)
    contact_rows = tuple(row for row in active if bool(row.get("grasp_contact")))

    verify_mean, verify_std, verify_peak = _force_statistics(verify_rows)
    lift_mean, lift_std, lift_peak = _force_statistics(lift_rows)
    all_forces = [
        _finite_float(row["contact_force_n"], "contact_force_n") for row in prefix
    ]
    approach_forces = [
        _finite_float(row["contact_force_n"], "contact_force_n")
        for row in prefix
        if str(row["stage"]) == "approach"
    ]

    start_ee = _finite_vector(active[0]["ee_position_m"], 3, "ee_position_m")
    terminal_ee = _finite_vector(boundary["ee_position_m"], 3, "ee_position_m")
    start_parcel = _finite_vector(
        active[0]["parcel_position_m"], 3, "parcel_position_m"
    )
    terminal_parcel = _finite_vector(
        boundary["parcel_position_m"], 3, "parcel_position_m"
    )
    reference_row = contact_rows[0] if contact_rows else active[0]
    reference_relative = _finite_vector(
        reference_row["ee_parcel_relative_position_m"],
        3,
        "ee_parcel_relative_position_m",
    )
    terminal_relative = _finite_vector(
        boundary["ee_parcel_relative_position_m"],
        3,
        "ee_parcel_relative_position_m",
    )
    relative_drift = tuple(
        terminal - reference
        for terminal, reference in zip(
            terminal_relative, reference_relative, strict=True
        )
    )
    relative_rows = [
        _finite_vector(
            row["ee_parcel_relative_position_m"],
            3,
            "ee_parcel_relative_position_m",
        )
        for row in active
    ]
    relative_steps = [
        tuple(current_value - previous_value for current_value, previous_value in zip(current, previous, strict=True))
        for previous, current in zip(relative_rows, relative_rows[1:])
    ]
    max_relative_step_m = max(
        (math.sqrt(sum(value * value for value in delta)) for delta in relative_steps),
        default=0.0,
    )
    max_downward_step_m = max((delta[2] for delta in relative_steps), default=0.0)
    first_contact_frame = (
        int(contact_rows[0]["frame"]) if contact_rows else int(boundary["frame"]) + 1
    )
    start_frame = int(active[0]["frame"])
    feature_map = {
        "probe_completed": float(str(boundary["stage"]) == "place"),
        "probe_safety_aborted": float(max(all_forces) > force_limit_n),
        "contact_acquired": float(bool(contact_rows)),
        "terminal_grasp_contact": float(bool(boundary.get("grasp_contact"))),
        "terminal_parcel_lifted": float(bool(boundary.get("parcel_lifted"))),
        "probe_frame_count": float(int(boundary["frame"]) - start_frame + 1),
        "verify_frame_count": float(len(verify_rows)),
        "lift_frame_count": float(len(lift_rows)),
        "contact_acquisition_frames": float(first_contact_frame - start_frame),
        "approach_peak_force_n": max(approach_forces, default=0.0),
        "verify_mean_force_n": verify_mean,
        "verify_force_std_n": verify_std,
        "verify_peak_force_n": verify_peak,
        "lift_mean_force_n": lift_mean,
        "lift_force_std_n": lift_std,
        "lift_peak_force_n": lift_peak,
        "terminal_force_n": _finite_float(
            boundary["contact_force_n"], "contact_force_n"
        ),
        "probe_peak_force_n": max(all_forces),
        "parcel_lift_delta_m": terminal_parcel[2] - start_parcel[2],
        "ee_lift_delta_m": terminal_ee[2] - start_ee[2],
        "relative_drift_x_m": relative_drift[0],
        "relative_drift_y_m": relative_drift[1],
        "relative_drift_z_m": relative_drift[2],
        "relative_drift_norm_m": math.sqrt(
            sum(value * value for value in relative_drift)
        ),
        "max_relative_step_m": max_relative_step_m,
        "max_downward_relative_step_m": max(0.0, max_downward_step_m),
        "loaded_contact_fraction": (
            sum(bool(row.get("grasp_contact")) for row in loaded_rows)
            / len(loaded_rows)
        ),
    }
    features = tuple(
        _finite_float(feature_map[name], f"probe feature {name}")
        for name in PROBE_FEATURE_NAMES
    )
    return {
        "candidate_id": str(rollout["candidate_id"]),
        "static_rank": int(rollout["static_rank"]),
        "boundary_stage": str(boundary["stage"]),
        "boundary_frame": int(boundary["frame"]),
        "source_trace_frames": len(trace),
        "consumed_trace_frames": len(prefix),
        "force_limit_n": force_limit_n,
        "feature_names": list(PROBE_FEATURE_NAMES),
        "features": list(features),
        "feature_map": feature_map,
    }


def controller_faithful_probe_rows(
    payload: Mapping[str, Any],
    *,
    source: str,
    source_sha256: str,
    split: str,
) -> list[dict[str, Any]]:
    if split != "train":
        raise ValueError("controller-faithful probe feasibility accepts train only")
    profile = str(payload["profile"])
    episode = int(payload["episode"])
    rows = []
    seen: set[tuple[str, int]] = set()
    for rollout in payload.get("rollouts", ()):  # type: ignore[union-attr]
        candidate_id = str(rollout["candidate_id"])
        repeat = int(rollout["repeat"])
        key = (candidate_id, repeat)
        if key in seen:
            raise ValueError(f"duplicate probe rollout: {candidate_id} repeat {repeat}")
        seen.add(key)
        if str(rollout["selected_candidate_id"]) != candidate_id:
            raise ValueError("probe requested/selected candidate mismatch")
        probe = extract_controller_faithful_probe(payload, rollout)
        rows.append(
            {
                "source": source,
                "source_sha256": source_sha256,
                "split": split,
                "group_id": f"{profile}:{episode}",
                "profile": profile,
                "episode": episode,
                "candidate_id": candidate_id,
                "repeat": repeat,
                "static_rank": int(rollout["static_rank"]),
                "probe": probe,
                "labels": {
                    "success": bool(rollout["success"]),
                    "safety_aborted": bool(rollout["safety_aborted"]),
                    "max_contact_force_n": _finite_float(
                        rollout["max_contact_force_n"], "max_contact_force_n"
                    ),
                    "duration_seconds": _finite_float(
                        rollout["duration_seconds"], "duration_seconds"
                    ),
                },
            }
        )
    if not rows:
        raise ValueError("probe source contains no rollouts")
    return rows


def build_controller_faithful_probe_dataset(
    sources: Iterable[tuple[str, Mapping[str, Any], str, str]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    artifacts = []
    seen_sources: set[str] = set()
    seen_rows: set[tuple[str, int, str, int]] = set()
    for source, payload, source_sha256, split in sources:
        if source in seen_sources:
            raise ValueError(f"duplicate probe source: {source}")
        seen_sources.add(source)
        artifacts.append({"path": source, "sha256": source_sha256})
        for row in controller_faithful_probe_rows(
            payload,
            source=source,
            source_sha256=source_sha256,
            split=split,
        ):
            key = (
                str(row["profile"]),
                int(row["episode"]),
                str(row["candidate_id"]),
                int(row["repeat"]),
            )
            if key in seen_rows:
                raise ValueError(f"duplicate probe dataset row: {key}")
            seen_rows.add(key)
            rows.append(row)
    if not rows:
        raise ValueError("probe dataset requires at least one source")
    result: dict[str, Any] = {
        "schema_version": 1,
        "probe_feature_schema_version": PROBE_FEATURE_SCHEMA_VERSION,
        "probe_feature_names": list(PROBE_FEATURE_NAMES),
        "source_artifacts": artifacts,
        "row_count": len(rows),
        "group_count": len({str(row["group_id"]) for row in rows}),
        "profiles": sorted({str(row["profile"]) for row in rows}),
        "splits": sorted({str(row["split"]) for row in rows}),
        "rows": rows,
    }
    result["dataset_sha256"] = canonical_payload_sha256(result)
    return result


def _eligible(row: Mapping[str, Any]) -> bool:
    probe = row["probe"]
    features = probe["feature_map"]
    return (
        float(features["probe_completed"]) == 1.0
        and float(features["probe_safety_aborted"]) == 0.0
        and float(features["contact_acquired"]) == 1.0
        and float(features["terminal_grasp_contact"]) == 1.0
        and float(features["terminal_parcel_lifted"]) == 1.0
    )


def _policy_key(row: Mapping[str, Any], policy: str) -> tuple[Any, ...]:
    features = row["probe"]["feature_map"]
    static_tail = (int(row["static_rank"]), str(row["candidate_id"]))
    if policy == "veto-static":
        return static_tail
    if policy == "force-first":
        return (
            float(features["probe_peak_force_n"]),
            float(features["max_downward_relative_step_m"]),
            float(features["relative_drift_norm_m"]),
            *static_tail,
        )
    if policy == "stability-first":
        return (
            float(features["max_downward_relative_step_m"]),
            float(features["max_relative_step_m"]),
            float(features["relative_drift_norm_m"]),
            float(features["probe_peak_force_n"]),
            -float(features["loaded_contact_fraction"]),
            *static_tail,
        )
    if policy == "support-first":
        return (
            -float(features["loaded_contact_fraction"]),
            -float(features["parcel_lift_delta_m"]),
            float(features["relative_drift_norm_m"]),
            float(features["probe_peak_force_n"]),
            *static_tail,
        )
    raise ValueError(f"unsupported controller-faithful probe policy: {policy}")


def select_controller_faithful_probe_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    policy: str,
) -> list[dict[str, Any]]:
    if policy not in PROBE_POLICIES:
        raise ValueError(f"unsupported controller-faithful probe policy: {policy}")
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["group_id"])].append(row)
    if not grouped:
        raise ValueError("probe policy requires at least one group")
    selections = []
    for group_id, candidates in sorted(grouped.items()):
        baseline = min(
            candidates,
            key=lambda row: (int(row["static_rank"]), str(row["candidate_id"])),
        )
        eligible = [row for row in candidates if _eligible(row)]
        selected = min(eligible, key=lambda row: _policy_key(row, policy)) if eligible else None
        labels = selected["labels"] if selected is not None else None
        probe_frames = sum(int(row["probe"]["consumed_trace_frames"]) for row in candidates)
        selections.append(
            {
                "group_id": group_id,
                "profile": str(baseline["profile"]),
                "policy": policy,
                "model_candidate_id": (
                    str(selected["candidate_id"]) if selected is not None else None
                ),
                "model_success": bool(labels["success"]) if labels else False,
                "model_safety_aborted": (
                    bool(labels["safety_aborted"]) if labels else False
                ),
                "model_force_n": (
                    float(labels["max_contact_force_n"]) if labels else None
                ),
                "model_duration_seconds": (
                    float(labels["duration_seconds"]) if labels else None
                ),
                "baseline_candidate_id": str(baseline["candidate_id"]),
                "baseline_success": bool(baseline["labels"]["success"]),
                "baseline_safety_aborted": bool(
                    baseline["labels"]["safety_aborted"]
                ),
                "baseline_force_n": float(
                    baseline["labels"]["max_contact_force_n"]
                ),
                "baseline_duration_seconds": float(
                    baseline["labels"]["duration_seconds"]
                ),
                "decision": "probe_selected" if selected is not None else "safe_abstain",
                "eligible_candidate_count": len(eligible),
                "probe_candidate_count": len(candidates),
                "probe_consumed_trace_frames": probe_frames,
                "selected_probe": selected["probe"] if selected is not None else None,
            }
        )
    return selections


def summarize_controller_faithful_probe(
    selections: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not selections:
        raise ValueError("probe summary requires at least one selection")

    def summarize(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        executed_forces = [
            float(row["model_force_n"])
            for row in items
            if row["model_force_n"] is not None
        ]
        return {
            "group_count": len(items),
            "model_successes": sum(bool(row["model_success"]) for row in items),
            "model_safety_aborts": sum(
                bool(row["model_safety_aborted"]) for row in items
            ),
            "baseline_successes": sum(
                bool(row["baseline_success"]) for row in items
            ),
            "baseline_safety_aborts": sum(
                bool(row["baseline_safety_aborted"]) for row in items
            ),
            "success_gains": sum(
                bool(row["model_success"]) and not bool(row["baseline_success"])
                for row in items
            ),
            "success_losses": sum(
                not bool(row["model_success"]) and bool(row["baseline_success"])
                for row in items
            ),
            "safety_abort_reductions": sum(
                not bool(row["model_safety_aborted"])
                and bool(row["baseline_safety_aborted"])
                for row in items
            ),
            "safety_abort_regressions": sum(
                bool(row["model_safety_aborted"])
                and not bool(row["baseline_safety_aborted"])
                for row in items
            ),
            "safe_abstentions": sum(str(row["decision"]) == "safe_abstain" for row in items),
            "changed_from_baseline": sum(
                row["model_candidate_id"] != row["baseline_candidate_id"]
                for row in items
            ),
            "executed_group_count": len(executed_forces),
            "model_mean_selected_force_n": (
                float(statistics.fmean(executed_forces)) if executed_forces else None
            ),
            "baseline_mean_force_n": float(
                statistics.fmean(float(row["baseline_force_n"]) for row in items)
            ),
            "probe_consumed_trace_frames": sum(
                int(row["probe_consumed_trace_frames"]) for row in items
            ),
        }

    result = summarize(selections)
    profiles = sorted({str(row["profile"]) for row in selections})
    result["per_profile"] = {
        profile: summarize(
            [row for row in selections if str(row["profile"]) == profile]
        )
        for profile in profiles
    }
    result["selections"] = [dict(row) for row in selections]
    return result


def audit_controller_faithful_probe_candidate(
    name: str,
    summary: Mapping[str, Any],
    fold_summaries: Sequence[Mapping[str, Any]],
    *,
    expected_group_count: int,
    expected_profile_group_count: int,
    max_selection_p95_ms: float,
    selection_p95_ms: float,
) -> dict[str, Any]:
    reasons = []
    if int(summary["group_count"]) != expected_group_count:
        reasons.append("incomplete_train_groups")
    profile_safety_regressions = []
    profile_success_regressions = []
    for profile, row in sorted(summary["per_profile"].items()):
        if int(row["group_count"]) != expected_profile_group_count:
            reasons.append("incomplete_profile_groups")
        if int(row["model_safety_aborts"]) > int(row["baseline_safety_aborts"]):
            profile_safety_regressions.append(profile)
        if int(row["model_successes"]) < int(row["baseline_successes"]):
            profile_success_regressions.append(profile)
    if profile_safety_regressions:
        reasons.append("per_profile_safety_regression")
    if profile_success_regressions:
        reasons.append("per_profile_success_regression")
    fold_safety_regressions = [
        index
        for index, row in enumerate(fold_summaries)
        if int(row["model_safety_aborts"]) > int(row["baseline_safety_aborts"])
    ]
    fold_success_regressions = [
        index
        for index, row in enumerate(fold_summaries)
        if int(row["model_successes"]) < int(row["baseline_successes"])
    ]
    if fold_safety_regressions:
        reasons.append("per_fold_safety_regression")
    if fold_success_regressions:
        reasons.append("per_fold_success_regression")
    if int(summary["model_successes"]) < int(summary["baseline_successes"]):
        reasons.append("aggregate_success_regression")
    if not (
        int(summary["model_successes"]) > int(summary["baseline_successes"])
        or int(summary["model_safety_aborts"])
        < int(summary["baseline_safety_aborts"])
    ):
        reasons.append("no_task_or_safety_improvement")
    if selection_p95_ms >= max_selection_p95_ms:
        reasons.append("selection_latency_gate_failed")
    return {
        "name": name,
        "passes": not reasons,
        "reasons": reasons,
        "profile_safety_regressions": profile_safety_regressions,
        "profile_success_regressions": profile_success_regressions,
        "fold_safety_regressions": fold_safety_regressions,
        "fold_success_regressions": fold_success_regressions,
        "selection_p95_ms": selection_p95_ms,
        "summary": dict(summary),
    }


def select_controller_faithful_probe_candidate(
    audits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not audits:
        raise ValueError("provide at least one probe candidate audit")
    eligible = [row for row in audits if bool(row["passes"])]
    if not eligible:
        return {
            "status": "no_probe_candidate",
            "selected": None,
            "new_physics_authorized": False,
        }
    selected = min(
        eligible,
        key=lambda row: (
            int(row["summary"]["model_safety_aborts"]),
            -int(row["summary"]["model_successes"]),
            int(row["summary"]["safe_abstentions"]),
            (
                float(row["summary"]["model_mean_selected_force_n"])
                if row["summary"]["model_mean_selected_force_n"] is not None
                else float("inf")
            ),
            float(row["selection_p95_ms"]),
            str(row["name"]),
        ),
    )
    return {
        "status": "probe_candidate_found",
        "selected": str(selected["name"]),
        "new_physics_authorized": False,
    }
