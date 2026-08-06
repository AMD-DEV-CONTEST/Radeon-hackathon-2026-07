"""Tests for app.drain.py (Todo 3): maintenance lock, race-free write admission,
DrainLease lifecycle, EPERM-safe reconcile, and bounded acquisition.

Each test isolates its own temp dir and RELOADS the app.drain module so the
env-driven path constants are re-bound per test (avoids cross-test pollution).
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DrainTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.mkdtemp(prefix="lc-drain-")
        self._env = {
            "LC_DRAIN_STATE_FILE": str(Path(self._td) / "drain.state.json"),
            "LC_DRAIN_LOCK_FILE": str(Path(self._td) / "drain.lock"),
            "LC_MAINTENANCE_LOCK_FILE": str(Path(self._td) / "maintenance.lock"),
            "LC_WRITER_COUNT_FILE": str(Path(self._td) / "writer_count.json"),
        }
        for k, v in self._env.items():
            os.environ[k] = v
        # reload module so constants re-bind to the isolated paths
        self.drain = importlib.reload(importlib.import_module("app.drain"))

    def tearDown(self) -> None:
        for k in self._env:
            os.environ.pop(k, None)


class TestMaintenanceLock(DrainTestCase):
    def test_second_acquire_fails_fast(self) -> None:
        fd1 = self.drain.acquire_maintenance_lock()
        with self.assertRaises(TimeoutError):
            self.drain.acquire_maintenance_lock()
        self.drain.release_maintenance_lock(fd1)
        fd2 = self.drain.acquire_maintenance_lock()
        self.drain.release_maintenance_lock(fd2)


class TestWriteAdmission(DrainTestCase):
    def test_admission_allowed_when_accepting(self) -> None:
        fd = self.drain.writer_enter()
        self.assertEqual(self.drain._read_count(), 1)
        self.drain.writer_exit(fd)
        self.assertEqual(self.drain._read_count(), 0)

    def test_admission_denied_while_draining(self) -> None:
        dfd = self.drain.acquire_drain()
        self.drain.set_drain_state(self.drain.DRAINING, "t1")
        with self.assertRaises(RuntimeError):
            self.drain.writer_enter()
        self.drain.release_drain(dfd)
        self.drain.set_drain_state(self.drain.ACCEPTING, "t1")
        fd = self.drain.writer_enter()
        self.drain.writer_exit(fd)


class TestDrainLease(DrainTestCase):
    def test_full_lifecycle(self) -> None:
        with self.drain.DrainLease("lease1"):
            with open(self._env["LC_DRAIN_STATE_FILE"]) as f:
                st = json.load(f)
            self.assertEqual(st["state"], self.drain.DRAINED)
        with open(self._env["LC_DRAIN_STATE_FILE"]) as f:
            st = json.load(f)
        self.assertEqual(st["state"], self.drain.ACCEPTING)

    def test_lease_error_returns_to_accepting(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.drain.DrainLease("lease2"):
                raise RuntimeError("boom")
        with open(self._env["LC_DRAIN_STATE_FILE"]) as f:
            st = json.load(f)
        self.assertEqual(st["state"], self.drain.ACCEPTING)


class TestReconcileEperm(DrainTestCase):
    def test_eperm_keeps_state(self) -> None:
        # live owner (this process) + held shared lock -> no undrain
        self.drain.set_drain_state(self.drain.DRAINING, "t")
        state = self.drain._read_state()
        state["owner_pid"] = os.getpid()
        self.drain._write_state(state)
        p = Path(self._env["LC_DRAIN_LOCK_FILE"])
        p.parent.mkdir(parents=True, exist_ok=True)
        import fcntl
        shfd = os.open(p, os.O_RDWR | os.O_CREAT)
        fcntl.flock(shfd, fcntl.LOCK_SH)
        result = self.drain.reconcile_stale()
        fcntl.flock(shfd, fcntl.LOCK_UN)
        os.close(shfd)
        self.assertEqual(result, self.drain.DRAINING)

    def test_esrch_with_free_flock_undrains(self) -> None:
        self.drain.set_drain_state(self.drain.DRAINED, "t")
        state = self.drain._read_state()
        state["owner_pid"] = 999999
        self.drain._write_state(state)
        result = self.drain.reconcile_stale()
        self.assertEqual(result, self.drain.ACCEPTING)


if __name__ == "__main__":
    unittest.main()
