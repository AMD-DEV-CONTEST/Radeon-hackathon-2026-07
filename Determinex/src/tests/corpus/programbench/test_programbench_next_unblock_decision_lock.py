from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from corpus.programbench.programbench_next_unblock_decision import (  # noqa: E402
    ProgramBenchNextUnblockDecision,
    decide_next_programbench_unblock,
)
from corpus.programbench.programbench_next_unblock_decision_record import (
    verify_programbench_next_unblock_decision_record,  # noqa: E402
)

LOCK_PATH = ROOT / "locks" / "sentinel" / "PROGRAMBENCH_NEXT_UNBLOCK_DECISION_LOCK_001.json"
EVIDENCE_INDEX = ROOT / "assurance" / "evidence" / "evidence_index.json"


def test_programbench_next_unblock_recommends_batch001_one_target() -> None:
    record = ProgramBenchNextUnblockDecision(write_record=False).run()

    assert record["status"] == "PROGRAMBENCH_NEXT_UNBLOCK_RECOMMENDS_BATCH001_ONE_TARGET"
    assert verify_programbench_next_unblock_decision_record(record)
    assert record["recommended_path"] == "batch001_one_target_artifact_import_scan_policy"
    assert record["next_required_operator_packet"] == "artifact_import_provenance_packet"


def test_programbench_next_unblock_keeps_authority_closed() -> None:
    record = ProgramBenchNextUnblockDecision(write_record=False).run()

    assert record["execution_authorized"] is False
    assert record["artifact_import_authorized"] is False
    assert record["scan_authorized"] is False
    assert record["training_eligible"] is False
    assert record["training_rows_written"] is False
    assert record["programbench_execution_performed"] is False


def test_programbench_next_unblock_compares_required_options() -> None:
    record = ProgramBenchNextUnblockDecision(write_record=False).run()
    options = {option["option"]: option for option in record["options"]}

    assert "doxygen_security_policy_admission" in options
    assert "batch001_one_target_artifact_import_scan_policy" in options
    assert "hold_for_evidence_ledger" in options
    assert (
        options["doxygen_security_policy_admission"]["required_operator_packet"]
        == "security_policy_admission"
    )


def test_programbench_next_unblock_holds_when_ledger_not_ready() -> None:
    result = decide_next_programbench_unblock(
        doxygen={},
        per_target={
            "batch001_targets": [
                {"instance_id": "x", "next_unblocker": "supply exact artifact import provenance"}
            ]
        },
        import_scan={},
        ledger={"chain_valid": False, "mutation_detected": False},
        count_guard={"status": "EVIDENCE_COUNT_DRIFT_GUARD_PASSED"},
    )

    assert result["status"] == "PROGRAMBENCH_NEXT_UNBLOCK_RECOMMENDS_HOLD_FOR_LEDGER"


def test_programbench_next_unblock_lock_and_index_entries_exist() -> None:
    assert LOCK_PATH.is_file()
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["lock_id"] == "PROGRAMBENCH_NEXT_UNBLOCK_DECISION_LOCK_001"
    assert lock["status"] == "PROGRAMBENCH_NEXT_UNBLOCK_RECOMMENDS_BATCH001_ONE_TARGET"

    index = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {entry.get("evidence_id") for entry in index.get("entries", [])}
    assert "PROGRAMBENCH_NEXT_UNBLOCK_DECISION_LOCK_001" in ids
