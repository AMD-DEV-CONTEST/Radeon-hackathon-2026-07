#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.bounded_rerun_record import (
    make_authorization_record,
    make_outcome_record,
    write_bounded_rerun_record,
)
from corpus.programbench.root_cause_packet_gate import RootCausePacketGate
from corpus.programbench.root_cause_packet_schema import RootCausePacketStatus


class BoundedRerunStatus(str, Enum):
    BOUNDED_RERUN_READY = "BOUNDED_RERUN_READY"
    BOUNDED_RERUN_AUTHORIZED = "BOUNDED_RERUN_AUTHORIZED"
    BOUNDED_RERUN_BLOCKED_NO_PACKET = "BOUNDED_RERUN_BLOCKED_NO_PACKET"
    BOUNDED_RERUN_BLOCKED_STALE_PACKET = "BOUNDED_RERUN_BLOCKED_STALE_PACKET"
    BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH = "BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH"
    BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT = "BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT"
    BOUNDED_RERUN_BLOCKED_QUARANTINE_ONLY = "BOUNDED_RERUN_BLOCKED_QUARANTINE_ONLY"
    BOUNDED_RERUN_BLOCKED_CONFLICT = "BOUNDED_RERUN_BLOCKED_CONFLICT"
    BOUNDED_RERUN_OUTCOME_RECORDED = "BOUNDED_RERUN_OUTCOME_RECORDED"


RerunExecutor = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class BoundedRerunDecision:
    status: str
    packet_id: str = ""
    target: dict[str, Any] = field(default_factory=dict)
    rerun_scope: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    record_path: str = ""


class BoundedRerunGate:
    def __init__(
        self,
        root: Path = Path("."),
        output_dir: Path = Path("assurance/evidence/programbench_bounded_reruns"),
    ) -> None:
        self.root = root
        self.output_dir = output_dir
        self.packet_gate = RootCausePacketGate(root=root)

    def authorize(
        self, packet_path: Path | None, target: dict[str, Any], *, attempt_index: int = 1
    ) -> BoundedRerunDecision:
        packet_status = self.packet_gate.authorize_rerun(packet_path)
        if packet_status.status == RootCausePacketStatus.RERUN_BLOCKED_STALE_PACKET.value:
            return self._decision(
                BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_STALE_PACKET.value,
                packet_status.packet_id,
                target,
                packet_status.rerun_scope,
                packet_status.reasons,
            )
        if packet_status.status != RootCausePacketStatus.RERUN_AUTHORIZED.value:
            status = BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_NO_PACKET.value
            if (
                packet_status.packet_status
                == RootCausePacketStatus.ROOT_CAUSE_PACKET_CONFLICT.value
            ):
                status = BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_CONFLICT.value
            if (
                packet_status.packet_status
                == RootCausePacketStatus.ROOT_CAUSE_PACKET_REJECTED.value
            ):
                if (
                    "quarantine_only_replay_manifest_cannot_authorize_rerun"
                    in packet_status.reasons
                ):
                    status = BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_QUARANTINE_ONLY.value
            return self._decision(
                status,
                packet_status.packet_id,
                target,
                packet_status.rerun_scope,
                packet_status.reasons,
            )

        scope = packet_status.rerun_scope
        mismatch = _scope_mismatch(scope, target)
        if mismatch:
            return self._decision(
                BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH.value,
                packet_status.packet_id,
                target,
                scope,
                mismatch,
            )

        max_attempts = int(scope.get("max_attempts") or 1)
        if attempt_index > max_attempts:
            return self._decision(
                BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT.value,
                packet_status.packet_id,
                target,
                scope,
                [f"attempt_index:{attempt_index}>max_attempts:{max_attempts}"],
            )

        return self._decision(
            BoundedRerunStatus.BOUNDED_RERUN_AUTHORIZED.value,
            packet_status.packet_id,
            target,
            scope,
            [],
        )

    def execute_with_mock(
        self,
        packet_path: Path,
        target: dict[str, Any],
        executor: RerunExecutor,
        *,
        attempt_index: int = 1,
    ) -> BoundedRerunDecision:
        authorization = self.authorize(packet_path, target, attempt_index=attempt_index)
        if authorization.status != BoundedRerunStatus.BOUNDED_RERUN_AUTHORIZED.value:
            return authorization
        outcome = executor(
            {
                "target": target,
                "rerun_scope": authorization.rerun_scope,
                "packet_id": authorization.packet_id,
                "attempt_index": attempt_index,
            }
        )
        record = make_outcome_record(
            packet_id=authorization.packet_id,
            target=target,
            rerun_scope=authorization.rerun_scope,
            outcome=_normalize_outcome(outcome),
        )
        path = write_bounded_rerun_record(record, self.output_dir)
        return BoundedRerunDecision(
            BoundedRerunStatus.BOUNDED_RERUN_OUTCOME_RECORDED.value,
            packet_id=authorization.packet_id,
            target=target,
            rerun_scope=authorization.rerun_scope,
            record_path=str(path),
        )

    def _decision(
        self,
        status: str,
        packet_id: str,
        target: dict[str, Any],
        rerun_scope: dict[str, Any],
        reasons: list[str],
    ) -> BoundedRerunDecision:
        record = make_authorization_record(
            status=status,
            packet_id=packet_id,
            target=target,
            rerun_scope=rerun_scope,
            reasons=reasons,
        )
        path = write_bounded_rerun_record(record, self.output_dir)
        return BoundedRerunDecision(
            status,
            packet_id=packet_id,
            target=target,
            rerun_scope=rerun_scope,
            reasons=reasons,
            record_path=str(path),
        )


def _scope_mismatch(scope: dict[str, Any], target: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in ("tool", "candidate_id", "filter"):
        if scope.get(key) is not None and target.get(key) != scope.get(key):
            reasons.append(f"{key}_mismatch:{target.get(key)}!={scope.get(key)}")
    return reasons


def _normalize_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(outcome)
    normalized.setdefault("record_status", "active_eval_evidence")
    normalized.setdefault("training_eligible", False)
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Authorize bounded ProgramBench rerun execution from a root-cause packet."
    )
    parser.add_argument("packet", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--tool", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--attempt-index", type=int, default=1)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("assurance/evidence/programbench_bounded_reruns")
    )
    args = parser.parse_args()
    target = {"tool": args.tool, "candidate_id": args.candidate_id}
    decision = BoundedRerunGate(root=args.root, output_dir=args.output_dir).authorize(
        args.packet,
        target,
        attempt_index=args.attempt_index,
    )
    print(json.dumps(asdict(decision), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
