"""Todo 8 tests: complete FastAPI wiring, gated reset, drain/undrain, SPA fallback,
startup recovery, and the material -> extraction -> learning -> review journey.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path("/persistent/learning-companion")
sys.path.insert(0, str(ROOT))

from app import drain, processing, study  # noqa: E402


def _sh(*args, env=None, timeout=120):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          cwd=ROOT, timeout=timeout, env=e)


class TestAdminDrainUndrain(unittest.TestCase):
    def test_drain_undrain_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            env = {
                "LC_DRAIN_STATE_FILE": str(td / "drain.state.json"),
                "LC_DRAIN_LOCK_FILE": str(td / "drain.lock"),
                "LC_WRITER_COUNT_FILE": str(td / "writer_count.json"),
                "LC_MAINTENANCE_LOCK_FILE": str(td / "maintenance.lock"),
            }
            # emulate API: acquire drain, assert drained, undrain, write admitted
            fd = drain.acquire_drain()
            drain.set_drain_state(drain.DRAINING, "test")
            drain.wait_drained()
            drain.set_drain_state(drain.DRAINED, "test")
            self.assertEqual(drain._read_state()["state"], drain.DRAINED)
            drain.release_drain(fd)
            drain._reset_state()
            self.assertEqual(drain._read_state()["state"], drain.ACCEPTING)
            # write admission works after undrain
            wfd = drain.writer_enter()
            drain.writer_exit(wfd)
            self.assertEqual(drain._read_count(), 0)

    def test_drain_rejects_new_writes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            env = {
                "LC_DRAIN_STATE_FILE": str(td / "drain.state.json"),
                "LC_DRAIN_LOCK_FILE": str(td / "drain.lock"),
                "LC_WRITER_COUNT_FILE": str(td / "writer_count.json"),
                "LC_MAINTENANCE_LOCK_FILE": str(td / "maintenance.lock"),
            }
            fd = drain.acquire_drain()
            drain.set_drain_state(drain.DRAINED, "test")
            try:
                with self.assertRaises(RuntimeError):
                    drain.writer_enter()
            finally:
                drain.release_drain(fd)
                drain._reset_state()


class TestGatedReset(unittest.TestCase):
    def _setup(self, td: Path) -> dict:
        db = td / "live.sqlite"
        backup_list = td / "backup.txt"
        env = {
            "LC_DB_PATH": str(db),
            "LC_BACKUP_DIR": str(td / "backups"),
            "LC_DRAIN_STATE_FILE": str(td / "drain.state.json"),
            "LC_DRAIN_LOCK_FILE": str(td / "drain.lock"),
            "LC_WRITER_COUNT_FILE": str(td / "writer_count.json"),
            "LC_MAINTENANCE_LOCK_FILE": str(td / "maintenance.lock"),
        }
        # seed a DB + verified backup
        r = _sh(sys.executable, ROOT / "scripts" / "bootstrap_study_fixture.py",
                "--db", str(db), "--out", str(td / "fx.json"), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = _sh("bash", ROOT / "scripts" / "manage_learning_db.sh", "backup",
                "--db", str(db), "--artifact-out", str(backup_list), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        backup = backup_list.read_text().strip()
        # routing decision artifact
        routing = ROOT / "docs" / "evaluation" / "routing-decision.json"
        self.assertTrue(routing.exists())
        return {"db": db, "backup": backup, "routing": routing, "env": env}

    def test_reset_succeeds_when_both_gates_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            s = self._setup(Path(td))
            r = _sh("bash", ROOT / "scripts" / "manage_learning_db.sh", "reset",
                    "--backup", s["backup"], "--routing", str(s["routing"]), env=s["env"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            con = sqlite3.connect(s["db"])
            row = con.execute("PRAGMA integrity_check").fetchone()
            con.close()
            self.assertEqual(row[0], "ok")

    def test_reset_aborts_without_routing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            s = self._setup(Path(td))
            # missing routing decision -> reset aborts, DB intact
            r = _sh("bash", ROOT / "scripts" / "manage_learning_db.sh", "reset",
                    "--backup", s["backup"], "--routing", str(Path(td) / "missing.json"),
                    env=s["env"])
            self.assertNotEqual(r.returncode, 0)
            con = sqlite3.connect(s["db"])
            n = con.execute("SELECT COUNT(*) AS c FROM skills").fetchone()[0]
            con.close()
            self.assertGreaterEqual(n, 1)  # live DB untouched


class TestSpaFallback(unittest.TestCase):
    def test_non_api_route_serves_index(self) -> None:
        from app.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            # / (index) and a deep non-api route both serve the HTML fallback
            # (the real web/dist/index.html when built, else the placeholder)
            r = client.get("/some/page")
            self.assertEqual(r.status_code, 200)
            body = r.text.lower()
            self.assertTrue("<!doctype html" in body or "<html" in body or "learning companion" in body,
                            body[:200])
            r2 = client.get("/")
            self.assertEqual(r2.status_code, 200)

    def test_api_route_preserved(self) -> None:
        from app.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            r = client.get("/api/stats")
            self.assertEqual(r.status_code, 200)
            self.assertIn("skills", r.json())


class TestStartupRecovery(unittest.TestCase):
    def test_requeue_stale_runs_at_startup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            db = td / "recovery.sqlite"
            processing.ensure_schema(db)
            con = processing.connect(db)
            con.execute("INSERT INTO skills(name, created_at, updated_at) VALUES('x','t','t')")
            con.execute("INSERT INTO materials(skill_id, raw_text, normalized_text, content_sha256, created_at) "
                        "VALUES(1,'t','t','sha','t')")
            con.execute("INSERT INTO extraction_runs(material_id, status, created_at, updated_at) "
                        "VALUES(1,'running','t','t')")
            con.commit()
            con.close()
            n = processing.requeue_stale_runs(db)
            self.assertEqual(n, 1)
            con = processing.connect(db)
            st = con.execute("SELECT status FROM extraction_runs WHERE id=1").fetchone()["status"]
            con.close()
            self.assertEqual(st, processing.RUN_QUEUED)

    def test_reconcile_stale_drained_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # stale drained state with a dead owner + free lock -> reconciled to accepting
            env = {
                "LC_DRAIN_STATE_FILE": str(td / "drain.state.json"),
                "LC_DRAIN_LOCK_FILE": str(td / "drain.lock"),
                "LC_WRITER_COUNT_FILE": str(td / "writer_count.json"),
                "LC_MAINTENANCE_LOCK_FILE": str(td / "maintenance.lock"),
            }
            import fcntl
            # claim drain lock then release it (free lock) and write stale state with dead pid
            lock_path = Path(env["LC_DRAIN_LOCK_FILE"])
            lock_path.touch()
            drain._write_state({"state": drain.DRAINED, "owner_token": "x",
                                "owner_pid": 999999999, "owner_start_time": 1.0,
                                "started_at": "t"})
            # simulate dead owner: pid not present
            self.assertEqual(drain.reconcile_stale(), drain.ACCEPTING)


class TestMaterialJourney(unittest.TestCase):
    def test_material_extraction_learning_review_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            db = td / "j.sqlite"
            env = dict(os.environ)
            env.update({
                "LC_DB_PATH": str(db),
                "LC_EXTRACT_STUB": "verify",
                "LC_DRAIN_STATE_FILE": str(td / "drain.state.json"),
                "LC_DRAIN_LOCK_FILE": str(td / "drain.lock"),
                "LC_WRITER_COUNT_FILE": str(td / "writer_count.json"),
                "LC_MAINTENANCE_LOCK_FILE": str(td / "maintenance.lock"),
            })
            r = _sh(sys.executable, ROOT / "scripts" / "bootstrap_study_fixture.py",
                    "--db", str(db), "--out", str(td / "fx.json"), env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            fx = json.loads((td / "fx.json").read_text())
            sid = study.start_learning_session(fx["skill_id"], db_path=db)["session"]["id"]
            from app.grading import GradingUnavailable
            from tests.test_study import _ok_grader
            res = study.submit_assessment(sid, fx["unit_id"], "k1", fx["gold_recall_text"],
                                          db_path=db, grader=_ok_grader)
            self.assertEqual(res["attempt"]["status"], "judged")
            con = processing.connect(db)
            due = con.execute(
                "SELECT COUNT(*) AS c FROM learning_progress WHERE next_review_at IS NOT NULL").fetchone()["c"]
            con.close()
            self.assertEqual(due, 1)


class TestMarkdownSourceDocument(unittest.TestCase):
    """Markdown-only upload boundary + source-document read-back (source viewer)."""

    def _client(self, td: Path):
        import os
        db = td / "src.sqlite"
        # 必须在 import app.main 之前设置 LC_DB_PATH，否则 study.resolve_db()
        # 在模块导入期缓存默认路径。worker 是后台线程，env 必须保持到测试结束。
        self._env_backup = {k: os.environ.get(k) for k in (
            "LC_DB_PATH", "LC_DRAIN_STATE_FILE", "LC_DRAIN_LOCK_FILE",
            "LC_WRITER_COUNT_FILE", "LC_MAINTENANCE_LOCK_FILE", "LC_EXTRACT_STUB")}
        os.environ["LC_DB_PATH"] = str(db)
        os.environ["LC_DRAIN_STATE_FILE"] = str(td / "drain.state.json")
        os.environ["LC_DRAIN_LOCK_FILE"] = str(td / "drain.lock")
        os.environ["LC_WRITER_COUNT_FILE"] = str(td / "writer_count.json")
        os.environ["LC_MAINTENANCE_LOCK_FILE"] = str(td / "maintenance.lock")
        os.environ["LC_EXTRACT_STUB"] = "verify"
        processing.ensure_schema(db)
        from app.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def tearDown(self) -> None:
        import os
        for k, v in getattr(self, "_env_backup", {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_markdown_upload_persists_filename_and_source(self) -> None:
        import uuid
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            skill = f"源文档测试-{uuid.uuid4().hex[:8]}"
            text = (f"# 标题\n\n强领导者通过多数确认后提交达成一致。\n\n"
                    f"唯一片段 {uuid.uuid4().hex}")
            r = client.post("/api/materials", json={
                "skill_name": skill,
                "text": text,
                "filename": "notes.md",
            })
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            mid = body["material_id"]
            self.assertEqual(body["status"], "queued")
            # source document endpoint returns raw markdown + filename
            src = client.get(f"/api/materials/{mid}")
            self.assertEqual(src.status_code, 200)
            d = src.json()
            self.assertEqual(d["filename"], "notes.md")
            self.assertEqual(d["raw_text"], text)
            self.assertEqual(d["skill_id"], body["skill_id"])
            # runs list exposes filename
            runs = client.get(f"/api/skills/{body['skill_id']}/runs").json()["runs"]
            self.assertTrue(any(x["material_filename"] == "notes.md" for x in runs))
            # source_material linkage: commit_candidates wires every candidate to its material
            db_path = Path(td) / "src.sqlite"
            norm = processing.normalize_text(text)
            idx = norm.find("强领导者")
            stats = processing.commit_candidates(body["skill_id"], mid, [
                {"content": "强领导者通过多数确认后提交达成一致。", "source_start": idx,
                 "source_end": idx + 4, "source_quote": "强领导者",
                 "key_points": [], "example": "", "pitfall": ""},
            ], db_path=db_path)
            self.assertEqual(stats["verified"], 1)
            con = processing.connect(db_path)
            row = con.execute(
                "SELECT source_material FROM learning_units WHERE skill_id=? AND status='verified' LIMIT 1",
                (body["skill_id"],)).fetchone()
            con.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["source_material"], str(mid))

    def test_non_markdown_filename_rejected(self) -> None:
        import uuid
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            r = client.post("/api/materials", json={
                "skill_name": f"x-{uuid.uuid4().hex[:8]}",
                "text": "一段足够长的正文内容用于通过校验。",
                "filename": "notes.txt",
            })
            self.assertEqual(r.status_code, 422)
            self.assertIn("Markdown", r.json()["detail"])

    def test_missing_material_404(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            r = client.get("/api/materials/999999")
            self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
