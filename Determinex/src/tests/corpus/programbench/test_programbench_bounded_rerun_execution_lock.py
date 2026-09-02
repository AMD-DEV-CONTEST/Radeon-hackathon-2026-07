from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.bounded_rerun_gate import (  # noqa: E402
    BoundedRerunGate,
    BoundedRerunStatus,
)
from corpus.programbench.bounded_rerun_record import verify_bounded_rerun_record  # noqa: E402
from corpus.programbench.root_cause_packet import (  # noqa: E402
    make_root_cause_packet,
    sign_packet,
    write_packet,
)


def _artifact(tmp_path: Path, name: str, score: str) -> Path:
    path = tmp_path / "evidence" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"score": score, "tool": "doxygen"}), encoding="utf-8")
    return path


def _packet_path(
    tmp_path: Path,
    *,
    tool: str = "doxygen",
    candidate_id: str = "doxygen_v7",
    stale: bool = False,
    quarantine: bool = False,
) -> Path:
    baseline = _artifact(tmp_path, f"{candidate_id}_baseline", "249/250")
    candidate = _artifact(tmp_path, f"{candidate_id}_candidate", "248/250")
    evidence_inputs: list = [
        baseline.relative_to(tmp_path).as_posix(),
        candidate.relative_to(tmp_path).as_posix(),
    ]
    if quarantine:
        manifest = tmp_path / "manifest.replay_manifest.json"
        manifest.write_text(json.dumps({"quarantine_only": True}), encoding="utf-8")
        evidence_inputs = [{"path": str(manifest), "quarantine_only": True}]
    packet = make_root_cause_packet(
        packet_id=f"{tool}_packet",
        benchmark_name="ProgramBench",
        candidate_id=candidate_id,
        baseline_score="249/250",
        candidate_score="248/250",
        score_delta="-1",
        baseline_artifact_reference={
            "path": baseline.relative_to(tmp_path).as_posix(),
            "score": "249/250",
        },
        candidate_artifact_reference={
            "path": candidate.relative_to(tmp_path).as_posix(),
            "score": "248/250",
            **({"superseded_by": "newer_candidate.json"} if stale else {}),
        },
        failing_tests=["test_default_config_html_output"],
        previously_passing_now_failing_tests=["test_argv0_preserved"],
        regression_diff_summary="candidate regressed argv0 behavior and default config output",
        suspected_patch_location=f"corpus/programbench/per_tool_overrides/{tool}/wrapper.py",
        suspected_failure_class="argv0_alias_regression",
        repair_hypothesis="preserve argv0 and avoid wrapper churn",
        expected_score_recovery="+1",
        rerun_scope={"tool": tool, "candidate_id": candidate_id, "max_attempts": 1},
        evidence_inputs=evidence_inputs,
        created_at="2026-05-27T00:00:00+00:00",
    )
    if quarantine:
        packet = sign_packet(packet)
    return write_packet(packet, tmp_path / "packets")


def _gate(tmp_path: Path) -> BoundedRerunGate:
    return BoundedRerunGate(root=tmp_path, output_dir=tmp_path / "bounded")


def _target(tool: str = "doxygen", candidate_id: str = "doxygen_v7") -> dict:
    return {"tool": tool, "candidate_id": candidate_id}


def test_authorized_doxygen_packet_permits_exact_scope(tmp_path):
    path = _packet_path(tmp_path)

    decision = _gate(tmp_path).authorize(path, _target())

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_AUTHORIZED.value
    assert decision.rerun_scope["tool"] == "doxygen"
    record = json.loads(Path(decision.record_path).read_text(encoding="utf-8"))
    assert verify_bounded_rerun_record(record)


def test_scope_mismatch_blocks(tmp_path):
    path = _packet_path(tmp_path)

    decision = _gate(tmp_path).authorize(path, _target(tool="richgo"))

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH.value
    assert any(reason.startswith("tool_mismatch") for reason in decision.reasons)


def test_missing_packet_blocks(tmp_path):
    decision = _gate(tmp_path).authorize(tmp_path / "missing.json", _target())

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_NO_PACKET.value


def test_stale_packet_blocks(tmp_path):
    path = _packet_path(tmp_path, stale=True)

    decision = _gate(tmp_path).authorize(path, _target())

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_STALE_PACKET.value


def test_attempt_count_above_max_blocks(tmp_path):
    path = _packet_path(tmp_path)

    decision = _gate(tmp_path).authorize(path, _target(), attempt_index=2)

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT.value


def test_quarantine_only_replay_manifest_blocks(tmp_path):
    path = _packet_path(tmp_path, quarantine=True)

    decision = _gate(tmp_path).authorize(path, _target())

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_QUARANTINE_ONLY.value


def test_richgo_cannot_run_from_doxygen_packet(tmp_path):
    path = _packet_path(tmp_path, tool="doxygen", candidate_id="doxygen_v7")

    decision = _gate(tmp_path).authorize(path, _target(tool="richgo", candidate_id="richgo_v7"))

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH.value


def test_authorized_packet_produces_deterministic_authorization_record(tmp_path):
    path = _packet_path(tmp_path)

    decision = _gate(tmp_path).authorize(path, _target())

    record = json.loads(Path(decision.record_path).read_text(encoding="utf-8"))
    assert record["record_type"] == "bounded_rerun_authorization"
    assert record["status"] == BoundedRerunStatus.BOUNDED_RERUN_AUTHORIZED.value
    assert record["target"] == _target()


def test_mock_rerun_outcome_produces_signed_outcome_record(tmp_path):
    path = _packet_path(tmp_path)

    decision = _gate(tmp_path).execute_with_mock(
        path,
        _target(),
        lambda _ctx: {
            "baseline_score": "249/250",
            "candidate_score": "250/250",
            "verifier_result": "pass",
        },
    )

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_OUTCOME_RECORDED.value
    record = json.loads(Path(decision.record_path).read_text(encoding="utf-8"))
    assert verify_bounded_rerun_record(record)
    assert record["outcome"]["training_eligible"] is False
    assert record["outcome"]["record_status"] == "active_eval_evidence"


def test_no_unauthorized_execution_path_exists(tmp_path):
    path = _packet_path(tmp_path)
    calls = {"executed": 0}

    def executor(_ctx):
        calls["executed"] += 1
        return {"verifier_result": "pass"}

    decision = _gate(tmp_path).execute_with_mock(path, _target(tool="richgo"), executor)

    assert decision.status == BoundedRerunStatus.BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH.value
    assert calls["executed"] == 0
