#!/usr/bin/env python3
"""Capture one frozen v6 exact record-time VIO/IMU trace and stop at step 300."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
for import_root in (SCRIPT_DIR, PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import flightguard.exact_native_observer_capture as capture_module
from flightguard.exact_native_observer_capture import (
    TRANSITION_COUNT,
    ExactNativeObserverCaptureRecorder,
    FrozenSensorTransformMetadata,
)
from scripts.evaluate_causal_imu_repair_batch_amd import (
    OBSERVER_CAPTURE_STOP_SCHEMA_VERSION,
    _strict_bound_file,
    load_v6_observer_capture_execution_adapter,
    run_pass,
)

DRIVER_SOURCE_ROLE = "capture_driver"
RECORDER_SOURCE_ROLE = "capture_module"
CAPTURE_PROTOCOL_SHA256_ENV = "FLIGHTGUARD_CAPTURE_PROTOCOL_SHA256"


class ObserverCaptureDriverError(RuntimeError):
    """Raised when Stage-A capture execution differs from its frozen contract."""


def _require_lowercase_sha256(value: Any, *, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ObserverCaptureDriverError(
            f"{name} must be exact lowercase 64-hex SHA256"
        )
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--checkpoint", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _verify_driver_source_bindings(stage_protocol: dict[str, Any]) -> None:
    sources = stage_protocol.get("implementation_bindings", {}).get("sources")
    if not isinstance(sources, dict):
        raise ObserverCaptureDriverError(
            "Stage-A implementation source bindings are missing"
        )
    try:
        _strict_bound_file(
            sources.get(DRIVER_SOURCE_ROLE),
            name="v6 capture driver source",
            expected_path=Path(__file__),
        )
        _strict_bound_file(
            sources.get(RECORDER_SOURCE_ROLE),
            name="v6 capture recorder source",
            expected_path=Path(capture_module.__file__),
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        raise ObserverCaptureDriverError(
            "Stage-A driver/recorder source binding mismatch"
        ) from error


def run_capture(
    *,
    protocol_path: Path,
    protocol_sha256: str,
    checkpoint_seed: int,
    output_path: Path,
) -> dict[str, Any]:
    protocol_sha256 = _require_lowercase_sha256(
        protocol_sha256,
        name="protocol_sha256",
    )
    if type(checkpoint_seed) is not int:
        raise TypeError("checkpoint_seed must be exact int")
    adapter = load_v6_observer_capture_execution_adapter(
        protocol_path=protocol_path,
        protocol_sha256=protocol_sha256,
        checkpoint_seed=checkpoint_seed,
        capture_output_path=output_path,
    )
    if adapter.get("stage_protocol_sha256") != protocol_sha256:
        raise ObserverCaptureDriverError(
            "Stage-A adapter protocol SHA256 binding mismatch"
        )
    if adapter["capture_output"].suffix != ".fgcap":
        raise ObserverCaptureDriverError(
            "registered capture output must use the .fgcap suffix"
        )
    _verify_driver_source_bindings(adapter["stage_protocol"])
    transform = FrozenSensorTransformMetadata(**adapter["frozen_transform"])
    recorder = ExactNativeObserverCaptureRecorder(
        dt_seconds=adapter["dt_seconds"],
        frozen_seeds=adapter["frozen_seeds"],
        frozen_transform=transform,
    )
    stop = run_pass(
        protocol_path=protocol_path,
        capture_protocol_sha256=protocol_sha256,
        arm_name=adapter["arm_name"],
        checkpoint_seed=checkpoint_seed,
        lane_role=adapter["lane_role"],
        output_path=adapter["dummy_pass_output"],
        observer_capture_hook=recorder,
        stop_after_observer_capture=True,
    )
    expected_stop = {
        "schema_version": OBSERVER_CAPTURE_STOP_SCHEMA_VERSION,
        "status": "CAPTURE_COMPLETE",
        "simulation_only": True,
        "contains_observer_metrics": False,
        "identity": {
            "arm": adapter["arm_name"],
            "checkpoint_seed": checkpoint_seed,
            "lane_role": adapter["lane_role"],
        },
        "captured_transition_count": TRANSITION_COUNT,
        "native_sensor_read_count": TRANSITION_COUNT,
        "sensor_bank_steps_consumed": TRANSITION_COUNT,
        "dropout_step_executed": False,
        "dropout_action_dispatched": False,
        "scheduled_fault_activated": False,
        "legacy_pass_output_written": False,
    }
    if stop != expected_stop or "metrics" in stop:
        raise ObserverCaptureDriverError(
            "legacy evaluator did not return the exact capture-stop sentinel"
        )
    if (
        recorder.complete is not True
        or recorder.transition_count != TRANSITION_COUNT
    ):
        raise ObserverCaptureDriverError(
            "capture recorder is incomplete at the evaluator stop boundary"
        )
    capture = recorder.finalize()
    digest = capture.write_new(adapter["capture_output"])
    return {
        "event": "flightguard_v6_observer_capture_complete",
        "status": "CAPTURE_COMPLETE",
        "simulation_only": True,
        "development_only": True,
        "contains_observer_metrics": False,
        "checkpoint_seed": checkpoint_seed,
        "transition_count": TRANSITION_COUNT,
        "output": str(adapter["capture_output"]),
        "sha256": digest,
        "stage_protocol_sha256": protocol_sha256,
    }


def main() -> None:
    args = parse_args()
    protocol_sha256 = _require_lowercase_sha256(
        os.environ.get(CAPTURE_PROTOCOL_SHA256_ENV),
        name=CAPTURE_PROTOCOL_SHA256_ENV,
    )
    result = run_capture(
        protocol_path=args.protocol,
        protocol_sha256=protocol_sha256,
        checkpoint_seed=args.checkpoint,
        output_path=args.output,
    )
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
