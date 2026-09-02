"""The first-E2E rerun evidence must be derived from a session, not asserted by an operator.

FOUND 2026-07-31. `_first_e2e_gate` passes the release when
`rerun_after_builder_health_latest.json` reports PASSED with all steps complete. A repo-wide search
for a writer found only readers -- the gates module and its tests. The file was maintained by hand,
so the four fields the gate checks were an operator's transcription of a console, and a mistake in
the operator's favour looks exactly like a pass. That is the same shape as every other defect this
release pass has turned up: a check whose input a human types.

`capture_first_e2e_rerun.py` now computes those fields from the session's committed manifest, and
computes `status` from the steps rather than accepting it, so the write-up of a session that did
not finish cannot say it did.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.release import capture_first_e2e_rerun as C  # noqa: E402

STAMP = "2026-07-31T00:00:00Z"


def _step(step_id: int, *, status: str = "complete", oracle: str = "pass", **extra):
    base = {"id": step_id, "status": status, "compiler_result": oracle, "retries": 0}
    base.update(extra)
    return base


def _manifest(steps, **extra):
    base = {
        "session_id": "s-1",
        "lang": "rust",
        "api_cost_usd": 0.0,
        "session_budget_usd": 2.0,
        "correctness_test_harness": "",
        "steps": steps,
        "pending_escalations": [],
    }
    base.update(extra)
    return base


class TestStatusIsComputedNotAccepted:
    def test_all_steps_verified_passes(self):
        rec = C.build_record(_manifest([_step(1), _step(2)]), generated_at_utc=STAMP)
        assert rec["status"] == C.PASSED
        assert rec["observed_result"]["steps_complete"] == 2
        assert rec["observed_result"]["steps_total"] == 2
        assert rec["observed_result"]["steps_failed"] == 0

    def test_a_failed_step_cannot_be_written_up_as_passed(self):
        rec = C.build_record(
            _manifest([_step(1), _step(2, status="failed", oracle="fail")]), generated_at_utc=STAMP
        )
        assert rec["status"] == C.FAILED
        assert rec["observed_result"]["steps_failed"] == 1

    def test_a_status_field_in_the_manifest_is_ignored(self):
        """Even if a session claims success, the steps decide."""
        rec = C.build_record(
            _manifest([_step(1, status="failed", oracle="fail")], status="FIRST_E2E_RERUN_PASSED"),
            generated_at_utc=STAMP,
        )
        assert rec["status"] == C.FAILED

    def test_complete_without_a_passing_oracle_is_not_counted_as_verified(self):
        """The exact overclaim to avoid: a step the session called done that nothing verified."""
        rec = C.build_record(_manifest([_step(1), _step(2, oracle="")]), generated_at_utc=STAMP)
        assert rec["status"] == C.FAILED
        assert rec["observed_result"]["steps_complete"] == 1
        assert rec["observed_result"]["steps_pending"] == 1

    def test_zero_steps_is_not_a_pass(self):
        """An empty DAG completes every step it has. That must not read as success."""
        rec = C.build_record(_manifest([]), generated_at_utc=STAMP)
        assert rec["status"] == C.FAILED
        assert rec["observed_result"]["steps_total"] == 0

    def test_an_exhausted_budget_is_not_a_pass(self):
        rec = C.build_record(_manifest([_step(1)], budget_exhausted=True), generated_at_utc=STAMP)
        assert rec["status"] == C.FAILED

    def test_a_pending_escalation_is_not_a_pass(self):
        rec = C.build_record(
            _manifest([_step(1)], pending_escalations=[{"step": 1}]), generated_at_utc=STAMP
        )
        assert rec["status"] == C.FAILED
        assert any("escalation" in q for q in rec["qualifications"])


class TestTheClaimStaysBounded:
    def test_a_missing_harness_is_disclosed_not_smoothed_over(self):
        rec = C.build_record(_manifest([_step(1)]), generated_at_utc=STAMP)
        joined = " ".join(rec["qualifications"])
        assert "no test harness" in joined
        assert "compile-verified workflow, not a behaviour-verified one" in joined

    def test_correctness_result_is_reported_verbatim_including_empty(self):
        rec = C.build_record(_manifest([_step(1, correctness_result="")]), generated_at_utc=STAMP)
        assert rec["per_step"][0]["correctness_result"] == ""

    def test_it_never_grants_release_authority(self):
        rec = C.build_record(_manifest([_step(1), _step(2)]), generated_at_utc=STAMP)
        assert rec["release_ready"] is False
        assert rec["authority_granted"] is False
        assert any("does not by itself authorise release" in q for q in rec["qualifications"])

    def test_it_records_where_it_came_from(self):
        rec = C.build_record(_manifest([_step(1)]), generated_at_utc=STAMP)
        assert rec["derived_from"] == "sessions/s-1/manifest.json", (
            "the evidence must name the session it was derived from so it can be re-checked"
        )


class TestItRefusesWhatItCannotRead:
    def test_a_missing_session_is_refused(self, tmp_path):
        with pytest.raises(C.CaptureError, match="no session manifest"):
            C.load_manifest(tmp_path, "nope")

    def test_a_mismatched_session_id_is_refused(self, tmp_path):
        d = tmp_path / "sessions" / "asked-for"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(
            json.dumps({"session_id": "something-else"}), encoding="utf-8"
        )
        with pytest.raises(C.CaptureError, match="does not match requested"):
            C.load_manifest(tmp_path, "asked-for")

    def test_unreadable_json_is_refused(self, tmp_path):
        d = tmp_path / "sessions" / "s"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text("{ not json", encoding="utf-8")
        with pytest.raises(C.CaptureError, match="unreadable"):
            C.load_manifest(tmp_path, "s")

    def test_the_cli_exits_nonzero_and_writes_nothing_when_refusing(self, tmp_path, capsys):
        rc = C.main(["--session", "absent", "--root", str(tmp_path)])
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().err
        assert not list(tmp_path.rglob("rerun_after_builder_health_latest.json"))


class TestTheGateAcceptsWhatThisWrites:
    """The generator and the gate must agree, or the evidence is useless."""

    def _write(self, root: Path, steps) -> Path:
        d = root / "sessions" / "s-1"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps(_manifest(steps)), encoding="utf-8")
        rc = C.main(["--session", "s-1", "--root", str(root)])
        out = (
            root
            / "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json"
        )
        assert out.is_file()
        return out, rc

    def test_a_passing_capture_satisfies_the_gates_own_predicate(self, tmp_path):
        from scripts.release import determinex_release_gates as G

        out, rc = self._write(tmp_path, [_step(1), _step(2)])
        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        observed = data["observed_result"]
        assert G._is_passing_status(data["status"])
        assert observed["steps_total"] > 0
        assert observed["steps_complete"] == observed["steps_total"]
        assert observed["steps_failed"] == 0

    def test_a_failing_capture_does_not(self, tmp_path):
        from scripts.release import determinex_release_gates as G

        out, rc = self._write(tmp_path, [_step(1, status="failed", oracle="fail")])
        assert rc == 1, "a failed session must exit nonzero so a script cannot ignore it"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert not G._is_passing_status(data["status"])


def test_the_shipped_evidence_is_derived_from_a_real_session():
    """Guards the regression directly: hand-written evidence has no `derived_from` session."""
    path = (
        REPO_ROOT
        / "assurance/evidence/first_end_to_end_user_workflow"
        / "rerun_after_builder_health_latest.json"
    )
    if not path.is_file():
        pytest.skip("no first-E2E rerun evidence in this checkout")
    data = json.loads(path.read_text(encoding="utf-8"))
    derived = str(data.get("derived_from") or "")
    assert derived.startswith("sessions/"), (
        "the shipped evidence was not produced by capture_first_e2e_rerun.py -- if it was "
        "hand-edited, the gate is trusting a typed number again"
    )
    session_id = str(data.get("session_id") or "")
    assert session_id and session_id in derived
    manifest = REPO_ROOT / derived
    if not manifest.is_file():
        pytest.skip(f"session {session_id} manifest is not retained in this checkout")
    # Recompute from the manifest and require the evidence to still match it.
    recomputed = C.build_record(
        json.loads(manifest.read_text(encoding="utf-8")),
        generated_at_utc=str(data.get("generated_at_utc") or STAMP),
    )
    assert recomputed["status"] == data["status"], (
        "the evidence disagrees with the session it claims to come from"
    )
    assert (
        recomputed["observed_result"]["steps_complete"] == data["observed_result"]["steps_complete"]
    )
    assert recomputed["observed_result"]["steps_total"] == data["observed_result"]["steps_total"]
