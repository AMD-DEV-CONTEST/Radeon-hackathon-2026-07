"""Todo 4 tests: durable extraction lifecycle + source validation + candidate transitions.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import processing  # noqa: E402

RAFT = ("Raft 通过强领导者简化共识协议。领导者选举使用随机超时，多数票胜出。\n"
        "日志复制由领导者发起，多数确认后提交。")


def _fresh_db():
    td = tempfile.mkdtemp(prefix="lc-proc-")
    db = Path(td) / "learning.db"
    processing.ensure_schema(db)
    con = processing.connect(db)
    con.execute("INSERT INTO skills(name, created_at, updated_at) VALUES('t','x','x')")
    con.commit()
    con.close()
    return db


class TestMaterialIngestion(unittest.TestCase):
    def test_ingest_normalizes_and_hashes(self) -> None:
        db = _fresh_db()
        mid, created = processing.ingest_material(1, RAFT, db)
        self.assertTrue(created)
        # idempotent by hash
        mid2, created2 = processing.ingest_material(1, RAFT, db)
        self.assertEqual(mid, mid2)
        self.assertFalse(created2)
        # normalized + sha stored
        con = processing.connect(db)
        row = con.execute("SELECT normalized_text, content_sha256 FROM materials WHERE id=?", (mid,)).fetchone()
        con.close()
        self.assertNotIn("\r\n", row["normalized_text"])
        self.assertEqual(row["content_sha256"], processing.content_sha(RAFT))

    def test_different_text_different_material(self) -> None:
        db = _fresh_db()
        a, _ = processing.ingest_material(1, RAFT, db)
        b, _ = processing.ingest_material(1, RAFT + "\n另外内容", db)
        self.assertNotEqual(a, b)

    def test_ingest_persists_filename(self) -> None:
        db = _fresh_db()
        mid, _ = processing.ingest_material(1, RAFT, db, filename="raft-notes.md")
        con = processing.connect(db)
        row = con.execute("SELECT filename FROM materials WHERE id=?", (mid,)).fetchone()
        con.close()
        self.assertEqual(row["filename"], "raft-notes.md")
        # default for pasted text is empty
        mid2, _ = processing.ingest_material(1, RAFT + "\n无文件名", db)
        con = processing.connect(db)
        row2 = con.execute("SELECT filename FROM materials WHERE id=?", (mid2,)).fetchone()
        con.close()
        self.assertEqual(row2["filename"], "")

    def test_ensure_schema_adds_filename_to_existing_db(self) -> None:
        # 存量库无 filename 列 -> ensure_schema 应通过 ALTER TABLE 补齐
        td = tempfile.mkdtemp(prefix="lc-schema-")
        db = Path(td) / "old.db"
        import sqlite3
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE materials (id INTEGER PRIMARY KEY, skill_id INTEGER, "
                    "raw_text TEXT, normalized_text TEXT, content_sha256 TEXT, created_at TEXT)")
        con.commit()
        con.close()
        processing.ensure_schema(db)
        con = processing.connect(db)
        cols = [r[1] for r in con.execute("PRAGMA table_info(materials)")]
        con.close()
        self.assertIn("filename", cols)


class TestRunLifecycle(unittest.TestCase):
    def test_run_transitions_and_requeue(self) -> None:
        db = _fresh_db()
        mid, _ = processing.ingest_material(1, RAFT, db)
        rid = processing.create_run(mid, "Qwen3-32B-AWQ", db)
        processing.mark_run(rid, processing.RUN_RUNNING, db_path=db)
        processing.mark_run(rid, processing.RUN_VERIFIED, db_path=db)
        # requeue stale running runs only
        rid2 = processing.create_run(mid, "Qwen3", db)
        processing.mark_run(rid2, processing.RUN_RUNNING, db_path=db)
        n = processing.requeue_stale_runs(db)
        self.assertEqual(n, 1)
        con = processing.connect(db)
        st2 = con.execute("SELECT status FROM extraction_runs WHERE id=?", (rid2,)).fetchone()
        st1 = con.execute("SELECT status FROM extraction_runs WHERE id=?", (rid,)).fetchone()
        con.close()
        self.assertEqual(st2["status"], processing.RUN_QUEUED)
        self.assertEqual(st1["status"], processing.RUN_VERIFIED)

    def test_retry_unlimited_but_only_failed(self) -> None:
        db = _fresh_db()
        mid, _ = processing.ingest_material(1, RAFT, db)
        rid = processing.create_run(mid, "Qwen3", db)
        processing.mark_run(rid, processing.RUN_FAILED, "boom", db)
        # manual retries are unlimited: retry past MAX_RETRY keeps working
        # (each retry queues the run; the worker failing again returns it to failed)
        for _ in range(processing.MAX_RETRY + 2):
            self.assertTrue(processing.retry_failed_run(rid, db))
            processing.mark_run(rid, processing.RUN_FAILED, "boom again", db)
        # but only a FAILED run may be retried
        processing.mark_run(rid, processing.RUN_VERIFIED, None, db)
        self.assertFalse(processing.retry_failed_run(rid, db))
        self.assertFalse(processing.retry_failed_run(999999, db))  # missing run


class TestSourceValidation(unittest.TestCase):
    def _unit(self, start, end, quote, content):
        return {"content": content, "source_start": start, "source_end": end,
                "source_quote": quote, "key_points": [], "example": "", "pitfall": ""}

    def test_exact_quote_match(self) -> None:
        db = _fresh_db()
        mid, _ = processing.ingest_material(1, RAFT, db)
        con = processing.connect(db)
        mat = con.execute("SELECT normalized_text FROM materials WHERE id=?", (mid,)).fetchone()
        con.close()
        idx = RAFT.find("强领导者")
        u = self._unit(idx, idx + 4, "强领导者", "强领导者")
        ok, err = processing.validate_unit_source(u, mat)
        self.assertTrue(ok, err)

    def test_quote_mismatch_rejected(self) -> None:
        db = _fresh_db()
        mid, _ = processing.ingest_material(1, RAFT, db)
        con = processing.connect(db)
        mat = con.execute("SELECT normalized_text FROM materials WHERE id=?", (mid,)).fetchone()
        con.close()
        u = self._unit(0, 4, "不存在的原文", "x")
        ok, err = processing.validate_unit_source(u, mat)
        self.assertFalse(ok)
        self.assertIn("does not match", err)

    def test_entailment_fails_on_unsupported_claim(self) -> None:
        db = _fresh_db()
        mid, _ = processing.ingest_material(1, RAFT, db)
        con = processing.connect(db)
        mat = con.execute("SELECT normalized_text FROM materials WHERE id=?", (mid,)).fetchone()
        con.close()
        # quote is a real substring but content is NOT entailed by it
        u = self._unit(0, 4, "Raft", "Qwen3 模型支持 100 种语言")
        ok, err = processing.entailment_ok(u)
        self.assertFalse(ok)
        self.assertIn("not entailed", err)


class TestCandidateTransitions(unittest.TestCase):
    def test_verified_duplicate_rejected(self) -> None:
        db = _fresh_db()
        mid, _ = processing.ingest_material(1, RAFT, db)
        con = processing.connect(db)
        mat = con.execute("SELECT normalized_text FROM materials WHERE id=?", (mid,)).fetchone()
        con.close()
        norm = mat["normalized_text"]
        idx = norm.find("强领导者")
        candidates = [
            {"content": "强领导者", "source_start": idx, "source_end": idx + 4,
             "source_quote": "强领导者", "key_points": [], "example": "", "pitfall": ""},
            # duplicate of the first
            {"content": "强领导者", "source_start": idx, "source_end": idx + 4,
             "source_quote": "强领导者", "key_points": [], "example": "", "pitfall": ""},
            # rejected: quote not in source
            {"content": "不存在的知识", "source_start": 0, "source_end": 2,
             "source_quote": "Ra", "key_points": [], "example": "", "pitfall": ""},
        ]
        stats = processing.commit_candidates(1, mid, candidates, db)
        self.assertEqual(stats["verified"], 1)
        self.assertEqual(stats["duplicate"], 1)
        self.assertEqual(stats["rejected"], 1)


if __name__ == "__main__":
    unittest.main()
