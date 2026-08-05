#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.programbench_next_unblock_decision_record import (  # noqa: E402
    make_programbench_next_unblock_decision_record,
    write_programbench_next_unblock_decision_record,
)

DOXYGEN_REF = "assurance/evidence/programbench_doxygen_lane_final_state/doxygen__doxygen.966d98e.DOXYGEN_LANE_FINAL_STATE_WRITTEN.json"
PER_TARGET_GRAPH_REF = "assurance/evidence/programbench_per_target_unified_graph_expansion/run_20260528.PROGRAMBENCH_PER_TARGET_GRAPH_WRITTEN.json"
IMPORT_SCAN_FINAL_REF = "assurance/evidence/programbench_batch001_import_scan_campaign_final_state/programbench_batch001_import_scan_campaign_final_state_run_20260528.BATCH001_IMPORT_SCAN_CAMPAIGN_FINAL_STATE_WRITTEN.json"
LEDGER_REF = "assurance/evidence/append_only_evidence_ledger/run_20260528.APPEND_ONLY_EVIDENCE_LEDGER_VALIDATED.json"
COUNT_GUARD_REF = "assurance/evidence/evidence_count_drift_guard/run_20260528.EVIDENCE_COUNT_DRIFT_GUARD_PASSED.json"


class ProgramBenchNextUnblockDecision:
    def __init__(self, root: Path = Path("."), *, write_record: bool = True) -> None:
        self.root = root
        self.write_record = write_record

    def run(self) -> dict[str, Any]:
        doxygen = self._load(DOXYGEN_REF)
        per_target = self._load(PER_TARGET_GRAPH_REF)
        import_scan = self._load(IMPORT_SCAN_FINAL_REF)
        ledger = self._load(LEDGER_REF)
        count_guard = self._load(COUNT_GUARD_REF)
        decision = decide_next_programbench_unblock(
            doxygen=doxygen,
            per_target=per_target,
            import_scan=import_scan,
            ledger=ledger,
            count_guard=count_guard,
        )
        record = make_programbench_next_unblock_decision_record(
            status=decision["status"],
            payload={
                "record_id": "run_20260528",
                **decision,
                "input_refs": {
                    "doxygen_final_state": DOXYGEN_REF,
                    "programbench_per_target_graph": PER_TARGET_GRAPH_REF,
                    "batch001_import_scan_final": IMPORT_SCAN_FINAL_REF,
                    "append_only_evidence_ledger": LEDGER_REF,
                    "evidence_count_drift_guard": COUNT_GUARD_REF,
                },
            },
        )
        if self.write_record:
            write_programbench_next_unblock_decision_record(
                record,
                self.root / "assurance/evidence/programbench_next_unblock_decision",
            )
        return record

    def _load(self, rel: str) -> dict[str, Any]:
        path = self.root / rel
        if not path.is_file():
            return {"_missing": True, "_path": rel}
        return json.loads(path.read_text(encoding="utf-8"))


def decide_next_programbench_unblock(
    *,
    doxygen: dict[str, Any],
    per_target: dict[str, Any],
    import_scan: dict[str, Any],
    ledger: dict[str, Any],
    count_guard: dict[str, Any],
) -> dict[str, Any]:
    batch_targets = list(per_target.get("batch001_targets", []))
    first_target = batch_targets[0] if batch_targets else {}
    ledger_ready = ledger.get("chain_valid") is True and ledger.get("mutation_detected") is False
    count_ready = count_guard.get("status") == "EVIDENCE_COUNT_DRIFT_GUARD_PASSED"
    options = [
        {
            "option": "doxygen_security_policy_admission",
            "current_status": doxygen.get(
                "security_execution_authority", "ABSENT_PENDING_OPERATOR_POLICY_ADMISSION"
            ),
            "required_operator_packet": "security_policy_admission",
            "required_artifact_provenance": "already has official artifact authority; scan failed/policy admission required",
            "required_scanner_policy_status": "operator must acknowledge scan/security policy",
            "execution_authorization_status": False,
            "training_eligibility_status": False,
            "risk": "hard_policy_admission_required",
            "recommended_next_rung": "PROGRAMBENCH_DOXYGEN_SECURITY_POLICY_ADMISSION_PACKET_REVIEW_LOCK_001",
        },
        {
            "option": "batch001_one_target_artifact_import_scan_policy",
            "current_status": first_target.get(
                "next_unblocker", "supply exact artifact import provenance"
            ),
            "target": first_target.get("instance_id"),
            "required_operator_packet": "artifact_import_provenance_packet",
            "required_artifact_provenance": "exact artifact tar/ref bound to manifest digest and sha256",
            "required_scanner_policy_status": "import gate then scanner admission then scan policy decision",
            "execution_authorization_status": False,
            "training_eligibility_status": False,
            "risk": "moderate_artifact_import_and_scan_chain",
            "recommended_next_rung": "PROGRAMBENCH_BATCH001_ONE_TARGET_ARTIFACT_IMPORT_PACKET_REVIEW_LOCK_001",
        },
        {
            "option": "hold_for_evidence_ledger",
            "current_status": "ledger_ready"
            if ledger_ready and count_ready
            else "ledger_not_ready",
            "required_operator_packet": "none",
            "required_artifact_provenance": "none",
            "required_scanner_policy_status": "none",
            "execution_authorization_status": False,
            "training_eligibility_status": False,
            "risk": "low_if_ledger_not_ready_high_value_if_ready",
            "recommended_next_rung": "DETERMINEX_APPEND_ONLY_EVIDENCE_LEDGER_RECHECK_LOCK_001",
        },
    ]
    if not batch_targets or not ledger_ready or not count_ready:
        status = "PROGRAMBENCH_NEXT_UNBLOCK_RECOMMENDS_HOLD_FOR_LEDGER"
        recommended = options[2]
    else:
        status = "PROGRAMBENCH_NEXT_UNBLOCK_RECOMMENDS_BATCH001_ONE_TARGET"
        recommended = options[1]
    return {
        "status": status,
        "decision_status": "PROGRAMBENCH_NEXT_UNBLOCK_DECISION_WRITTEN",
        "options": options,
        "recommended_path": recommended["option"],
        "reason": (
            "Batch001 one-target path exercises the solved metadata authority with lower policy burden than Doxygen, "
            "while still stopping before import, scan, execution, or training."
            if recommended["option"] == "batch001_one_target_artifact_import_scan_policy"
            else "Hold until ledger/count guards are valid."
        ),
        "next_required_operator_packet": recommended["required_operator_packet"],
        "recommended_next_rung": recommended["recommended_next_rung"],
        "execution_authorized": False,
        "artifact_import_authorized": False,
        "scan_authorized": False,
        "training_eligible": False,
        "training_rows_written": False,
        "programbench_execution_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    record = ProgramBenchNextUnblockDecision(write_record=not args.no_write).run()
    print(json.dumps(record, indent=2, sort_keys=True) if args.json else record["status"])
    return 0 if record["decision_status"] == "PROGRAMBENCH_NEXT_UNBLOCK_DECISION_WRITTEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
