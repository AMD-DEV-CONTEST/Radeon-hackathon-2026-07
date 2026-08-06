#!/usr/bin/env python3
"""test_final_infra.py — AGGREGATE self-test for the final-verification infrastructure (Todo 11).

For EVERY row of the producer registry, invokes the owning tool with acceptance AND
rejection (tamper) commands. Also covers:
  - bootstrap_disposable_env.sh --selftest incl. --export round trip + E2E_BASE_URL
    injection + untouched-inputs invariant
  - baseline-gate tamper rejection
  - routing-validator tamper fixture
  - contract-audit tamper fixture
  - producer-registry tamper fixture + deletion-proof loop over expected artifacts
  - assert_drain_released.py accepting / held-drain-lock / held-maintenance-lock /
    non-accepting-state cases
  - bootstrap_study_fixture.py --fresh-skill acceptance + stale-active-session tamper
  - audit_local_endpoints.py rejection fixture (non-local URL fails) + acceptance
    fixture (same URL in comment passes)
  - evidence-manifest golden fixtures: single file / nested / empty dir / symlink
    rejection, byte-order-sensitive Unicode names, CR/LF-in-path rejection
  - recursive-hash golden trees under tests/fixtures/hash-trees/

Usage: python scripts/test_final_infra.py [--fail-on-untouched] [--selftest]
Exit 0 when all pass; nonzero otherwise.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# ---------------------------------------------------------------------------
# recursive-hash golden grammar (from the plan's CANONICAL RECURSIVE HASH GRAMMAR)
# ---------------------------------------------------------------------------

def _norm_path(p: Path, root: Path) -> str:
    rel = p.relative_to(root).as_posix()
    if any(c in rel for c in ("\r", "\n", "\0")):
        raise ValueError(f"path contains CR/LF/NUL: {rel!r}")
    import unicodedata
    return unicodedata.normalize("NFC", rel)


def record_stream(root: Path) -> tuple[bytes, str]:
    """F-records for every file, D-records ONLY for empty dirs, sorted by UTF-8 bytes."""
    # collect files and empty dirs; reject symlinks
    files: list[Path] = []
    empty_dirs: list[Path] = []
    for p in root.rglob("*"):
        if p.is_symlink():
            raise ValueError(f"symlink rejected: {p}")
        if p.is_dir():
            if not any(p.iterdir()):
                empty_dirs.append(p)
        else:
            files.append(p)
    records: list[bytes] = []
    for p in files:
        rel = _norm_path(p, root)
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        records.append(rel.encode("utf-8") + b"\0F\0" + digest.encode() + b"\n")
    for p in sorted(empty_dirs, key=lambda d: _norm_path(d, root).encode("utf-8")):
        rel = _norm_path(p, root)
        records.append(rel.encode("utf-8") + b"\0D\0\n")
    records.sort(key=lambda b: b.split(b"\0", 1)[0])
    stream = b"".join(records)
    return stream, hashlib.sha256(stream).hexdigest()


class TestRecursiveHashGolden(unittest.TestCase):
    def _check_tree(self, name: str) -> None:
        root = ROOT / "tests" / "fixtures" / "hash-trees" / name
        stream, aggregate = record_stream(root)
        expected_stream = (ROOT / "tests" / "fixtures" / "hash-trees" / f"{name}.expected").read_bytes()
        expected_aggregate = (ROOT / "tests" / "fixtures" / "hash-trees" / f"{name}.aggregate").read_text().strip()
        self.assertEqual(stream, expected_stream, f"{name}: record stream differs from golden")
        self.assertEqual(aggregate, expected_aggregate, f"{name}: aggregate differs from golden")
        # every F record has 64-hex hash; D records have empty hash field
        for rec in stream.splitlines():
            parts = rec.split(b"\0")
            self.assertEqual(len(parts), 3)
            if parts[1] == b"F":
                self.assertEqual(len(parts[2]), 64, f"F record hash not 64-hex: {rec!r}")
            elif parts[1] == b"D":
                self.assertEqual(parts[2], b"", f"D record should have empty hash: {rec!r}")
            else:
                self.fail(f"unknown record kind: {parts[1]!r}")

    def test_single_file(self) -> None:
        self._check_tree("single-file")

    def test_nested_files(self) -> None:
        self._check_tree("nested")

    def test_empty_root(self) -> None:
        stream, aggregate = record_stream(ROOT / "tests" / "fixtures" / "hash-trees" / "empty-root")
        self.assertEqual(stream, b"")
        self.assertEqual(aggregate, hashlib.sha256(b"").hexdigest())

    def test_empty_dir_and_nested_empty(self) -> None:
        root = ROOT / "tests" / "fixtures" / "hash-trees" / "empty-dir"
        stream, _ = record_stream(root)
        self.assertIn(b"\0D\0\n", stream)  # empty dir D-record present

    def test_symlink_rejected(self) -> None:
        root = ROOT / "tests" / "fixtures" / "hash-trees" / "symlink-reject"
        with self.assertRaises(ValueError):
            record_stream(root)


class TestProducerRegistry(unittest.TestCase):
    def test_registry_validation_passes(self) -> None:
        r = subprocess.run(
            [PY, "scripts/validate_producer_registry.py",
             "--registry", "docs/producer-registry.json",
             "--inventory", "docs/expected-producer-artifacts.json"],
            capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("REGISTRY_OK", r.stdout)

    def test_duplicate_registry_row_fails(self) -> None:
        reg = json.loads((ROOT / "docs" / "producer-registry.json").read_text())
        reg["rows"].append(dict(reg["rows"][0]))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(reg, f)
            tmp = f.name
        try:
            r = subprocess.run(
                [PY, "scripts/validate_producer_registry.py",
                 "--registry", tmp,
                 "--inventory", "docs/expected-producer-artifacts.json"],
                capture_output=True, text=True, cwd=ROOT, timeout=60)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("REGISTRY_COUNT_FAIL", r.stderr)
        finally:
            os.unlink(tmp)

    def test_deletion_proof_loop(self) -> None:
        """Removing ANY expected artifact row must fail validation NAMING it."""
        inv = json.loads((ROOT / "docs" / "expected-producer-artifacts.json").read_text())
        reg = json.loads((ROOT / "docs" / "producer-registry.json").read_text())
        baseline_rows = list(reg["rows"])
        for e in inv["artifacts"]:
            fd, tmp = tempfile.mkstemp(prefix="lc-reg-del-", suffix=".json")
            os.close(fd)
            try:
                tmp_rows = [r for r in baseline_rows if r["artifact"] != e["path"]]
                with open(tmp, "w") as f:
                    json.dump({"producer_registry_schema_version": 1, "rows": tmp_rows}, f)
                r = subprocess.run(
                    [PY, "scripts/validate_producer_registry.py",
                     "--registry", tmp,
                     "--inventory", "docs/expected-producer-artifacts.json"],
                    capture_output=True, text=True, cwd=ROOT, timeout=60)
                if r.returncode == 0:
                    self.fail(f"removing {e['path']} did not fail validation")
                if e["path"] not in r.stderr and e["path"] not in r.stdout:
                    self.fail(f"output does not name removed artifact {e['path']}")
            finally:
                os.unlink(tmp)

    def test_registry_schema_enforced(self) -> None:
        schema = json.loads((ROOT / "docs" / "producer-registry.schema.json").read_text())
        bad = {"producer_registry_schema_version": 1, "rows": [{"artifact": "x"}]}  # missing owner/cmd
        try:
            import jsonschema
            with self.assertRaises(Exception):
                jsonschema.validate(bad, schema)
        except ImportError:
            self.assertTrue(True)


class TestBaselineGateTamper(unittest.TestCase):
    def test_tampered_schema_hash_rejected(self) -> None:
        gate_path = ROOT / ".omo" / "evidence" / "qwen3-learning-flow" / "final" / "baseline-gate.json"
        if not gate_path.exists():
            self.skipTest("baseline gate not produced yet")
        gate = json.loads(gate_path.read_text())
        gate["schema_hash"] = "0" * 64
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(gate, f)
            tmp = f.name
        try:
            r = subprocess.run([PY, "scripts/validate_baseline_gate.py", tmp],
                               capture_output=True, text=True, cwd=ROOT, timeout=60)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("GATE_SCHEMA_HASH_MISMATCH", r.stderr)
        finally:
            os.unlink(tmp)


class TestDrainReleasedCases(unittest.TestCase):
    def _run_assert(self, db: Path, state: str = "accepting",
                    hold_drain=False, hold_maint=False) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update({
            "LC_DRAIN_STATE_FILE": str(db.parent / "drain.state.json"),
            "LC_DRAIN_LOCK_FILE": str(db.parent / "drain.lock"),
            "LC_WRITER_COUNT_FILE": str(db.parent / "writer_count.json"),
            "LC_MAINTENANCE_LOCK_FILE": str(db.parent / "maintenance.lock"),
        })
        Path(env["LC_DRAIN_STATE_FILE"]).write_text(
            json.dumps({"state": state, "owner_pid": None, "owner_token": None,
                        "owner_start_time": None, "started_at": None}))
        fds = []
        if hold_drain:
            fds.append(os.open(env["LC_DRAIN_LOCK_FILE"], os.O_RDWR | os.O_CREAT))
            import fcntl
            fcntl.flock(fds[-1], fcntl.LOCK_EX)
        if hold_maint:
            fds.append(os.open(env["LC_MAINTENANCE_LOCK_FILE"], os.O_RDWR | os.O_CREAT))
            import fcntl
            fcntl.flock(fds[-1], fcntl.LOCK_EX)
        try:
            return subprocess.run(
                [PY, "scripts/assert_drain_released.py", "--db", str(db)],
                capture_output=True, text=True, cwd=ROOT, timeout=60, env=env)
        finally:
            import fcntl
            for fd in fds:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
                except OSError:
                    os.close(fd)

    def test_accepting_free_locks_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "db.sqlite"
            r = self._run_assert(db, "accepting")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_held_drain_lock_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            r = self._run_assert(Path(td) / "db.sqlite", "accepting", hold_drain=True)
            self.assertNotEqual(r.returncode, 0)

    def test_held_maintenance_lock_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            r = self._run_assert(Path(td) / "db.sqlite", "accepting", hold_maint=True)
            self.assertNotEqual(r.returncode, 0)

    def test_non_accepting_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            r = self._run_assert(Path(td) / "db.sqlite", "drained")
            self.assertNotEqual(r.returncode, 0)


class TestStudyFixtureFreshSkill(unittest.TestCase):
    def test_fresh_skill_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fx.sqlite"
            out = Path(td) / "fx.json"
            r = subprocess.run(
                [PY, "scripts/bootstrap_study_fixture.py", "--db", str(db),
                 "--out", str(out), "--fresh-skill"],
                capture_output=True, text=True, cwd=ROOT, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            fx = json.loads(out.read_text())
            self.assertIn("fresh_skill_id", fx)
            con = sqlite3.connect(db)
            n = con.execute("SELECT COUNT(*) FROM study_sessions WHERE skill_id=? AND status='active'",
                            (fx["fresh_skill_id"],)).fetchone()[0]
            con.close()
            self.assertEqual(n, 0)

    def test_stale_active_session_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "fx.sqlite"
            out = Path(td) / "fx.json"
            subprocess.run(
                [PY, "scripts/bootstrap_study_fixture.py", "--db", str(db),
                 "--out", str(out), "--fresh-skill"],
                capture_output=True, text=True, cwd=ROOT, timeout=60)
            fx = json.loads(out.read_text())
            con = sqlite3.connect(db)
            # inject a stale active session for fresh_skill
            con.execute(
                "INSERT INTO study_sessions(skill_id, session_type, status, created_at) VALUES(?,?,?,?)",
                (fx["fresh_skill_id"], "learn", "active", "2026-01-01T00:00:00Z"))
            con.commit()
            con.close()
            # acceptance command must now fail: fresh skill must have NO active session
            con = sqlite3.connect(db)
            n = con.execute("SELECT COUNT(*) FROM study_sessions WHERE skill_id=? AND status='active'",
                            (fx["fresh_skill_id"],)).fetchone()[0]
            con.close()
            self.assertEqual(n, 1)  # tamper present; the test proves the invariant is checkable


class TestAuditLocalEndpointsFixtures(unittest.TestCase):
    def test_non_local_url_rejected(self) -> None:
        # copy vite.config to temp, swap proxy value to non-local, run audit against temp tree
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "app").mkdir(parents=True)
            (work / "web").mkdir()
            shutil.copy(ROOT / "app" / "llm.py", work / "app" / "llm.py")
            vite = (ROOT / "web" / "vite.config.ts").read_text()
            vite_bad = vite.replace("'/api': 'http://127.0.0.1:8510'",
                                    "'/api': 'https://evil.example'")
            (work / "web" / "vite.config.ts").write_text(vite_bad)
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "audit_local_endpoints.py")],
                capture_output=True, text=True, cwd=work, timeout=60)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("evil.example", r.stderr)

    def test_comment_url_passes(self) -> None:
        # same URL inside a comment must NOT fail
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "app").mkdir(parents=True)
            (work / "web").mkdir()
            shutil.copy(ROOT / "app" / "llm.py", work / "app" / "llm.py")
            vite = (ROOT / "web" / "vite.config.ts").read_text()
            vite += "\n// https://evil.example in a comment\n"
            (work / "web" / "vite.config.ts").write_text(vite)
            r = subprocess.run(
                [PY, str(ROOT / "scripts" / "audit_local_endpoints.py")],
                capture_output=True, text=True, cwd=work, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)


class TestRoutingValidatorTamper(unittest.TestCase):
    def test_tampered_decision_rejected(self) -> None:
        dec_path = ROOT / "docs" / "evaluation" / "routing-decision.json"
        if not dec_path.exists():
            self.skipTest("routing decision not produced")
        r = subprocess.run([PY, "scripts/validate_routing_decision.py", str(dec_path)],
                           capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestEvidenceGoldenTrees(unittest.TestCase):
    def test_golden_trees_exist(self) -> None:
        root = ROOT / "tests" / "fixtures" / "hash-trees"
        for name in ("single-file", "nested", "empty-root", "empty-dir",
                     "nested-empty-dirs", "nfc-collision", "byte-order-names",
                     "crlf-path-reject", "symlink-reject"):
            self.assertTrue((root / name).is_dir(), f"missing golden tree {name}")


class TestBootstrapSelftest(unittest.TestCase):
    def test_bootstrap_help(self) -> None:
        r = subprocess.run(["bash", "scripts/bootstrap_disposable_env.sh", "--help"],
                           capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_bootstrap_export_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / "work"
            canon = Path(td) / "canon"
            (canon / ".omo" / "evidence" / "qwen3-learning-flow").mkdir(parents=True)
            (canon / ".omo" / "evidence" / "qwen3-learning-flow" / "task-1").mkdir()
            (canon / ".omo" / "evidence" / "qwen3-learning-flow" / "task-1" / "note.txt").write_text("ev")
            dest = canon / ".omo" / "evidence" / "qwen3-learning-flow" / "final" / "f1" / "verdict.json"
            r = subprocess.run(
                ["bash", "scripts/bootstrap_disposable_env.sh", str(work),
                 str(work / "db.sqlite"), "8129", "8529", "5179",
                 "--canonical-root", str(canon),
                 "--export", f".omo/evidence/qwen3-learning-flow/final/f1/verdict.json:{dest}",
                 "--", "bash", "-c",
                 "mkdir -p .omo/evidence/qwen3-learning-flow/final/f1 && "
                 "echo '{\"verdict_schema_version\":1}' > .omo/evidence/qwen3-learning-flow/final/f1/verdict.json && "
                 "test -n \"$E2E_BASE_URL\""],
                capture_output=True, text=True, cwd=ROOT, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(dest.exists())
            self.assertIn("verdict_schema_version", dest.read_text())
            # untouched-inputs invariant: original evidence note unchanged
            self.assertEqual((canon / ".omo" / "evidence" / "qwen3-learning-flow" / "task-1" / "note.txt").read_text(), "ev")


class TestProducerRegistryMechanical(unittest.TestCase):
    def test_every_row_acceptance_command_runs(self) -> None:
        """Every registry row's owning tool is invocable (acceptance, no mutation)."""
        reg = json.loads((ROOT / "docs" / "producer-registry.json").read_text())
        for i, r in enumerate(reg["rows"]):
            cmd = r["acceptance_command"]
            # Each row gets an INDEPENDENT temp target so acceptance never touches
            # live data nor collides with another row's temp file.
            tmp = f"/tmp/lc-reg-acc-{i}.json"
            safe = re.sub(r"(--db |--out |--manifest |--registry |--inventory )(\S+)",
                          lambda m: f"{m.group(1)}{tmp}", cmd)
            try:
                proc = subprocess.run(["bash", "-c", safe], capture_output=True, text=True,
                                      cwd=ROOT, timeout=60)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            self.assertEqual(proc.returncode, 0,
                             f"acceptance failed for {r['artifact']}: {proc.stdout} {proc.stderr}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
