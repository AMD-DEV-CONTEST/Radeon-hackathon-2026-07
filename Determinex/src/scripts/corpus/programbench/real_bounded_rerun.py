#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.bounded_rerun_gate import BoundedRerunGate, BoundedRerunStatus
from corpus.programbench.real_bounded_rerun_record import (
    make_real_rerun_record,
    write_real_rerun_record,
)


class RealBoundedRerunStatus(str, Enum):
    REAL_BOUNDED_RERUN_EXECUTED = "REAL_BOUNDED_RERUN_EXECUTED"
    REAL_BOUNDED_RERUN_IMPROVED = "REAL_BOUNDED_RERUN_IMPROVED"
    REAL_BOUNDED_RERUN_REJECTED = "REAL_BOUNDED_RERUN_REJECTED"
    REAL_BOUNDED_RERUN_REGRESSED = "REAL_BOUNDED_RERUN_REGRESSED"
    REAL_BOUNDED_RERUN_INFRA_FAILURE = "REAL_BOUNDED_RERUN_INFRA_FAILURE"
    REAL_BOUNDED_RERUN_BLOCKED_PACKET_INVALID = "REAL_BOUNDED_RERUN_BLOCKED_PACKET_INVALID"
    REAL_BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH = "REAL_BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH"
    REAL_BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT = "REAL_BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT"
    REAL_BOUNDED_RERUN_OUTCOME_SIGNED = "REAL_BOUNDED_RERUN_OUTCOME_SIGNED"


LiveExecutor = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class RealBoundedRerunConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_real_bounded_reruns")
    attempt_index: int = 1
    executor: LiveExecutor | None = None


class RealBoundedRerun:
    def __init__(self, config: RealBoundedRerunConfig | None = None) -> None:
        self.config = config or RealBoundedRerunConfig()
        self.bounded_gate = BoundedRerunGate(
            root=self.config.root,
            output_dir=self.config.output_dir,
        )

    def run(self, packet_path: Path, target: dict[str, Any]) -> dict[str, Any]:
        authorization = self.bounded_gate.authorize(
            packet_path, target, attempt_index=self.config.attempt_index
        )
        if authorization.status != BoundedRerunStatus.BOUNDED_RERUN_AUTHORIZED.value:
            status = _blocked_status(authorization.status)
            return self._record(
                status,
                authorization.packet_id,
                target,
                authorization.rerun_scope,
                reasons=authorization.reasons,
            )

        if int(authorization.rerun_scope.get("max_attempts") or 1) != 1:
            return self._record(
                RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT.value,
                authorization.packet_id,
                target,
                authorization.rerun_scope,
                reasons=["real_bounded_rerun_requires_max_attempts_1"],
            )

        executor = self.config.executor or _programbench_gate_executor
        try:
            outcome = executor(
                {
                    "target": target,
                    "rerun_scope": authorization.rerun_scope,
                    "packet_id": authorization.packet_id,
                }
            )
        except Exception as exc:
            return self._record(
                RealBoundedRerunStatus.REAL_BOUNDED_RERUN_INFRA_FAILURE.value,
                authorization.packet_id,
                target,
                authorization.rerun_scope,
                outcome={"error": type(exc).__name__, "message": str(exc)[:1000]},
            )

        status = _classify_outcome(outcome)
        return self._record(
            status, authorization.packet_id, target, authorization.rerun_scope, outcome=outcome
        )

    def _record(
        self,
        status: str,
        packet_id: str,
        target: dict[str, Any],
        rerun_scope: dict[str, Any],
        *,
        outcome: dict[str, Any] | None = None,
        reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        record = make_real_rerun_record(
            status=status,
            packet_id=packet_id,
            target=target,
            rerun_scope=rerun_scope,
            outcome=_normalize_outcome(outcome or {}),
            reasons=reasons or [],
        )
        path = write_real_rerun_record(record, self.config.output_dir)
        return {"record_path": str(path), "record": record}


def _programbench_gate_executor(context: dict[str, Any]) -> dict[str, Any]:
    scope = context["rerun_scope"]
    tool = str(scope.get("tool") or "")
    run_root = Path(str(scope.get("run_root") or ""))
    baseline_eval = Path(str(scope.get("baseline_eval") or ""))
    min_baseline = int(scope.get("min_baseline_passed") or 1)
    timeout = int(scope.get("timeout_seconds") or 3600)
    if not tool or not run_root or not baseline_eval:
        return {
            "status": "infra_failure",
            "error": "missing_live_rerun_scope_fields",
            "required": ["tool", "run_root", "baseline_eval"],
        }
    cmd = [
        sys.executable,
        "scripts/pb_candidate_gate.py",
        tool,
        str(run_root),
        "--baseline-eval",
        str(baseline_eval),
        "--min-baseline-passed",
        str(min_baseline),
    ]
    completed = subprocess.run(
        cmd,
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    gate_result = run_root / "gate_result.json"
    parsed = _read_json(gate_result)
    return {
        "status": "executed",
        "command": cmd,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "gate_result_path": str(gate_result),
        "gate_result": parsed,
    }


def _classify_outcome(outcome: dict[str, Any]) -> str:
    if outcome.get("status") == "infra_failure" or outcome.get("error"):
        return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_INFRA_FAILURE.value
    combined_output = f"{outcome.get('stdout', '')}\n{outcome.get('stderr', '')}".lower()
    if any(
        marker in combined_output
        for marker in (
            "preflight failed",
            "image missing",
            "no such image",
            "docker daemon",
            "docker unavailable",
        )
    ):
        return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_INFRA_FAILURE.value
    gate = outcome.get("gate_result") if isinstance(outcome.get("gate_result"), dict) else {}
    decision = str(gate.get("decision") or outcome.get("decision") or "")
    delta = gate.get("delta") if isinstance(gate.get("delta"), dict) else {}
    passed_delta = int(delta.get("passed") or outcome.get("passed_delta") or 0)
    if decision == "accept" or passed_delta > 0:
        return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_IMPROVED.value
    if decision == "reject" and passed_delta < 0:
        return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_REGRESSED.value
    if decision == "reject":
        return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_REJECTED.value
    return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_EXECUTED.value


def _blocked_status(status: str) -> str:
    if status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH.value:
        return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH.value
    if status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT.value:
        return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT.value
    return RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_PACKET_INVALID.value


def _normalize_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(outcome)
    normalized.setdefault("record_status", "active_eval_evidence")
    normalized.setdefault("training_eligible", False)
    return normalized


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"error": f"failed_to_parse_gate_result:{type(exc).__name__}:{exc}"}
    return data if isinstance(data, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one real bounded ProgramBench rerun from an authorized packet."
    )
    parser.add_argument("packet", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--tool", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--attempt-index", type=int, default=1)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_real_bounded_reruns"),
    )
    args = parser.parse_args()
    result = RealBoundedRerun(
        RealBoundedRerunConfig(
            root=args.root, output_dir=args.output_dir, attempt_index=args.attempt_index
        )
    ).run(args.packet, {"tool": args.tool, "candidate_id": args.candidate_id})
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
