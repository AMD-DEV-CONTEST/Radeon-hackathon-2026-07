#!/usr/bin/env python3
"""Run one frozen G3 learned-policy closed-loop episode in Genesis on the ACT.

This is the thin CLI for ``src/mantis_rocm_bridge/act_closedloop_g3.py``.  It
loads every versioned contract plus the frozen local checkpoint path supplied
on the command line, validates LeRobot 0.4.4 and the saved checkpoint
processors with no fallback, requires the single AMD Radeon HIP device defined
by the phase contract (unless a dependency-injected test adapter is supplied by
unit tests), constructs the same table, fixed Mantis URDF, three-bowl reset
distribution, three cameras, actuator gains/limits, allowed-collision filter,
friction, and strict safety monitoring as the accepted Genesis task, then runs
the causal 30 Hz perception-decision-control loop with zero scripted
assistance.

The receipt and ``status`` are always written when the output directory was
successfully admitted, even on ordinary task failure or runtime failure, so a
failed run still preserves its evidence (fail-closed, fresh-output,
non-overwriting artifact semantics).  Network / GPU / LeRobot / Genesis work
lives entirely inside :class:`GenesisClosedLoopRuntime`, which imports those
packages lazily; this module imports only the Python standard library plus the
pure-Python core at import time.

Exit codes: ``0`` on a passing (task-success) episode receipt, ``2`` on a
failing receipt, on a safety failure, or on any argument / output-directory
violation.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from mantis_rocm_bridge.act_closedloop_g3 import (
    AGGREGATE_ARTIFACTS,
    EXPECTED_GENESIS_VERSION,
    EXPECTED_LEROBOT_VERSION,
    PER_EPISODE_ARTIFACTS,
    SafetySignals,
    EvaluatorFrame,
    GenesisClosedLoopRuntime,
    run_closed_loop_episode,
    sha256_file,
    write_text_exclusive,
)
from mantis_rocm_bridge.contracts import ContractError, load_json


ROOT = Path(__file__).resolve().parents[1]


def _now_utc_iso() -> str:
    """Return the current UTC timestamp in ISO-8601.  Tests monkeypatch this."""

    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_absolute_path(path: Path, *, arg: str, parser: argparse.ArgumentParser) -> Path:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        parser.error(f"{arg} must be an absolute path, got: {path}")
    return resolved


def build_sha256sums(output_dir: Path) -> str:
    """Deterministic ``SHA256SUMS`` over every real file except the manifest."""

    names = sorted(path.name for path in output_dir.iterdir() if path.is_file())
    entries = [
        (sha256_file(output_dir / name), name)
        for name in names
        if name != "SHA256SUMS"
    ]
    return "".join(f"{digest}  {name}\n" for digest, name in entries)


def _rocm_smi_evidence() -> dict[str, Any]:
    """Best-effort ``rocm-smi`` capture for the official AMD single device.

    Prefers ``/opt/rocm/bin/rocm-smi --showuse --showmemuse --showpids`` and
    falls back to whichever ``rocm-smi`` is on ``PATH``.  The command, return
    code, stdout and stderr are all recorded.  Missing telemetry is recorded as
    such rather than treated as success evidence; this never raises.
    """

    preferred = Path("/opt/rocm/bin/rocm-smi")
    command: list[str]
    if preferred.is_file():
        command = [str(preferred), "--showuse", "--showmemuse", "--showpids"]
    else:
        fallback = shutil.which("rocm-smi")
        if not fallback:
            return {
                "available": False,
                "command": None,
                "return_code": None,
                "stdout": "",
                "stderr": "rocm-smi not found on PATH or at /opt/rocm/bin/rocm-smi",
            }
        command = [fallback, "--showuse", "--showmemuse", "--showpids"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 - descriptive only
        return {
            "available": False,
            "command": " ".join(command),
            "return_code": None,
            "stdout": "",
            "stderr": f"rocm-smi capture failed:{type(exc).__name__}:{exc}",
        }
    return {
        "available": True,
        "command": " ".join(command),
        "return_code": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _gpu_evidence(label: str) -> str:
    """Capture descriptive GPU evidence for the official AMD single device.

    Records the torch identity and a best-effort ``rocm-smi`` capture (command,
    return code, stdout, stderr).  This is best-effort descriptive text; it is
    never a pass threshold and never a comparative performance claim.  Failure to
    capture any part is recorded as such -- missing telemetry is never treated as
    task-success evidence -- rather than aborting the episode.
    """

    lines = [f"{label}:"]

    torch_block: dict[str, Any]
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch_block = {
                "available": True,
                "device_count": int(torch.cuda.device_count()),
                "device_name_0": str(torch.cuda.get_device_name(0)),
            }
        else:
            torch_block = {"available": False, "note": "torch.cuda is not available"}
    except Exception as exc:  # noqa: BLE001 - descriptive only
        torch_block = {
            "available": False,
            "note": f"torch_unavailable:{type(exc).__name__}",
        }
    lines.append("  torch: " + json.dumps(torch_block, sort_keys=True))

    rocm = _rocm_smi_evidence()
    lines.append("  rocm_smi: " + json.dumps(rocm, sort_keys=True))
    if not rocm.get("available"):
        lines.append(
            "  note: rocm-smi telemetry was not captured; this is recorded, not "
            "treated as task-success evidence"
        )
    return "\n".join(lines) + "\n"


def publish_episode_artifacts(
    *,
    output_dir: Path,
    started: dict[str, Any],
    command: str,
    environment: dict[str, Any],
    policy_steps: list[dict[str, Any]],
    evaluator_rows: list[dict[str, Any]],
    receipt: dict[str, Any],
    stdout_text: str,
    stderr_text: str,
    exit_code: int,
    gpu_before: str,
    gpu_during: str,
    gpu_after: str,
) -> None:
    """Write the fail-closed per-episode artifact set exclusively."""

    write_text_exclusive(
        output_dir / "started.json",
        json.dumps(started, indent=2, sort_keys=True) + "\n",
    )
    write_text_exclusive(output_dir / "command.txt", command)
    write_text_exclusive(
        output_dir / "environment.json",
        json.dumps(environment, indent=2, sort_keys=True) + "\n",
    )
    step_lines = [json.dumps(record, sort_keys=True) for record in policy_steps]
    write_text_exclusive(
        output_dir / "policy_steps.jsonl",
        ("\n".join(step_lines) + "\n") if step_lines else "",
    )
    eval_lines = [json.dumps(record, sort_keys=True) for record in evaluator_rows]
    write_text_exclusive(
        output_dir / "strict_evaluator.jsonl",
        ("\n".join(eval_lines) + "\n") if eval_lines else "",
    )
    write_text_exclusive(
        output_dir / "receipt.json",
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    )
    write_text_exclusive(
        output_dir / "status",
        "PASS\n" if receipt.get("task_success") else "FAIL\n",
    )
    write_text_exclusive(output_dir / "stdout.log", stdout_text)
    write_text_exclusive(output_dir / "stderr.log", stderr_text)
    write_text_exclusive(output_dir / "exit_code.txt", f"{int(exit_code)}\n")
    write_text_exclusive(output_dir / "finished_at_utc.txt", _now_utc_iso() + "\n")
    write_text_exclusive(output_dir / "gpu_before.txt", gpu_before)
    write_text_exclusive(output_dir / "gpu_during.txt", gpu_during)
    write_text_exclusive(output_dir / "gpu_after.txt", gpu_after)
    write_text_exclusive(output_dir / "SHA256SUMS", build_sha256sums(output_dir))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "checkpoint_root",
        type=Path,
        help="absolute path to the frozen 060000 checkpoint root (containing pretrained_model/)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        required=True,
        help="frozen G3 seed (101-110); seed 101 is the infrastructure smoke",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="fresh, exclusive per-episode output directory that must not yet exist",
    )
    parser.add_argument(
        "--gate",
        type=Path,
        default=ROOT / "configs/act-closedloop-g3-v1.json",
    )
    parser.add_argument(
        "--task",
        type=Path,
        default=ROOT / "configs/task-pack-v1.json",
    )
    parser.add_argument(
        "--port-config",
        type=Path,
        default=ROOT / "configs/mantis-port-config.json",
    )
    parser.add_argument(
        "--fixed-plan",
        type=Path,
        default=ROOT / "configs/fixed-base-plan.json",
    )
    parser.add_argument(
        "--scene-contract",
        type=Path,
        default=ROOT / "configs/stack-bowls-genesis-v1.json",
    )
    parser.add_argument(
        "--camera-contract",
        type=Path,
        default=ROOT / "configs/camera-extrinsics-v1.json",
    )
    parser.add_argument(
        "--source-task",
        type=Path,
        default=ROOT / "configs/source-task-stack-bowls-three.json",
    )
    parser.add_argument(
        "--interface",
        type=Path,
        default=ROOT / "configs/mantis-lerobot-interface-v1.json",
    )
    parser.add_argument(
        "--bowl-asset-root",
        type=Path,
        required=True,
        help="absolute path to the materialized bowl asset root (containing urdf/ and manifest.json)",
    )
    parser.add_argument(
        "--mantis-urdf",
        type=Path,
        required=True,
        help="absolute path to the fixed-base Mantis URDF",
    )
    parser.add_argument(
        "--backend",
        choices=("cpu", "cuda", "amdgpu"),
        default="amdgpu",
        help="Genesis backend (amdgpu is the official AMD runtime)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    checkpoint_root = _require_absolute_path(
        args.checkpoint_root, arg="checkpoint_root", parser=parser
    )
    output_dir = _require_absolute_path(args.output_dir, arg="--output-dir", parser=parser)
    gate_path = _require_absolute_path(args.gate, arg="--gate", parser=parser)
    task_path = _require_absolute_path(args.task, arg="--task", parser=parser)
    port_path = _require_absolute_path(args.port_config, arg="--port-config", parser=parser)
    fixed_plan_path = _require_absolute_path(args.fixed_plan, arg="--fixed-plan", parser=parser)
    scene_path = _require_absolute_path(args.scene_contract, arg="--scene-contract", parser=parser)
    camera_path = _require_absolute_path(args.camera_contract, arg="--camera-contract", parser=parser)
    source_task_path = _require_absolute_path(args.source_task, arg="--source-task", parser=parser)
    interface_path = _require_absolute_path(args.interface, arg="--interface", parser=parser)
    bowl_root = _require_absolute_path(args.bowl_asset_root, arg="--bowl-asset-root", parser=parser)
    mantis_urdf = _require_absolute_path(args.mantis_urdf, arg="--mantis-urdf", parser=parser)

    if output_dir.exists():
        parser.error(f"refusing to reuse or overwrite output directory: {output_dir}")
    if not checkpoint_root.is_dir():
        parser.error(f"checkpoint_root is not a directory: {checkpoint_root}")
    if not bowl_root.is_dir():
        parser.error(f"--bowl-asset-root is not a directory: {bowl_root}")
    if not mantis_urdf.is_file():
        parser.error(f"--mantis-urdf is not a file: {mantis_urdf}")

    gate = load_json(gate_path)
    task = load_json(task_path)
    port = load_json(port_path)
    fixed_plan = load_json(fixed_plan_path)
    scene_contract = load_json(scene_path)
    camera_contract = load_json(camera_path)
    source_task = load_json(source_task_path)
    interface = load_json(interface_path)

    gate_sha256 = sha256_file(gate_path)
    task_sha256 = sha256_file(task_path)
    port_sha256 = sha256_file(port_path)
    fixed_plan_sha256 = sha256_file(fixed_plan_path)
    scene_sha256 = sha256_file(scene_path)
    camera_sha256 = sha256_file(camera_path)
    source_task_sha256 = sha256_file(source_task_path)
    interface_sha256 = sha256_file(interface_path)
    mantis_urdf_sha256 = sha256_file(mantis_urdf)

    # The frozen open-loop admission contract named by the G3 gate is the single
    # source of truth for the required checkpoint files and processor-artifact
    # hashes.  Load it, require it to be the admitted v3 gate, and record its
    # SHA-256 in started / source / input hashes and the receipt.
    from mantis_rocm_bridge.contracts import ContractError

    openloop_admission_rel = gate.get("openloop_admission_contract")
    if not isinstance(openloop_admission_rel, str) or not openloop_admission_rel:
        parser.error("G3 gate does not name an openloop_admission_contract")
    openloop_admission_path = (ROOT / openloop_admission_rel).resolve()
    if not openloop_admission_path.is_file():
        parser.error(
            f"openloop admission contract not found: {openloop_admission_path}"
        )
    openloop_admission_gate = load_json(openloop_admission_path)
    if openloop_admission_gate.get("gate_id") != "mantis_act_openloop_inference_v3":
        parser.error(
            "openloop_admission_contract must be the admitted v3 gate "
            "(gate_id=mantis_act_openloop_inference_v3)"
        )
    openloop_admission_gate_sha256 = sha256_file(openloop_admission_path)

    bowl_urdf = bowl_root / "urdf" / "robotwin_002_bowl_model3.urdf"
    bowl_manifest_path = bowl_root / "manifest.json"
    if not bowl_urdf.is_file():
        parser.error(f"required bowl URDF does not exist: {bowl_urdf}")
    if not bowl_manifest_path.is_file():
        parser.error(f"required bowl manifest does not exist: {bowl_manifest_path}")
    bowl_manifest = load_json(bowl_manifest_path)
    if bowl_manifest.get("distribution_allowed") is not True:
        parser.error("bowl materialization is not licensed for distribution")
    bowl_urdf_sha256 = sha256_file(bowl_urdf)

    # Frozen seed contract: the seed must belong to the exact frozen set and is
    # never replaced.
    from mantis_rocm_bridge.act_closedloop_g3 import (
        is_frozen_g3_seed,
        is_smoke_seed,
    )

    if not is_frozen_g3_seed(args.seed, gate):
        parser.error(
            f"seed {args.seed} is not in the frozen G3 set 101-110; seed "
            "replacement is forbidden"
        )

    command = " ".join([sys.argv[0], *(str(a) for a in (argv or sys.argv[1:]))])
    started_at = _now_utc_iso()
    started = {
        "gate_id": gate.get("gate_id"),
        "phase": gate.get("phase"),
        "seed": int(args.seed),
        "smoke_seed": is_smoke_seed(args.seed, gate),
        "checkpoint_root": str(checkpoint_root),
        "started_at_utc": started_at,
        "input_hashes": {
            "gate_sha256": gate_sha256,
            "task_contract_sha256": task_sha256,
            "port_config_sha256": port_sha256,
            "fixed_base_plan_sha256": fixed_plan_sha256,
            "scene_contract_sha256": scene_sha256,
            "camera_contract_sha256": camera_sha256,
            "source_task_contract_sha256": source_task_sha256,
            "interface_contract_sha256": interface_sha256,
            "mantis_urdf_sha256": mantis_urdf_sha256,
            "bowl_urdf_sha256": bowl_urdf_sha256,
            "openloop_admission_contract_sha256": openloop_admission_gate_sha256,
        },
        "output_artifacts": list(PER_EPISODE_ARTIFACTS),
    }

    environment = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "expected_lerobot_version": EXPECTED_LEROBOT_VERSION,
        "expected_genesis_version": EXPECTED_GENESIS_VERSION,
        "backend": args.backend,
        "single_gpu_only": True,
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    gpu_before = _gpu_evidence("before")
    gpu_during = ""
    gpu_after = ""
    exit_code = 2

    source_hashes = {
        "task_contract": task_sha256,
        "port_config": port_sha256,
        "fixed_base_plan": fixed_plan_sha256,
        "scene_contract": scene_sha256,
        "camera_contract": camera_sha256,
        "source_task_contract": source_task_sha256,
        "interface_contract": interface_sha256,
        "mantis_urdf": mantis_urdf_sha256,
        "bowl_urdf": bowl_urdf_sha256,
        "openloop_admission_contract": openloop_admission_gate_sha256,
    }

    try:
        runtime = GenesisClosedLoopRuntime(
            checkpoint_root=checkpoint_root,
            pretrained_model=checkpoint_root / "pretrained_model",
            mantis_urdf=mantis_urdf,
            bowl_urdf=bowl_urdf,
            gate=gate,
            task=task,
            port=port,
            fixed_plan=fixed_plan,
            scene_contract=scene_contract,
            camera_contract=camera_contract,
            source_task=source_task,
            interface=interface,
            seed=int(args.seed),
            backend=args.backend,
            port_sha256=port_sha256,
            interface_sha256=interface_sha256,
            fixed_plan_sha256=fixed_plan_sha256,
            openloop_admission_gate=openloop_admission_gate,
            openloop_admission_gate_sha256=openloop_admission_gate_sha256,
            stdout=stdout_buf,
            stderr=stderr_buf,
        )
        gpu_during = _gpu_evidence("during")
        receipt = run_closed_loop_episode(
            runtime,
            gate=gate,
            gate_sha256=gate_sha256,
            task=task,
            port=port,
            fixed_plan=fixed_plan,
            seed=int(args.seed),
            source_hashes=source_hashes,
            checkpoint_hashes=runtime.processor_artifact_hashes,
        )
        exit_code = 0 if receipt.get("task_success") else 2
    except Exception as exc:  # noqa: BLE001 - fail closed, preserve evidence
        stderr_buf.write(f"closed_loop_runtime_failed:{type(exc).__name__}:{exc}\n")
        # A Python exception caught by the CLI is an infrastructure defect, not a
        # task failure.  Emit an immutable *terminal* execution receipt
        # (terminal=true, infrastructure_failure=true,
        # terminal_reason=runtime_error) so the seed-101 smoke admission blocks
        # the batch instead of relabelling the defect as an ordinary task
        # failure.
        receipt = {
            "schema_version": 1,
            "gate_id": gate.get("gate_id"),
            "task_id": gate.get("task_id"),
            "phase": gate.get("phase"),
            "seed": int(args.seed),
            "task_success": False,
            "terminal": True,
            "terminal_reason": "runtime_error",
            "infrastructure_failure": True,
            "has_safety_failure": False,
            "safety_failure_count": 0,
            "safety_failure_reasons": [],
            "failure_taxonomy_label": "runtime_error",
            "runtime_identity": {"identity_issues": ["cli_runtime_exception"]},
            "issues": [f"gate_failed_closed:{type(exc).__name__}:{exc}"],
            "started_at_utc": started_at,
            "gate_sha256": gate_sha256,
            "openloop_admission_contract_sha256": openloop_admission_gate_sha256,
            "claim_boundary": gate.get("claim_boundary", {}),
        }
        exit_code = 2
    finally:
        gpu_after = _gpu_evidence("after")

    policy_steps = receipt.get("policy_steps", [])
    evaluator_rows = receipt.get("strict_evaluator_rows", [])

    publish_episode_artifacts(
        output_dir=output_dir,
        started=started,
        command=command,
        environment=environment,
        policy_steps=policy_steps,
        evaluator_rows=evaluator_rows,
        receipt=receipt,
        stdout_text=stdout_buf.getvalue(),
        stderr_text=stderr_buf.getvalue(),
        exit_code=exit_code,
        gpu_before=gpu_before,
        gpu_during=gpu_during,
        gpu_after=gpu_after,
    )
    stdout_buf.write(json.dumps({"task_success": receipt.get("task_success"), "seed": args.seed}, sort_keys=True) + "\n")
    sys.stdout.write(stdout_buf.getvalue())
    if stderr_buf.getvalue():
        sys.stderr.write(stderr_buf.getvalue())
    return int(exit_code)


if __name__ == "__main__":
    sys.exit(main())
