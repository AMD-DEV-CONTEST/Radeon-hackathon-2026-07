#!/usr/bin/env python3
"""Run the deterministic ACT open-loop inference gate against a local dataset.

This is the thin CLI for
``src/mantis_rocm_bridge/act_openloop_inference.py``.  It validates that every
path argument is absolute, refuses to overwrite or reuse an output directory,
hands the frozen checkpoint / dataset / contracts to the core runtime, and
publishes the fail-closed artifact set (``started.json``, ``actions.jsonl``,
``receipt.json``, ``status``, ``SHA256SUMS``).

The receipt is written and ``status`` is recorded whether or not the gate
passes, so a failed run still preserves its evidence.  Network / GPU / LeRobot
work lives entirely inside :class:`LeRobotOpenLoopRuntime`, which imports those
packages lazily; this module imports only the Python standard library plus the
pure-Python core at import time.

Exit codes: ``0`` on a passing open-loop receipt, ``2`` on a failing receipt or
on any argument / output-directory violation.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mantis_rocm_bridge.act_openloop_inference import (
    LeRobotOpenLoopRuntime,
    OUTPUT_ARTIFACTS,
    run_open_loop_inference,
    sha256_file,
)
from mantis_rocm_bridge.contracts import load_json


ROOT = Path(__file__).resolve().parents[1]


def _now_utc_iso() -> str:
    """Return the current UTC timestamp in ISO-8601.  Tests monkeypatch this."""

    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_absolute_path(path: Path, *, arg: str, parser: argparse.ArgumentParser) -> Path:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        parser.error(f"{arg} must be an absolute path, got: {path}")
    return resolved


def _write_text(path: Path, content: str) -> None:
    # Exclusive no-overwrite: the output directory is already guaranteed fresh,
    # but every artifact is still created with xfail semantics so a collision
    # can never silently clobber evidence.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def _build_sha256sums(output_dir: Path) -> str:
    """Return a deterministic ``SHA256SUMS`` manifest over the output artifacts.

    Entries are sorted by filename so two runs with identical artifact contents
    produce an identical manifest (and therefore an identical manifest hash).
    """

    entries: list[str] = []
    for name in sorted(path.name for path in output_dir.iterdir() if path.is_file()):
        if name == "SHA256SUMS":
            continue
        digest = sha256_file(output_dir / name)
        entries.append(f"{digest}  {name}")
    return "\n".join(entries) + ("\n" if entries else "")


def publish_artifacts(
    *,
    output_dir: Path,
    started: dict[str, Any],
    actions: list[dict[str, Any]],
    receipt: dict[str, Any],
) -> None:
    """Write the fail-closed artifact set under an exclusive output directory."""

    _write_text(output_dir / "started.json", json.dumps(started, indent=2, sort_keys=True) + "\n")
    lines = [json.dumps(record, sort_keys=True) for record in actions]
    _write_text(output_dir / "actions.jsonl", ("\n".join(lines) + "\n") if lines else "")
    _write_text(output_dir / "receipt.json", json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    _write_text(output_dir / "status", "PASS\n" if receipt.get("open_loop_inference_pass") else "FAIL\n")
    _write_text(output_dir / "SHA256SUMS", _build_sha256sums(output_dir))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path, help="absolute path to the local LeRobot dataset root")
    parser.add_argument("--repo-id", required=True, help="LeRobot repo_id label for the dataset")
    parser.add_argument(
        "--pretrained-model",
        required=True,
        type=Path,
        help="absolute path to the frozen pretrained_model directory",
    )
    parser.add_argument(
        "--gate",
        type=Path,
        default=ROOT / "configs/act-openloop-inference-v1.json",
        help="absolute path to the open-loop inference gate config",
    )
    parser.add_argument(
        "--interface",
        type=Path,
        default=ROOT / "configs/mantis-lerobot-interface-v1.json",
        help="absolute path to the Mantis LeRobot interface contract",
    )
    parser.add_argument(
        "--port-config",
        type=Path,
        default=ROOT / "configs/mantis-port-config.json",
        help="absolute path to the Mantis port config",
    )
    parser.add_argument(
        "--fixed-plan",
        type=Path,
        default=ROOT / "configs/fixed-base-plan.json",
        help="absolute path to the fixed-base plan",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="fresh, exclusive output directory that must not yet exist",
    )
    args = parser.parse_args(argv)

    dataset_root = _require_absolute_path(args.dataset_root, arg="dataset_root", parser=parser)
    pretrained_model = _require_absolute_path(
        args.pretrained_model, arg="--pretrained-model", parser=parser
    )
    gate_path = _require_absolute_path(args.gate, arg="--gate", parser=parser)
    interface_path = _require_absolute_path(args.interface, arg="--interface", parser=parser)
    port_path = _require_absolute_path(args.port_config, arg="--port-config", parser=parser)
    fixed_plan_path = _require_absolute_path(args.fixed_plan, arg="--fixed-plan", parser=parser)
    output_dir = _require_absolute_path(args.output_dir, arg="--output-dir", parser=parser)

    if output_dir.exists():
        parser.error(
            f"refusing to reuse or overwrite output directory: {output_dir}"
        )
    if not dataset_root.is_dir():
        parser.error(f"dataset_root is not a directory: {dataset_root}")
    if not pretrained_model.is_dir():
        parser.error(f"--pretrained-model is not a directory: {pretrained_model}")

    gate = load_json(gate_path)
    port = load_json(port_path)
    fixed_plan = load_json(fixed_plan_path)
    interface = load_json(interface_path)

    gate_sha256 = sha256_file(gate_path)
    port_sha256 = sha256_file(port_path)
    interface_sha256 = sha256_file(interface_path)
    fixed_plan_sha256 = sha256_file(fixed_plan_path)

    started_at = _now_utc_iso()
    started = {
        "gate_id": gate.get("gate_id"),
        "phase": gate.get("phase"),
        "dataset_root": str(dataset_root),
        "repo_id": args.repo_id,
        "pretrained_model": str(pretrained_model),
        "started_at_utc": started_at,
        "input_hashes": {
            "gate_sha256": gate_sha256,
            "port_config_sha256": port_sha256,
            "interface_contract_sha256": interface_sha256,
            "fixed_base_plan_sha256": fixed_plan_sha256,
        },
        "output_artifacts": list(OUTPUT_ARTIFACTS),
    }

    output_dir.mkdir(parents=True, exist_ok=False)

    try:
        runtime = LeRobotOpenLoopRuntime(
            dataset_root=dataset_root,
            repo_id=args.repo_id,
            pretrained_model=pretrained_model,
            gate=gate,
            port_sha256=port_sha256,
            interface_sha256=interface_sha256,
            fixed_plan_sha256=fixed_plan_sha256,
        )
        receipt = run_open_loop_inference(
            runtime,
            gate=gate,
            gate_sha256=gate_sha256,
            port=port,
            fixed_plan=fixed_plan,
            interface=interface,
        )
        actions = [record for record in receipt.get("per_sample", [])]
    except Exception as exc:  # noqa: BLE001 - fail closed on any runtime failure
        # Fail closed: preserve a failed receipt, actions log, and status that
        # name the defect.  Never claim inference success.
        receipt = {
            "schema_version": 1,
            "gate_id": gate.get("gate_id"),
            "task_id": gate.get("task_id"),
            "phase": gate.get("phase"),
            "open_loop_inference_pass": False,
            "issues": [f"gate_failed_closed:{type(exc).__name__}:{exc}"],
            "started_at_utc": started_at,
            "gate_sha256": gate_sha256,
            "claim_boundary": gate.get("claim_boundary", {}),
        }
        publish_artifacts(output_dir=output_dir, started=started, actions=[], receipt=receipt)
        return 2
    publish_artifacts(output_dir=output_dir, started=started, actions=actions, receipt=receipt)
    return 0 if receipt.get("open_loop_inference_pass") else 2


if __name__ == "__main__":
    sys.exit(main())
