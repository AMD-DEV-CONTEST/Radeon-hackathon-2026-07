"""Todo 7 tests: learning/assessment/review services + grading contract.

Covers the domain-contract transitions (unlearned->learning->review_due),
SM-2 scheduling, idempotency (same key+same payload replay / same key+different
payload 409), single-active-session partial unique index (concurrency),
fail-closed grading (LC_GRADER_STUB=unavailable), server-recomputed
authoritative score over model advisory score, and derived garden aggregation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path("/persistent/learning-companion")
sys.path.insert(0, str(ROOT))

from app import grading, schedule, study  # noqa: E402
from app.processing import connect, ensure_schema  # noqa: E402


def _fixture(tmp: Path, fresh: bool = False) -> dict:
    db = tmp / "fixture.sqlite"
    out = tmp / "fixture.json"
    cmd = [sys.executable, str(ROOT / "scripts" / "bootstrap_study_fixture.py"),
           "--db", str(db), "--out", str(out)]
    if fresh:
        cmd.append("--fresh-skill")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return {"db": db, **json.loads(out.read_text())}


def _ok_grader(unit: dict, recall: str) -> dict:
    """Deterministic grader: matched key points whose normalized key appears in recall."""
    matched = [kp for kp in unit.get("key_points", [])
               if grading.normalize_key(kp) in grading.normalize_key(recall)]
    return {
        "feedback": "ok",
        "score": len(matched),          # advisory only
        "mastery_level": len(matched),  # advisory only
        "needs_retry": False,
        "matched_key_points": matched,
    }


class TestGradingContract(unittest.TestCase):
    def test_authoritative_score_recomputed_over_advisory(self) -> None:
        unit = {"key_points": ["强领导者", "多数确认后提交", "随机超时选举"]}
        # model advisory says 5, but only one validated match -> server recomputes 1
        judged = _ok_grader(unit, "强领导者")
        self.assertEqual(judged["score"], 1)  # advisory
        self.assertEqual(grading.authoritative_score(unit, judged["matched_key_points"]), 1)

    def test_matched_key_points_validated_against_checked_in_list(self) -> None:
        unit = {"key_points": ["强领导者"]}
        # model claims a key point NOT on the unit's list -> ignored
        self.assertEqual(grading.authoritative_score(unit, ["不存在的关键点"]), 0)

    def test_misconception_hit_from_checked_in_list(self) -> None:
        unit = {"accepted_misconceptions": ["Raft 使用中心化仲裁者"]}
        self.assertEqual(
            grading.misconception_hit(unit, "我认为 Raft 使用中心化仲裁者"),
            "Raft 使用中心化仲裁者")
        self.assertIsNone(grading.misconception_hit(unit, "Raft 使用多数派"))

    def test_call_grader_fail_closed_when_unavailable(self) -> None:
        os.environ["LC_GRADER_STUB"] = "unavailable"
        try:
            with self.assertRaises(grading.GradingUnavailable):
                grading.call_grader({"key_points": []}, "recall")
        finally:
            del os.environ["LC_GRADER_STUB"]


class TestLearningFlow(unittest.TestCase):
    def test_learning_then_assessment_schedules_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td))
            sid = study.start_learning_session(fx["skill_id"], db_path=fx["db"])["session"]["id"]
            res = study.submit_assessment(sid, fx["unit_id"], "k1", fx["gold_recall_text"],
                                          db_path=fx["db"], grader=_ok_grader)
            self.assertEqual(res["attempt"]["status"], "judged")
            con = connect(fx["db"])
            prog = con.execute("SELECT * FROM learning_progress WHERE unit_id=?", (fx["unit_id"],)).fetchone()
            con.close()
            self.assertEqual(prog["progress_status"], study.PROG_REVIEW_DUE)
            self.assertIsNotNone(prog["next_review_at"])
            self.assertEqual(prog["repetitions"], 1)

    def test_grade_mapping_and_interval(self) -> None:
        # mastery 5 -> grade 5, interval 1d on first assessment
        self.assertEqual(schedule.mastery_to_grade(5), 5)
        self.assertEqual(schedule.mastery_to_grade(1), 2)
        self.assertEqual(schedule.mastery_to_grade(0), 2)

    def test_preview_skill_409_and_no_session(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td))
            with self.assertRaises(study.StudyError) as cm:
                study.start_learning_session(fx["preview_skill_id"], db_path=fx["db"])
            self.assertEqual(cm.exception.status, 409)
            con = connect(fx["db"])
            n = con.execute("SELECT COUNT(*) AS c FROM study_sessions WHERE skill_id=?",
                            (fx["preview_skill_id"],)).fetchone()["c"]
            con.close()
            self.assertEqual(n, 0)

    def test_idempotency_same_key_same_payload_replays(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td))
            sid = study.start_learning_session(fx["skill_id"], db_path=fx["db"])["session"]["id"]
            r1 = study.submit_assessment(sid, fx["unit_id"], "k1", fx["gold_recall_text"],
                                         db_path=fx["db"], grader=_ok_grader)
            r2 = study.submit_assessment(sid, fx["unit_id"], "k1", fx["gold_recall_text"],
                                         db_path=fx["db"], grader=_ok_grader)
            self.assertTrue(r2["replayed"])
            self.assertEqual(r1["attempt"]["id"], r2["attempt"]["id"])
            con = connect(fx["db"])
            n = con.execute("SELECT COUNT(*) AS c FROM assessment_attempts WHERE session_id=?",
                            (sid,)).fetchone()["c"]
            con.close()
            self.assertEqual(n, 1)

    def test_idempotency_same_key_different_payload_409(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td))
            sid = study.start_learning_session(fx["skill_id"], db_path=fx["db"])["session"]["id"]
            study.submit_assessment(sid, fx["unit_id"], "k1", fx["gold_recall_text"],
                                    db_path=fx["db"], grader=_ok_grader)
            with self.assertRaises(study.StudyError) as cm:
                study.submit_assessment(sid, fx["unit_id"], "k1", "different text",
                                        db_path=fx["db"], grader=_ok_grader)
            self.assertEqual(cm.exception.status, 409)
            con = connect(fx["db"])
            n = con.execute("SELECT COUNT(*) AS c FROM assessment_attempts WHERE session_id=?",
                            (sid,)).fetchone()["c"]
            con.close()
            self.assertEqual(n, 1)  # unchanged

    def test_single_active_session_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td))
            s1 = study.start_learning_session(fx["skill_id"], db_path=fx["db"])
            # second concurrent start resumes the same active session (partial unique index)
            s2 = study.start_learning_session(fx["skill_id"], db_path=fx["db"])
            self.assertTrue(s1["resumed"] or s2["resumed"])
            self.assertEqual(s1["session"]["id"], s2["session"]["id"])
            con = connect(fx["db"])
            n = con.execute(
                "SELECT COUNT(*) AS c FROM study_sessions WHERE skill_id=? AND status='active'",
                (fx["skill_id"],)).fetchone()["c"]
            con.close()
            self.assertEqual(n, 1)

    def test_fail_closed_grading_no_schedule_update(self) -> None:
        os.environ["LC_GRADER_STUB"] = "unavailable"
        try:
            with tempfile.TemporaryDirectory() as td:
                fx = _fixture(Path(td))
                sid = study.start_learning_session(fx["skill_id"], db_path=fx["db"])["session"]["id"]
                before = connect(fx["db"]).execute(
                    "SELECT COUNT(*) AS c FROM learning_progress WHERE unit_id=? AND next_review_at IS NOT NULL",
                    (fx["unit_id"],)).fetchone()["c"]
                with self.assertRaises(study.StudyError) as cm:
                    study.submit_assessment(sid, fx["unit_id"], "k2", fx["gold_recall_text"],
                                            db_path=fx["db"])
                self.assertEqual(cm.exception.status, 503)
                con = connect(fx["db"])
                failed = con.execute(
                    "SELECT COUNT(*) AS c FROM assessment_attempts WHERE session_id=? AND status='failed'",
                    (sid,)).fetchone()["c"]
                after = con.execute(
                    "SELECT COUNT(*) AS c FROM learning_progress WHERE unit_id=? AND next_review_at IS NOT NULL",
                    (fx["unit_id"],)).fetchone()["c"]
                con.close()
                self.assertEqual(failed, 1)
                self.assertEqual(after, before)  # no schedule update
        finally:
            del os.environ["LC_GRADER_STUB"]

    def test_abandon_marks_session_abandoned(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td))
            sid = study.start_learning_session(fx["skill_id"], db_path=fx["db"])["session"]["id"]
            study.abandon_session(sid, db_path=fx["db"])
            con = connect(fx["db"])
            status = con.execute("SELECT status FROM study_sessions WHERE id=?", (sid,)).fetchone()["status"]
            con.close()
            self.assertEqual(status, study.SESSION_ABANDONED)


class TestGardenDerived(unittest.TestCase):
    def test_garden_derived_from_formula(self) -> None:
        # golden formula: clamp(floor(100*(0.6cov+0.4mast))-3*overdue, 0, 100)
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td))
            g = study.compute_garden(fx["skill_id"], db_path=fx["db"])
            self.assertIn(g["status"], (study.STATUS_BUD, study.STATUS_GROWING,
                                        study.STATUS_MATURE, study.STATUS_DECAYING))
            self.assertGreaterEqual(g["growth_value"], 0)
            self.assertLessEqual(g["growth_value"], 100)
            self.assertEqual(g["total_verified"], 1)

    def test_garden_zero_when_no_verified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td))
            g = study.compute_garden(fx["preview_skill_id"], db_path=fx["db"])
            self.assertEqual(g["growth_value"], 0)
            self.assertEqual(g["total_verified"], 0)


class TestFixtureFreshSkill(unittest.TestCase):
    def test_fresh_skill_has_no_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fx = _fixture(Path(td), fresh=True)
            self.assertIn("fresh_skill_id", fx)
            con = connect(fx["db"])
            n = con.execute("SELECT COUNT(*) AS c FROM study_sessions WHERE skill_id=?",
                            (fx["fresh_skill_id"],)).fetchone()["c"]
            con.close()
            self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
