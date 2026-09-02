from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.root_cause_packet import (  # noqa: E402
    make_root_cause_packet,
    sign_packet,
    write_packet,
)
from corpus.programbench.root_cause_packet_gate import RootCausePacketGate  # noqa: E402
from corpus.programbench.root_cause_packet_schema import RootCausePacketStatus  # noqa: E402


def _artifact(tmp_path: Path, name: str, score: str) -> Path:
    path = tmp_path / "evidence" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"score": score, "tool": "doxygen"}), encoding="utf-8")
    return path


def _rel(tmp_path: Path, path: Path) -> str:
    return path.relative_to(tmp_path).as_posix()


def _packet(tmp_path: Path, **extra) -> dict:
    baseline = _artifact(tmp_path, "baseline", "249/250")
    candidate = _artifact(tmp_path, "candidate", "248/250")
    packet = make_root_cause_packet(
        packet_id="doxygen_root_cause_001",
        benchmark_name="ProgramBench",
        candidate_id="doxygen_v7",
        baseline_score="249/250",
        candidate_score="248/250",
        score_delta="-1",
        baseline_artifact_reference={"path": _rel(tmp_path, baseline), "score": "249/250"},
        candidate_artifact_reference={"path": _rel(tmp_path, candidate), "score": "248/250"},
        failing_tests=["test_default_config_html_output"],
        previously_passing_now_failing_tests=["test_argv0_preserved"],
        regression_diff_summary="candidate regressed argv0 behavior and default config output",
        suspected_patch_location="corpus/programbench/per_tool_overrides/doxygen/wrapper.py",
        suspected_failure_class="argv0_alias_regression",
        repair_hypothesis="preserve argv0 and avoid default config directory rewrite",
        expected_score_recovery="+1",
        rerun_scope={"tool": "doxygen", "candidate_id": "doxygen_v7", "max_attempts": 1},
        evidence_inputs=[_rel(tmp_path, baseline), _rel(tmp_path, candidate)],
        created_at="2026-05-27T00:00:00+00:00",
    )
    packet.update(extra)
    if "packet_signature" not in extra:
        packet = sign_packet(packet)
    return packet


def test_valid_packet_becomes_ready(tmp_path):
    result = RootCausePacketGate(root=tmp_path).validate_packet(_packet(tmp_path))

    assert result.status == RootCausePacketStatus.ROOT_CAUSE_PACKET_READY.value
    assert result.rerun_scope["tool"] == "doxygen"


def test_missing_failing_tests_blocks_authorization(tmp_path):
    packet = _packet(tmp_path)
    packet["failing_tests"] = []
    packet = sign_packet(packet)

    result = RootCausePacketGate(root=tmp_path).validate_packet(packet)

    assert result.status == RootCausePacketStatus.ROOT_CAUSE_PACKET_INCOMPLETE.value
    assert "missing:failing_tests" in result.reasons


def test_missing_suspected_patch_location_blocks_authorization(tmp_path):
    packet = _packet(tmp_path)
    packet["suspected_patch_location"] = ""
    packet = sign_packet(packet)

    result = RootCausePacketGate(root=tmp_path).validate_packet(packet)

    assert result.status == RootCausePacketStatus.ROOT_CAUSE_PACKET_INCOMPLETE.value
    assert "missing:suspected_patch_location" in result.reasons


def test_missing_repair_hypothesis_blocks_authorization(tmp_path):
    packet = _packet(tmp_path)
    packet["repair_hypothesis"] = ""
    packet = sign_packet(packet)

    result = RootCausePacketGate(root=tmp_path).validate_packet(packet)

    assert result.status == RootCausePacketStatus.ROOT_CAUSE_PACKET_INCOMPLETE.value
    assert "missing:repair_hypothesis" in result.reasons


def test_conflicting_baseline_candidate_references_produce_conflict(tmp_path):
    packet = _packet(tmp_path)
    packet["candidate_artifact_reference"]["score"] = "249/250"
    packet = sign_packet(packet)

    result = RootCausePacketGate(root=tmp_path).validate_packet(packet)

    assert result.status == RootCausePacketStatus.ROOT_CAUSE_PACKET_CONFLICT.value
    assert any(reason.startswith("score_mismatch") for reason in result.reasons)


def test_stale_packet_blocks_rerun(tmp_path):
    packet = _packet(tmp_path)
    packet["candidate_artifact_reference"]["superseded_by"] = "candidate_v8.json"
    packet = sign_packet(packet)
    path = write_packet(packet, tmp_path / "packets")

    result = RootCausePacketGate(root=tmp_path).authorize_rerun(path)

    assert result.status == RootCausePacketStatus.RERUN_BLOCKED_STALE_PACKET.value
    assert result.packet_status == RootCausePacketStatus.ROOT_CAUSE_PACKET_STALE.value


def test_no_packet_produces_blocked_no_packet(tmp_path):
    result = RootCausePacketGate(root=tmp_path).authorize_rerun(tmp_path / "missing.json")

    assert result.status == RootCausePacketStatus.RERUN_BLOCKED_NO_PACKET.value


def test_ready_packet_authorizes_only_bounded_scope(tmp_path):
    path = write_packet(_packet(tmp_path), tmp_path / "packets")

    result = RootCausePacketGate(root=tmp_path).authorize_rerun(path)

    assert result.status == RootCausePacketStatus.RERUN_AUTHORIZED.value
    assert result.rerun_scope == {
        "tool": "doxygen",
        "candidate_id": "doxygen_v7",
        "max_attempts": 1,
    }


def test_quarantine_only_replay_manifest_cannot_authorize_execution(tmp_path):
    manifest = tmp_path / "manifest.replay_manifest.json"
    manifest.write_text(json.dumps({"quarantine_only": True}), encoding="utf-8")
    packet = _packet(tmp_path)
    packet["evidence_inputs"] = [{"path": str(manifest), "quarantine_only": True}]
    packet = sign_packet(packet)

    result = RootCausePacketGate(root=tmp_path).validate_packet(packet)

    assert result.status == RootCausePacketStatus.ROOT_CAUSE_PACKET_REJECTED.value
    assert "quarantine_only_replay_manifest_cannot_authorize_rerun" in result.reasons


def test_invalid_signature_rejected(tmp_path):
    packet = _packet(tmp_path)
    packet["repair_hypothesis"] = "tampered after signing"

    result = RootCausePacketGate(root=tmp_path).validate_packet(packet)

    assert result.status == RootCausePacketStatus.ROOT_CAUSE_PACKET_REJECTED.value
    assert result.reasons == ["packet_signature_invalid"]
