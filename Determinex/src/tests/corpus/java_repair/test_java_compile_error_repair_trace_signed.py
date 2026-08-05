"""
Java compile-error repair trace signing tests.

Verifies that Java repair tasks generated from compile errors are written to
the corpus with HMAC signatures, correct schema version, and required fields.

JAVA_REPAIR_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from agents.base_agent import SCHEMA_VERSION, CorpusType
from corpus.code_ingest.java_repair_pipeline import JavaRepairPipeline
from corpus.corpus_manager import CorpusManager


def _make_compile_error_task(task_id: str = "compile-001"):
    return JavaRepairPipeline.make_test_task(
        task_id=task_id,
        failure_type="compile_error",
        error_message="error: incompatible types: int cannot be converted to String\n  at Converter.java:17",
        build_system="maven",
    )


class TestCompileErrorRepairTraceSigned:
    def test_compile_error_record_has_schema_version(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_compile_error_task("ce-001")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record["schema_version"] == SCHEMA_VERSION

    def test_compile_error_record_is_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_compile_error_task("ce-002")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert "_sig" in record
        assert len(record["_sig"]) >= 32

    def test_compile_error_record_verifies(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_compile_error_task("ce-003")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_compile_error_tamper_fails_verification(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_compile_error_task("ce-004")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        record["failure_type"] = "injected_value"
        assert cm.verify(record) is False

    def test_compile_error_failure_type_preserved(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_compile_error_task("ce-005")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record["failure_type"] == "compile_error"
        assert record["language"] == "java"
        assert record["build_system"] == "maven"

    def test_compile_error_error_message_in_record(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_compile_error_task("ce-006")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert "incompatible types" in record.get("error_message", "")

    def test_compile_error_corpus_type_is_code_verdict(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = _make_compile_error_task("ce-007")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record["corpus_type"] == CorpusType.CODE_VERDICT.value

    def test_pipeline_writes_compile_error_to_corpus(self, tmp_path):
        """Pipeline._write_corpus_record must persist a signed record."""
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        task = _make_compile_error_task("ce-008")
        task_id = pipeline._write_corpus_record(task, "java_corpus")
        assert task_id == "ce-008"
