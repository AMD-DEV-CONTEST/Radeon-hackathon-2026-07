"""Todo 3 integration tests: backup/verify/restore round-trip, canonical schema
byte-exactness, and assert_drain_released behavior.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path("/persistent/learning-companion")
sys.path.insert(0, str(ROOT))


def sh(*args, **kw):
    env = dict(os.environ)
    env.update(kw.pop("env", {}))
    return subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          cwd=ROOT, env=env, timeout=90, **kw)


class TestCanonicalSchema(unittest.TestCase):
    def test_canonicalize_verify_ok(self) -> None:
        r = sh("python3", "scripts/canonicalize_schema.py", "--verify")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VERIFY_OK", r.stdout)

    def test_golden_fixture_exists_and_matches(self) -> None:
        g = ROOT / "tests" / "fixtures" / "golden-target-schema.sql"
        sha = ROOT / "tests" / "fixtures" / "golden-target-schema.sha256"
        self.assertTrue(g.exists(), "golden fixture missing")
        self.assertTrue(sha.exists(), "golden sha missing")
        import hashlib
        self.assertEqual(hashlib.sha256(g.read_bytes()).hexdigest(), sha.read_text().strip())


class TestBackupRestore(unittest.TestCase):
    def test_round_trip_preserves_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "learning.db"
            # create a source DB with the target schema + one row
            import sqlite3
            con = sqlite3.connect(db)
            con.executescript((ROOT / "db/migrations/0001_initial.sql").read_text())
            con.execute("INSERT INTO skills(name, created_at, updated_at) VALUES('t','x','x')")
            con.commit(); con.close()
            env = {
                "LC_DB_PATH": str(db),
                "LC_BACKUP_DIR": str(Path(td) / "backups"),
                "LC_DRAIN_STATE_FILE": str(Path(td) / "drain.state.json"),
                "LC_DRAIN_LOCK_FILE": str(Path(td) / "drain.lock"),
                "LC_MAINTENANCE_LOCK_FILE": str(Path(td) / "maintenance.lock"),
                "LC_WRITER_COUNT_FILE": str(Path(td) / "writer_count.json"),
            }
            out = Path(td) / "artifact.txt"
            r = sh("bash", "scripts/manage_learning_db.sh", "backup",
                   "--db", str(db), "--artifact-out", str(out), env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            art = out.read_text().strip()
            self.assertTrue(Path(art).exists(), art)
            rv = sh("bash", "scripts/manage_learning_db.sh", "verify", art, env=env)
            self.assertEqual(rv.returncode, 0, rv.stderr)
            target = Path(td) / "restored.sqlite"
            rr = sh("bash", "scripts/manage_learning_db.sh", "restore", art, "--to", str(target), env=env)
            self.assertEqual(rr.returncode, 0, rr.stderr)
            con = sqlite3.connect(target)
            n = con.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            con.close()
            self.assertEqual(n, 1)


class TestAssertDrainReleased(unittest.TestCase):
    def _setup(self, td: str, state: str) -> None:
        base = Path(td)
        (base / "drain.state.json").write_text(json.dumps({"state": state}))
        open(base / "drain.lock", "w").close()
        open(base / "maintenance.lock", "w").close()
        (base / "learning.db").write_bytes(b"placeholder")

    def test_accepting_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._setup(td, "accepting")
            r = sh("python3", "scripts/assert_drain_released.py", "--db", f"{td}/learning.db")
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_draining_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._setup(td, "draining")
            r = sh("python3", "scripts/assert_drain_released.py", "--db", f"{td}/learning.db")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("ASSERT_FAIL: state=", r.stderr + r.stdout)

    def test_missing_db_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            r = sh("python3", "scripts/assert_drain_released.py", "--db", f"{td}/nope.sqlite")
            self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
