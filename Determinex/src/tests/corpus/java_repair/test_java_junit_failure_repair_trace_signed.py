"""
Java JUnit failure repair trace signing tests.

Verifies that repair tasks from JUnit test failures are HMAC-signed,
carry required Java metadata, and fail verification after tampering.

JAVA_REPAIR_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from agents.base_agent import SCHEMA_VERSION, CorpusType
from corpus.code_ingest.java_repair_pipeline import JavaRepairPipeline
from corpus.corpus_manager import CorpusManager


def _make_junit_task(task_id: str = "junit-001", framework: str = "junit5"):
    return JavaRepairPipeline.make_test_task(
        task_id=task_id,
        failure_type="junit_failure",
        framework=framework,
        error_message="org.opentest4j.AssertionFailedError: expected <true> but was <false>\n\tat UserServiceTest.testNullUser(UserServiceTest.java:24)",
    )


class TestJUnitFailureRepairTraceSigned:
    def test_junit_trace_has_schema_version(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_junit_task("jf-001")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record["schema_version"] == SCHEMA_VERSION

    def test_junit_trace_is_hmac_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_junit_task("jf-002")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert "_sig" in record
        assert len(record["_sig"]) >= 32

    def test_junit_trace_verifies(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_junit_task("jf-003")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_junit_trace_tamper_fails(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_junit_task("jf-004")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        record["verdict"] = "fail"  # tamper
        assert cm.verify(record) is False

    def test_junit5_framework_preserved(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_junit_task("jf-005", framework="junit5")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record.get("framework") == "junit5"
        assert record.get("failure_type") == "junit_failure"

    def test_junit4_framework_preserved(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_junit_task("jf-006", framework="junit4")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record.get("framework") == "junit4"

    def test_different_junit_tasks_have_different_sigs(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        r1 = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="jf-007a",
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="java_corpus",
            payload=_make_junit_task("jf-007a").to_corpus_payload(),
        )
        r2 = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="jf-007b",
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="java_corpus",
            payload=_make_junit_task("jf-007b").to_corpus_payload(),
        )
        assert r1["_sig"] != r2["_sig"]

    def test_pipeline_writes_junit_task(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        task = _make_junit_task("jf-008")
        task_id = pipeline._write_corpus_record(task, "java_corpus")
        assert task_id == "jf-008"
