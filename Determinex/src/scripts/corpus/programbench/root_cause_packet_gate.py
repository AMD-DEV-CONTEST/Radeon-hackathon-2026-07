#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.root_cause_packet import (
    check_evidence_references,
    missing_required_fields,
    verify_packet_signature,
)
from corpus.programbench.root_cause_packet_schema import (
    ALLOWED_RERUN_SCOPE_FIELDS,
    CRITICAL_PACKET_FIELDS,
    READY_STATUS,
    RootCausePacketStatus,
)


@dataclass(slots=True)
class PacketValidationResult:
    status: str
    packet_id: str = ""
    reasons: list[str] = field(default_factory=list)
    rerun_scope: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RerunGateResult:
    status: str
    packet_status: str = ""
    packet_id: str = ""
    rerun_scope: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


class RootCausePacketGate:
    def __init__(self, root: Path = Path(".")) -> None:
        self.root = root

    def validate_packet(self, packet: dict[str, Any]) -> PacketValidationResult:
        packet_id = str(packet.get("packet_id") or "")
        missing = missing_required_fields(packet)
        critical_missing = [field for field in CRITICAL_PACKET_FIELDS if field in missing]
        if critical_missing or missing:
            return PacketValidationResult(
                RootCausePacketStatus.ROOT_CAUSE_PACKET_INCOMPLETE.value,
                packet_id=packet_id,
                reasons=[f"missing:{field}" for field in missing],
            )

        if not verify_packet_signature(packet):
            return PacketValidationResult(
                RootCausePacketStatus.ROOT_CAUSE_PACKET_REJECTED.value,
                packet_id=packet_id,
                reasons=["packet_signature_invalid"],
            )

        evidence = check_evidence_references(packet, self.root)
        if evidence.stale:
            return PacketValidationResult(
                RootCausePacketStatus.ROOT_CAUSE_PACKET_STALE.value,
                packet_id=packet_id,
                reasons=evidence.stale,
            )
        if evidence.conflicts:
            return PacketValidationResult(
                RootCausePacketStatus.ROOT_CAUSE_PACKET_CONFLICT.value,
                packet_id=packet_id,
                reasons=evidence.conflicts,
            )
        if evidence.missing:
            return PacketValidationResult(
                RootCausePacketStatus.ROOT_CAUSE_PACKET_INCOMPLETE.value,
                packet_id=packet_id,
                reasons=evidence.missing,
            )

        rerun_scope = _bounded_rerun_scope(packet.get("rerun_scope"))
        if not rerun_scope:
            return PacketValidationResult(
                RootCausePacketStatus.ROOT_CAUSE_PACKET_INCOMPLETE.value,
                packet_id=packet_id,
                reasons=["rerun_scope_unbounded_or_empty"],
            )

        if _references_quarantine_manifest(packet):
            return PacketValidationResult(
                RootCausePacketStatus.ROOT_CAUSE_PACKET_REJECTED.value,
                packet_id=packet_id,
                reasons=["quarantine_only_replay_manifest_cannot_authorize_rerun"],
            )

        return PacketValidationResult(
            READY_STATUS,
            packet_id=packet_id,
            rerun_scope=rerun_scope,
        )

    def authorize_rerun(self, packet_path: Path | None) -> RerunGateResult:
        if packet_path is None or not packet_path.is_file():
            return RerunGateResult(
                RootCausePacketStatus.RERUN_BLOCKED_NO_PACKET.value, reasons=["packet_missing"]
            )
        packet = json.loads(packet_path.read_text(encoding="utf-8", errors="replace"))
        validation = self.validate_packet(packet)
        if validation.status == RootCausePacketStatus.ROOT_CAUSE_PACKET_STALE.value:
            return RerunGateResult(
                RootCausePacketStatus.RERUN_BLOCKED_STALE_PACKET.value,
                packet_status=validation.status,
                packet_id=validation.packet_id,
                reasons=validation.reasons,
            )
        if validation.status != READY_STATUS:
            return RerunGateResult(
                RootCausePacketStatus.RERUN_BLOCKED_NO_PACKET.value,
                packet_status=validation.status,
                packet_id=validation.packet_id,
                reasons=validation.reasons,
            )
        return RerunGateResult(
            RootCausePacketStatus.RERUN_AUTHORIZED.value,
            packet_status=validation.status,
            packet_id=validation.packet_id,
            rerun_scope=validation.rerun_scope,
        )


def _bounded_rerun_scope(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    bounded = {key: raw[key] for key in ALLOWED_RERUN_SCOPE_FIELDS if raw.get(key) is not None}
    if not bounded.get("tool") and not bounded.get("candidate_id") and not bounded.get("filter"):
        return {}
    bounded.setdefault("max_attempts", 1)
    return bounded


def _references_quarantine_manifest(packet: dict[str, Any]) -> bool:
    inputs = packet.get("evidence_inputs") or []
    if not isinstance(inputs, list):
        return False
    for item in inputs:
        if isinstance(item, dict):
            if item.get("quarantine_only") is True:
                return True
            path = str(item.get("path") or "")
        else:
            path = str(item)
        if not path.endswith(".replay_manifest.json"):
            continue
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if data.get("quarantine_only") is True:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate ProgramBench root-cause packets and authorize bounded reruns."
    )
    parser.add_argument("packet", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--authorize", action="store_true")
    args = parser.parse_args()
    gate = RootCausePacketGate(root=args.root)
    if args.authorize:
        result = gate.authorize_rerun(args.packet)
    else:
        packet = json.loads(args.packet.read_text(encoding="utf-8", errors="replace"))
        result = gate.validate_packet(packet)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
