from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.real_bounded_rerun import (  # noqa: E402
    RealBoundedRerun,
    RealBoundedRerunConfig,
    RealBoundedRerunStatus,
)
from corpus.programbench.real_bounded_rerun_record import verify_real_rerun_record  # noqa: E402
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
    max_attempts: int = 1,
    quarantine: bool = False,
    tamper: bool = False,
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
        },
        failing_tests=["test_default_config_html_output"],
        previously_passing_now_failing_tests=["test_argv0_preserved"],
        regression_diff_summary="candidate regressed argv0 behavior and default config output",
        suspected_patch_location=f"corpus/programbench/per_tool_overrides/{tool}/wrapper.py",
        suspected_failure_class="argv0_alias_regression",
        repair_hypothesis="preserve argv0 and avoid wrapper churn",
        expected_score_recovery="+1",
        rerun_scope={"tool": tool, "candidate_id": candidate_id, "max_attempts": max_attempts},
        evidence_inputs=evidence_inputs,
        created_at="2026-05-27T00:00:00+00:00",
    )
    if quarantine:
        packet = sign_packet(packet)
    if tamper:
        packet["repair_hypothesis"] = "tampered"
    return (
        write_packet(packet, tmp_path / "packets")
        if not tamper
        else _write_unsigned(packet, tmp_path / "packets")
    )


def _write_unsigned(packet: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{packet['packet_id']}.json"
    path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _runner(tmp_path: Path, executor):
    return RealBoundedRerun(
        RealBoundedRerunConfig(
            root=tmp_path,
            output_dir=tmp_path / "real",
            executor=executor,
        )
    )


def _target(tool: str = "doxygen", candidate_id: str = "doxygen_v7") -> dict:
    return {"tool": tool, "candidate_id": candidate_id}


def test_invalid_packet_blocks_live_rerun(tmp_path):
    calls = {"n": 0}
    result = _runner(tmp_path, lambda _ctx: calls.__setitem__("n", calls["n"] + 1)).run(
        _packet_path(tmp_path, tamper=True),
        _target(),
    )

    assert (
        result["record"]["status"]
        == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_PACKET_INVALID.value
    )
    assert calls["n"] == 0


def test_scope_mismatch_blocks_live_rerun(tmp_path):
    result = _runner(tmp_path, lambda _ctx: {"decision": "accept"}).run(
        _packet_path(tmp_path),
        _target(tool="richgo"),
    )

    assert (
        result["record"]["status"]
        == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH.value
    )


def test_attempt_limit_blocks_live_rerun(tmp_path):
    runner = RealBoundedRerun(
        RealBoundedRerunConfig(
            root=tmp_path,
            output_dir=tmp_path / "real",
            attempt_index=2,
            executor=lambda _ctx: {"decision": "accept"},
        )
    )

    result = runner.run(_packet_path(tmp_path), _target())

    assert (
        result["record"]["status"]
        == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_ATTEMPT_LIMIT.value
    )


def test_richgo_cannot_be_triggered_by_doxygen_packet(tmp_path):
    calls = {"n": 0}

    def executor(_ctx):
        calls["n"] += 1
        return {"decision": "accept"}

    result = _runner(tmp_path, executor).run(
        _packet_path(tmp_path, tool="doxygen"), _target(tool="richgo", candidate_id="richgo_v7")
    )

    assert (
        result["record"]["status"]
        == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_SCOPE_MISMATCH.value
    )
    assert calls["n"] == 0


def test_mock_live_run_records_signed_active_eval_evidence(tmp_path):
    result = _runner(
        tmp_path,
        lambda _ctx: {"decision": "accept", "passed_delta": 1, "verifier_result": "pass"},
    ).run(_packet_path(tmp_path), _target())

    record = result["record"]
    assert verify_real_rerun_record(record)
    assert record["record_status"] == "active_eval_evidence"
    assert record["training_eligible"] is False


def test_improved_result_not_automatically_training_eligible(tmp_path):
    result = _runner(tmp_path, lambda _ctx: {"decision": "accept", "passed_delta": 1}).run(
        _packet_path(tmp_path), _target()
    )

    assert result["record"]["status"] == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_IMPROVED.value
    assert result["record"]["training_eligible"] is False


def test_rejected_result_is_signed_evidence(tmp_path):
    result = _runner(tmp_path, lambda _ctx: {"decision": "reject", "passed_delta": 0}).run(
        _packet_path(tmp_path), _target()
    )

    assert result["record"]["status"] == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_REJECTED.value
    assert verify_real_rerun_record(result["record"])


def test_infra_failure_is_signed_as_infra_failure(tmp_path):
    result = _runner(
        tmp_path, lambda _ctx: {"status": "infra_failure", "error": "docker_unavailable"}
    ).run(_packet_path(tmp_path), _target())

    assert (
        result["record"]["status"] == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_INFRA_FAILURE.value
    )
    assert verify_real_rerun_record(result["record"])


def test_preflight_image_missing_output_is_infra_failure(tmp_path):
    result = _runner(
        tmp_path,
        lambda _ctx: {
            "status": "executed",
            "stdout": "preflight failed before official eval: FAIL image missing: programbench/doxygen:task_cleanroom",
            "gate_result": {"decision": "reject", "delta": {"passed": -1}},
        },
    ).run(_packet_path(tmp_path), _target())

    assert (
        result["record"]["status"] == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_INFRA_FAILURE.value
    )
    assert verify_real_rerun_record(result["record"])


def test_no_retry_occurs_after_failure(tmp_path):
    calls = {"n": 0}

    def executor(_ctx):
        calls["n"] += 1
        return {"status": "infra_failure", "error": "first_failure"}

    _runner(tmp_path, executor).run(_packet_path(tmp_path), _target())

    assert calls["n"] == 1


def test_quarantine_only_packet_does_not_execute(tmp_path):
    calls = {"n": 0}
    result = _runner(tmp_path, lambda _ctx: calls.__setitem__("n", calls["n"] + 1)).run(
        _packet_path(tmp_path, quarantine=True),
        _target(),
    )

    assert (
        result["record"]["status"]
        == RealBoundedRerunStatus.REAL_BOUNDED_RERUN_BLOCKED_PACKET_INVALID.value
    )
    assert calls["n"] == 0
