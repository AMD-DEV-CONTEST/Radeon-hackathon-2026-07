#!/usr/bin/env python3
"""Validate a complete full-fidelity BiGym evaluation recording."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from episode_recorder import DEFAULT_CAMERA_NAMES, inspect_episode


TERMINAL_STATES = {"complete", "failed"}
REQUIRED_TRANSITION_FIELDS = {
    "state16",
    "state16_before",
    "state16_after",
    "state_after_error",
    "sim_time_s_before",
    "sim_time_s_after",
    "camera_frames_phase",
    "observation_before_record_step_index",
    "observation_after_record_step_index",
    "action16_model",
    "action_env",
    "action_clipped",
    "clip_mask",
    "reward",
    "success",
    "terminated",
    "truncated",
    "info",
    "request",
    "action_index_in_chunk",
}


def latency_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "maximum": None}
    ordered = sorted(values)

    def percentile(percent: float) -> float:
        rank = (len(ordered) - 1) * percent / 100.0
        lower = math.floor(rank)
        upper = math.ceil(rank)
        if lower == upper:
            return float(ordered[lower])
        fraction = rank - lower
        return float(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction)

    return {
        "mean": float(sum(ordered) / len(ordered)),
        "p50": percentile(50),
        "p95": percentile(95),
        "maximum": float(ordered[-1]),
    }


def equal_numbers(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def equal_latency_summary(actual: Any, expected: dict[str, float | None]) -> bool:
    return isinstance(actual, dict) and all(
        equal_numbers(actual.get(key), value) for key, value in expected.items()
    )


def finite_numbers(value: Any) -> bool:
    if isinstance(value, str):
        return value not in {"NaN", "Infinity", "-Infinity"}
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(finite_numbers(item) for item in value)
    if isinstance(value, dict):
        return all(finite_numbers(item) for item in value.values())
    return False


def read_steps(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL line {line_number}: {error}") from error
            if not isinstance(record, dict):
                raise ValueError(f"JSONL line {line_number} is not an object")
            records.append(record)
    return records


def validate_episode(task_dir: Path, episode_index: int) -> dict[str, Any]:
    inspection = inspect_episode(task_dir, episode_index)
    errors = list(inspection.get("errors", []))
    state = inspection["state"]
    if state not in TERMINAL_STATES:
        errors.append(f"episode is not terminal: {state}")
        return {
            "episode_index": episode_index,
            "passed": False,
            "state": state,
            "errors": errors,
        }

    manifest = inspection["manifest"]
    episode_dir = Path(inspection["episode_dir"])
    try:
        records = read_steps(episode_dir / manifest["steps"]["path"])
    except (KeyError, OSError, ValueError) as error:
        records = []
        errors.append(f"step log validation failed: {type(error).__name__}: {error}")

    if len(records) != int(manifest["steps"].get("count", -1)):
        errors.append("manifest and JSONL record counts differ")
    if records and records[0].get("record_type") != "reset":
        errors.append("first record must be the reset observation")
    if not all(finite_numbers(record) for record in records):
        errors.append("step records contain non-finite or unsupported values")
    if tuple(manifest.get("camera_names", ())) != DEFAULT_CAMERA_NAMES:
        errors.append("manifest camera_names do not match the three-camera contract")

    transitions = [record for record in records if record.get("record_type") == "transition"]
    observation_records = [
        record
        for record in records
        if record.get("record_type") in {"reset", "transition"}
    ]
    if any(not record.get("camera_frames_recorded") for record in observation_records):
        errors.append("one or more reset/transition records lack synchronized camera frames")
    previous_observation_step: int | None = 0 if records and records[0].get("record_type") == "reset" else None
    linked_request_ids: set[str] = set()
    for record in transitions:
        missing = sorted(REQUIRED_TRANSITION_FIELDS - set(record))
        if missing:
            errors.append(
                f"transition {record.get('step_index')} is missing fields: {missing}"
            )
        if len(record.get("state16_before", [])) != 16:
            errors.append(f"transition {record.get('step_index')} state16_before is not 16D")
        if record.get("state16") != record.get("state16_before"):
            errors.append(f"transition {record.get('step_index')} state16 alias differs")
        state_after = record.get("state16_after")
        if state_after is None:
            if not record.get("state_after_error"):
                errors.append(
                    f"transition {record.get('step_index')} lacks state16_after and error"
                )
        elif len(state_after) != 16:
            errors.append(f"transition {record.get('step_index')} state16_after is not 16D")
        if len(record.get("action16_model", [])) != 16:
            errors.append(f"transition {record.get('step_index')} action16_model is not 16D")
        action_env = record.get("action_env", [])
        action_clipped = record.get("action_clipped", [])
        clip_mask = record.get("clip_mask", [])
        if not action_env or len(action_env) != len(action_clipped) or len(action_env) != len(clip_mask):
            errors.append(f"transition {record.get('step_index')} env action arrays differ")
        if not all(isinstance(value, bool) for value in clip_mask):
            errors.append(f"transition {record.get('step_index')} clip_mask is not boolean")
        if not isinstance(record.get("success"), bool) or not isinstance(
            record.get("terminated"), bool
        ) or not isinstance(record.get("truncated"), bool):
            errors.append(f"transition {record.get('step_index')} terminal flags are not boolean")
        action_index = record.get("action_index_in_chunk")
        if not isinstance(action_index, int) or not 0 <= action_index < 10:
            errors.append(f"transition {record.get('step_index')} action index is outside 0..9")
        if record.get("camera_frames_phase") != "observation_after_action":
            errors.append(f"transition {record.get('step_index')} camera phase is ambiguous")
        if record.get("observation_before_record_step_index") != previous_observation_step:
            errors.append(f"transition {record.get('step_index')} previous observation link differs")
        if record.get("observation_after_record_step_index") != record.get("step_index"):
            errors.append(f"transition {record.get('step_index')} next observation link differs")
        previous_observation_step = record.get("step_index")
        request_record = record.get("request")
        if not isinstance(request_record, dict) or not request_record.get("request_id"):
            errors.append(f"transition {record.get('step_index')} lacks request linkage")
        else:
            linked_request_ids.add(str(request_record["request_id"]))
            for timing_field in ("image_encode_ms", "http_round_trip_ms"):
                if not isinstance(request_record.get(timing_field), (int, float)):
                    errors.append(
                        f"transition {record.get('step_index')} lacks {timing_field}"
                    )
            server_timing = request_record.get("server_timing_ms")
            required_server_timings = (
                "image_decode",
                "policy_infer",
                "total_before_serialize",
                "serialization_first_pass",
                "server_total_before_final_serialize",
            )
            if not isinstance(server_timing, dict) or any(
                not isinstance(server_timing.get(key), (int, float))
                for key in required_server_timings
            ):
                errors.append(
                    f"transition {record.get('step_index')} lacks server timing evidence"
                )

    result = manifest.get("result") or {}
    if len(transitions) != int(result.get("steps_executed", len(transitions))):
        errors.append("transition count does not match steps_executed")
    camera_frame_steps = sum(bool(record.get("camera_frames_recorded")) for record in records)
    if camera_frame_steps != int(manifest["steps"].get("camera_frame_steps", -1)):
        errors.append("camera frame row count does not match manifest")

    videos: dict[str, Any] = {}
    for camera in manifest.get("camera_names", []):
        metadata = manifest.get("videos", {}).get(camera, {}).get("final")
        videos[camera] = metadata
        if camera_frame_steps == 0:
            if metadata is not None:
                errors.append(f"{camera} video exists even though no frames were recorded")
            continue
        if not isinstance(metadata, dict):
            errors.append(f"{camera} final video metadata is missing")
            continue
        if not metadata.get("passed"):
            errors.append(f"{camera} video validation did not pass")
        if int(metadata.get("decoded_frames", -1)) != camera_frame_steps:
            errors.append(f"{camera} decoded frame count does not match recording")
        if len(str(metadata.get("sha256", ""))) != 64:
            errors.append(f"{camera} video SHA-256 is missing")

    request_records = result.get("request_records", [])
    request_ids = [
        str(record.get("request_id"))
        for record in request_records
        if isinstance(record, dict) and record.get("request_id")
    ]
    if len(request_ids) != len(set(request_ids)):
        errors.append("episode request IDs are not unique")
    if int(result.get("request_attempts", -1)) != len(request_records):
        errors.append("request_attempts does not match request_records")
    successful_request_ids = {
        str(record.get("request_id"))
        for record in request_records
        if isinstance(record, dict)
        and record.get("request_id")
        and record.get("server_timing_ms") is not None
    }
    if int(result.get("request_count", -1)) != len(successful_request_ids):
        errors.append("request_count does not match successful request records")
    if not linked_request_ids.issubset(successful_request_ids):
        errors.append("one or more transition requests are missing from episode request records")

    return {
        "episode_index": episode_index,
        "seed": manifest.get("seed"),
        "state": state,
        "task_success": bool(result.get("success")),
        "recording_status": manifest.get("status"),
        "recording_manifest": str((episode_dir / "manifest.json").relative_to(task_dir)),
        "fps": manifest.get("fps"),
        "manifest_result": result,
        "step_records": len(records),
        "transitions": len(transitions),
        "camera_frame_steps": camera_frame_steps,
        "videos": videos,
        "passed": not errors,
        "errors": errors,
    }


def validate_task_dir(task_dir: Path, expected_episodes: int) -> dict[str, Any]:
    if expected_episodes <= 0:
        raise ValueError("expected_episodes must be positive")
    task_dir = task_dir.resolve()
    results_path = task_dir / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    episode_reports = [
        validate_episode(task_dir, episode_index)
        for episode_index in range(expected_episodes)
    ]
    temporary_files = [
        str(path.relative_to(task_dir))
        for path in task_dir.rglob("*")
        if path.is_file()
        and (".tmp" in path.name or path.name.endswith(".part"))
        if "incomplete-attempts" not in path.parts
    ]
    top_level_errors: list[str] = []
    if results.get("schema_version") != 2:
        top_level_errors.append("results schema_version must be 2")
    if results.get("status") != "benchmark_complete":
        top_level_errors.append("results status is not benchmark_complete")
    if results.get("n_episodes") != expected_episodes:
        top_level_errors.append("results n_episodes does not match expectation")
    recording = results.get("recording", {})
    if recording.get("mode") != "full":
        top_level_errors.append("results do not declare full recording mode")
    if recording.get("episodes_terminal") != expected_episodes:
        top_level_errors.append("terminal episode count does not match expectation")
    if recording.get("episodes_interrupted") != 0:
        top_level_errors.append("one or more episode recordings are interrupted")
    if temporary_files:
        top_level_errors.append("active recording tree contains temporary files")

    result_episodes = results.get("episodes", [])
    if not isinstance(result_episodes, list):
        result_episodes = []
        top_level_errors.append("results episodes is not a list")
    entries_by_index: dict[int, dict[str, Any]] = {}
    for entry in result_episodes:
        if not isinstance(entry, dict) or not isinstance(entry.get("episode_index"), int):
            top_level_errors.append("results contains an invalid episode entry")
            continue
        index = int(entry["episode_index"])
        if index in entries_by_index:
            top_level_errors.append(f"results contains duplicate episode index {index}")
        entries_by_index[index] = entry
    expected_indices = set(range(expected_episodes))
    if set(entries_by_index) != expected_indices:
        top_level_errors.append("results episode indices are not exactly 0..N-1")

    seed0 = results.get("seed0")
    if not isinstance(seed0, int):
        top_level_errors.append("results seed0 is missing or invalid")
    configuration_sha256 = results.get("configuration_sha256")
    if not isinstance(configuration_sha256, str) or len(configuration_sha256) != 64:
        top_level_errors.append("results configuration_sha256 is missing")
    expected_fps = results.get("configuration", {}).get("fps")
    if not isinstance(expected_fps, (int, float)) or expected_fps <= 0:
        top_level_errors.append("results configuration FPS is missing")
    camera_contract = results.get("observation_contract", {}).get("cameras", {})
    if set(camera_contract) != set(DEFAULT_CAMERA_NAMES):
        top_level_errors.append("results observation camera contract is incomplete")

    joined_entries: list[dict[str, Any]] = []
    for report in episode_reports:
        index = report["episode_index"]
        entry = entries_by_index.get(index)
        if entry is None:
            continue
        joined_entries.append(entry)
        expected_seed = seed0 + index if isinstance(seed0, int) else None
        if entry.get("seed") != expected_seed or report.get("seed") != expected_seed:
            top_level_errors.append(f"episode {index} seed differs from seed0 contract")
        if not equal_numbers(report.get("fps"), expected_fps):
            top_level_errors.append(f"episode {index} FPS differs from run contract")
        for camera in DEFAULT_CAMERA_NAMES:
            expected_shape = camera_contract.get(camera)
            metadata = report.get("videos", {}).get(camera)
            if report.get("camera_frame_steps", 0) == 0:
                continue
            if (
                not isinstance(expected_shape, list)
                or len(expected_shape) != 3
                or expected_shape[0] != 3
                or not isinstance(metadata, dict)
                or metadata.get("height") != expected_shape[1]
                or metadata.get("width") != expected_shape[2]
            ):
                top_level_errors.append(
                    f"episode {index} {camera} video dimensions differ from observation contract"
                )
        manifest_result = report.get("manifest_result", {})
        for field in (
            "episode_index",
            "seed",
            "success",
            "steps_executed",
            "max_steps",
            "failure_reason",
            "failure_detail",
            "request_count",
            "request_attempts",
            "request_latency_ms",
            "request_attempt_latency_ms",
            "request_records",
            "provenance",
        ):
            if entry.get(field) != manifest_result.get(field):
                top_level_errors.append(
                    f"episode {index} top-level {field} differs from terminal manifest"
                )
        expected_recording_fields = {
            "recording_status": report.get("recording_status"),
            "recording_manifest": report.get("recording_manifest"),
            "step_records": report.get("step_records"),
            "camera_frame_steps": report.get("camera_frame_steps"),
            "videos": report.get("videos"),
        }
        for field, expected in expected_recording_fields.items():
            if entry.get(field) != expected:
                top_level_errors.append(
                    f"episode {index} top-level {field} differs from recording artifacts"
                )
        provenance = manifest_result.get("provenance", {})
        if not isinstance(provenance, dict):
            top_level_errors.append(f"episode {index} provenance is missing")
        else:
            if provenance.get("run_id") != results.get("run_id"):
                top_level_errors.append(f"episode {index} run_id provenance differs")
            if provenance.get("configuration_sha256") != configuration_sha256:
                top_level_errors.append(
                    f"episode {index} configuration provenance differs"
                )
            if provenance.get("task") != results.get("task"):
                top_level_errors.append(f"episode {index} task provenance differs")
            if provenance.get("policy_health") != results.get("policy_health"):
                top_level_errors.append(
                    f"episode {index} policy provenance differs"
                )
            if provenance.get("code_revisions") != results.get("code_revisions"):
                top_level_errors.append(f"episode {index} code provenance differs")

    successes = sum(bool(entry.get("success")) for entry in joined_entries)
    if results.get("successes") != successes:
        top_level_errors.append("results successes does not match episode manifests")
    expected_success_rate = successes / expected_episodes
    if not equal_numbers(results.get("success_rate"), expected_success_rate):
        top_level_errors.append("results success_rate does not match episode manifests")
    terminal_count = sum(
        entry.get("recording_status") in TERMINAL_STATES for entry in joined_entries
    )
    interrupted_count = sum(
        entry.get("recording_status") == "interrupted" for entry in joined_entries
    )
    if results.get("episodes_completed") != terminal_count:
        top_level_errors.append("results episodes_completed aggregate differs")
    expected_step_records = sum(int(report.get("step_records", 0)) for report in episode_reports)
    expected_camera_frames = sum(
        int(report.get("camera_frame_steps", 0)) for report in episode_reports
    )
    if recording.get("episodes_terminal") != terminal_count:
        top_level_errors.append("recording terminal aggregate differs")
    if recording.get("episodes_interrupted") != interrupted_count:
        top_level_errors.append("recording interrupted aggregate differs")
    if recording.get("step_records") != expected_step_records:
        top_level_errors.append("recording step_records aggregate differs")
    if recording.get("camera_frame_steps") != expected_camera_frames:
        top_level_errors.append("recording camera_frame_steps aggregate differs")

    successful_latencies = [
        float(value)
        for entry in joined_entries
        for value in entry.get("request_latency_ms", [])
        if value is not None
    ]
    attempt_latencies = [
        float(value)
        for entry in joined_entries
        for value in entry.get("request_attempt_latency_ms", [])
        if value is not None
    ]
    if results.get("policy_requests") != len(successful_latencies):
        top_level_errors.append("policy_requests aggregate differs")
    request_attempts = sum(
        int(entry.get("request_attempts", 0)) for entry in joined_entries
    )
    if results.get("policy_request_attempts") != request_attempts:
        top_level_errors.append("policy_request_attempts aggregate differs")
    if results.get("policy_attempts_with_http_latency") != len(attempt_latencies):
        top_level_errors.append("policy_attempts_with_http_latency aggregate differs")
    if not equal_latency_summary(
        results.get("policy_latency_ms"), latency_summary(successful_latencies)
    ):
        top_level_errors.append("policy_latency_ms aggregate differs")
    if not equal_latency_summary(
        results.get("policy_attempt_latency_ms"), latency_summary(attempt_latencies)
    ):
        top_level_errors.append("policy_attempt_latency_ms aggregate differs")

    passed_episodes = sum(report["passed"] for report in episode_reports)
    passed = not top_level_errors and passed_episodes == expected_episodes
    return {
        "schema_version": 1,
        "status": "recording_valid" if passed else "recording_invalid",
        "task_dir": str(task_dir.resolve()),
        "expected_episodes": expected_episodes,
        "episodes_passed": passed_episodes,
        "episodes_failed_validation": expected_episodes - passed_episodes,
        "task_successes": sum(report.get("task_success", False) for report in episode_reports),
        "step_records": sum(int(report.get("step_records", 0)) for report in episode_reports),
        "transitions": sum(int(report.get("transitions", 0)) for report in episode_reports),
        "camera_frame_steps": sum(
            int(report.get("camera_frame_steps", 0)) for report in episode_reports
        ),
        "temporary_files": temporary_files,
        "top_level_errors": top_level_errors,
        "episodes": episode_reports,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--expected-episodes", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate_task_dir(args.task_dir.resolve(), args.expected_episodes)
    atomic_write_json(args.output.resolve(), report)
    print(json.dumps({key: report[key] for key in (
        "status",
        "expected_episodes",
        "episodes_passed",
        "task_successes",
        "transitions",
        "camera_frame_steps",
    )}, indent=2))
    if report["status"] != "recording_valid":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
