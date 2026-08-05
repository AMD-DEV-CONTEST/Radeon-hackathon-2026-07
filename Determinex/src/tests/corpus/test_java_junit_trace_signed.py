"""
Java JUnit corpus trace signing test.

Verifies that Java repair tasks written to the corpus via CorpusManager:
  1. Carry SCHEMA_VERSION
  2. Are HMAC-signed (_sig field present)
  3. Pass HMAC verification
  4. Include Java-specific metadata (language, build_system, failure_type)
  5. Signed records fail verification after tampering

JAVA_CORPUS_LOCK_001 / CORPUS_LICENSE_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from agents.base_agent import SCHEMA_VERSION, CorpusType
from corpus.corpus_manager import CorpusManager


def _make_java_verdict_payload() -> dict:
    return {
        "language": "java",
        "build_system": "maven",
        "framework": "junit5",
        "failure_type": "junit_failure",
        "failing_test": "UserServiceTest#testNullUser",
        "error_message": "NullPointerException at UserService.java:42",
        "mutated_file": "src/main/java/UserService.java",
        "original_snippet": "if (user == null) throw new IllegalArgumentException();",
        "repair_patch": "--- a/UserService.java\n+++ b/UserService.java\n@@ -42,1 +42,1 @@\n-if (false)\n+if (user == null)",
        "validator": "mvn test",
        "verdict": "pass",
    }


class TestJavaJUnitTraceSigning:
    def test_java_trace_has_schema_version(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="java-test-001",
            input_hash="aabbcc001122",
            output_hash="ddeeff334455",
            source_benchmark="java_corpus",
            payload=_make_java_verdict_payload(),
        )
        assert record["schema_version"] == SCHEMA_VERSION

    def test_java_trace_is_hmac_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="java-test-002",
            input_hash="aabbcc001122",
            output_hash="ddeeff334455",
            source_benchmark="java_corpus",
            payload=_make_java_verdict_payload(),
        )
        assert "_sig" in record, "HMAC signature field must be present"
        assert len(record["_sig"]) >= 32, "HMAC signature must be at least 32 chars"

    def test_java_trace_verifies(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="java-test-003",
            input_hash="aabbcc001122",
            output_hash="ddeeff334455",
            source_benchmark="java_corpus",
            payload=_make_java_verdict_payload(),
        )
        assert cm.verify(record) is True, "Valid Java trace must pass HMAC verification"

    def test_tampered_java_trace_fails_verification(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="java-test-004",
            input_hash="aabbcc001122",
            output_hash="ddeeff334455",
            source_benchmark="java_corpus",
            payload=_make_java_verdict_payload(),
        )
        # Tamper with the verdict
        record["verdict"] = "pass"  # change task_id to simulate tampering
        record["task_id"] = "injected-malicious-task"
        assert cm.verify(record) is False, "Tampered record must fail HMAC verification"

    def test_java_metadata_preserved(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        payload = _make_java_verdict_payload()
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="java-test-005",
            input_hash="aabbcc001122",
            output_hash="ddeeff334455",
            source_benchmark="java_corpus",
            payload=payload,
        )
        # Payload is spread into top-level
        assert record.get("language") == "java"
        assert record.get("build_system") == "maven"
        assert record.get("failure_type") == "junit_failure"
        assert record.get("validator") == "mvn test"

    def test_corpus_type_is_code_verdict(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="java-test-006",
            input_hash="aa",
            output_hash="bb",
            source_benchmark="java_corpus",
            payload=_make_java_verdict_payload(),
        )
        assert record["corpus_type"] == CorpusType.CODE_VERDICT.value

    def test_two_different_records_have_different_sigs(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        r1 = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="java-007a",
            input_hash="aa",
            output_hash="bb",
            source_benchmark="java_corpus",
            payload=_make_java_verdict_payload(),
        )
        r2 = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id="java-007b",  # different task_id
            input_hash="aa",
            output_hash="bb",
            source_benchmark="java_corpus",
            payload=_make_java_verdict_payload(),
        )
        assert r1["_sig"] != r2["_sig"], "Different records must have different HMAC signatures"
