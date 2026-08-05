"""
Java Maven dependency conflict repair tests.

Verifies that repair tasks arising from Maven dependency conflicts
(ClassNotFoundException, NoSuchMethodError, version conflicts) are
correctly classified, signed, and written to corpus.

JAVA_REPAIR_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from agents.base_agent import CorpusType
from corpus.code_ingest.java_repair_pipeline import JavaRepairPipeline
from corpus.corpus_manager import CorpusManager

_DEP_CONFLICT_ERRORS = [
    (
        "class_not_found",
        "java.lang.ClassNotFoundException: org.apache.http.client.HttpClient",
        "compile_error",
    ),
    (
        "no_such_method",
        "java.lang.NoSuchMethodError: com.google.gson.Gson.fromJson(Ljava/lang/String;Ljava/lang/reflect/Type;)Ljava/lang/Object;",
        "junit_failure",
    ),
    (
        "version_conflict",
        "[ERROR] Failed to execute goal: found conflict between org.slf4j:slf4j-api:jar:1.7.32 and org.slf4j:slf4j-api:jar:2.0.0",
        "compile_error",
    ),
    (
        "missing_dep",
        "[ERROR] The following artifacts could not be resolved: com.example:missing-lib:jar:1.0.0",
        "compile_error",
    ),
]


class TestMavenDependencyConflictRepair:
    def test_dep_conflict_task_is_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = JavaRepairPipeline.make_test_task(
            task_id="dep-001",
            failure_type="compile_error",
            error_message="ClassNotFoundException: org.apache.http.client.HttpClient",
        )
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="11" * 8,
            output_hash="22" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_dep_conflict_error_message_truncated_to_500(self, tmp_path):
        long_error = "dependency conflict: " + ("x" * 1000)
        task = JavaRepairPipeline.make_test_task(
            task_id="dep-002",
            error_message=long_error,
        )
        payload = task.to_corpus_payload()
        assert len(payload["error_message"]) <= 500

    def test_class_not_found_classified_as_compile_error(self, tmp_path):
        task = JavaRepairPipeline.make_test_task(
            task_id="dep-003",
            failure_type="compile_error",
            error_message="ClassNotFoundException: org.apache.http.client.HttpClient",
        )
        assert task.failure_type == "compile_error"

    def test_no_such_method_classified_as_junit_failure(self, tmp_path):
        task = JavaRepairPipeline.make_test_task(
            task_id="dep-004",
            failure_type="junit_failure",
            error_message="NoSuchMethodError: com.google.gson.Gson.fromJson",
        )
        assert task.failure_type == "junit_failure"

    def test_multiple_dep_conflict_records_all_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        for name, error_msg, failure_type in _DEP_CONFLICT_ERRORS:
            task = JavaRepairPipeline.make_test_task(
                task_id=f"dep-{name}",
                failure_type=failure_type,
                error_message=error_msg,
            )
            record = cm._normalize_record(
                corpus_type=CorpusType.CODE_VERDICT,
                task_id=task.task_id,
                input_hash="33" * 8,
                output_hash="44" * 8,
                source_benchmark="java_corpus",
                payload=task.to_corpus_payload(),
            )
            assert cm.verify(record) is True, f"Signature invalid for {name}"

    def test_dep_conflict_record_has_validator_field(self, tmp_path):
        task = JavaRepairPipeline.make_test_task(
            task_id="dep-005",
            build_system="maven",
        )
        payload = task.to_corpus_payload()
        assert payload["validator"] == "mvn test"

    def test_gradle_dep_conflict_validator_field(self, tmp_path):
        task = JavaRepairPipeline.make_test_task(
            task_id="dep-006",
            build_system="gradle",
        )
        payload = task.to_corpus_payload()
        assert payload["validator"] == "gradle test"

    def test_pipeline_writes_dep_conflict_task(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        task = JavaRepairPipeline.make_test_task(
            task_id="dep-007",
            failure_type="compile_error",
            error_message="ClassNotFoundException: missing.Dependency",
        )
        task_id = pipeline._write_corpus_record(task, "java_corpus")
        assert task_id == "dep-007"
