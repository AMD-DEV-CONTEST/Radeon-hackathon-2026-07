"""Tests for the normative domain contract (Todo 2): SM-2 schedule, growth
formula, mastery->grade mapping, and EPERM-safe drain reconciliation logic.

Pure-function tests use app.schedule; drain reconcile is tested against a
minimal state-file + flock simulation.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import schedule  # noqa: E402


class TestScheduleSm2(unittest.TestCase):
    def test_grade_sequence_5_4_5_intervals(self) -> None:
        # first 5 -> 1d, second 4 -> 6d, third 5 -> round(6*ease)
        ease = 2.0
        reps, interval = schedule.compute_interval(ease, 0, 5, 0)
        self.assertEqual((reps, interval), (1, 1))
        reps, interval = schedule.compute_interval(ease, reps, 4, interval)
        self.assertEqual((reps, interval), (2, 6))
        reps, interval = schedule.compute_interval(ease, reps, 5, interval)
        self.assertEqual(reps, 3)
        self.assertEqual(interval, schedule.math.floor(6 * schedule.update_ease(ease, 5) + 0.5))

    def test_grade_2_resets_interval_and_still_updates_ease(self) -> None:
        ease = 2.0
        reps, interval = schedule.compute_interval(ease, 3, 2, 6)
        self.assertEqual((reps, interval), (0, 1))
        # ease still updated for grade<3
        self.assertNotEqual(schedule.update_ease(ease, 2), ease)

    def test_ease_bounds(self) -> None:
        for g in range(0, 6):
            ef = schedule.update_ease(1.0, g)
            self.assertGreaterEqual(ef, schedule.EASE_MIN)
            self.assertLessEqual(ef, schedule.EASE_MAX)

    def test_half_up_rounding(self) -> None:
        # 2.5 -> floor(2.5+0.5)=3 ; 2.4 -> floor(2.9)=2
        self.assertEqual(schedule.math.floor(2.5 + 0.5), 3)
        self.assertEqual(schedule.math.floor(2.4 + 0.5), 2)


class TestGrowth(unittest.TestCase):
    def test_no_units_growth_zero(self) -> None:
        self.assertEqual(schedule.growth_value(0, 0, [], 0), 0)

    def test_all_learned_mastered_no_overdue_is_100(self) -> None:
        # coverage=1, mastery=1 -> floor(100*(0.6+0.4))=100
        self.assertEqual(schedule.growth_value(4, 4, [5, 5, 5, 5], 0), 100)

    def test_overdue_penalty_floors_at_zero(self) -> None:
        g = schedule.growth_value(4, 4, [5, 5, 5, 5], 40)
        self.assertEqual(g, 0)
        g2 = schedule.growth_value(4, 4, [5, 5, 5, 5], 5)
        self.assertLess(g2, 100)


class TestDueTime(unittest.TestCase):
    def test_due_at_asia_shanghai_2300_utc(self) -> None:
        # 2026-08-05T02:00Z = 2026-08-05 10:00 Asia/Shanghai; +1d -> due 2026-08-06 23:00 CST = 15:00Z
        now = datetime(2026, 8, 5, 2, 0, tzinfo=timezone.utc)
        due = schedule.due_at(1, now)
        self.assertEqual(due.hour, 15)  # 23:00 CST == 15:00 UTC
        self.assertEqual(due.day, 6)


class TestMasteryGrade(unittest.TestCase):
    def test_mapping(self) -> None:
        self.assertEqual([schedule.mastery_to_grade(m) for m in [5, 4, 3, 2, 1, 0]],
                         [5, 4, 3, 2, 2, 2])
        self.assertEqual(schedule.override_grade(), 3)


class TestDrainReconcileEperm(unittest.TestCase):
    """EPERM-safe reconcile: 0=live (no undrain), EPERM=fail-closed, ESRCH=absent."""

    def _state(self, state, pid, start):
        return {"state": state, "owner_token": "t", "owner_pid": pid,
                "owner_start_time": start, "started_at": "x"}

    def _reconcile(self, state_file, drain_lock_path, kill_out=None):
        # minimal reimplementation of the contract's kill-based check
        import fcntl
        with open(state_file) as f:
            state = json.load(f)
        pid = state["owner_pid"]
        # flock probe: EX|NB succeeds = owner fd gone
        fd = os.open(drain_lock_path, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            flock_free = True
        except OSError:
            flock_free = False
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        # kill_out: "live"|"eperm"|"esrch" injection (real os.kill only used when None)
        if kill_out is None:
            try:
                os.kill(pid, 0)
                alive, eperm = True, False
            except ProcessLookupError:
                alive, eperm = False, False
            except PermissionError:
                alive, eperm = True, True
        else:
            alive = kill_out == "live"
            eperm = kill_out == "eperm"
        if eperm:
            return "fail_closed"  # EPERM -> do NOT undrain
        if not alive and flock_free:
            return "accepting"
        return state["state"]

    def test_eperm_keeps_state_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            st = os.path.join(td, "drain.state.json")
            lock = os.path.join(td, "drain.lock")
            with open(st, "w") as f:
                json.dump(self._state("drained", 12345, "t1"), f)
            # EPERM (process exists but inaccessible) must NOT undrain
            r = self._reconcile(st, lock, kill_out="eperm")
            self.assertEqual(r, "fail_closed")

    def test_live_owner_keeps_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            st = os.path.join(td, "drain.state.json")
            lock = os.path.join(td, "drain.lock")
            with open(st, "w") as f:
                json.dump(self._state("draining", 12345, "t1"), f)
            r = self._reconcile(st, lock, kill_out="live")
            self.assertEqual(r, "draining")  # live owner: no undrain, state unchanged

    def test_esrch_with_free_flock_undrains(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            st = os.path.join(td, "drain.state.json")
            lock = os.path.join(td, "drain.lock")
            # a pid that surely does not exist (max pid often 4M; use huge but valid kill target)
            dead_pid = 999999
            with open(st, "w") as f:
                json.dump(self._state("drained", dead_pid, "t1"), f)
            r = self._reconcile(st, lock)
            self.assertEqual(r, "accepting")


if __name__ == "__main__":
    unittest.main()
