"""
Java Spring configuration repair tests.

Verifies that Spring Boot configuration failure patterns
(missing beans, circular dependencies, property binding errors)
are classified correctly and produce signed corpus records.

Also verifies that Spring pom.xml with legitimate spring-boot-starter
dependencies is not flagged as malicious.

JAVA_REPAIR_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from agents.base_agent import CorpusType
from agents.prompt_injection_detector import is_safe
from corpus.code_ingest.java_repair_pipeline import JavaRepairPipeline
from corpus.corpus_manager import CorpusManager

_SPRING_ERRORS = [
    (
        "missing_bean",
        "org.springframework.beans.factory.NoSuchBeanDefinitionException: No qualifying bean of type 'com.example.UserRepository'",
    ),
    (
        "circular_dep",
        "The dependencies of some of the beans in the application context form a cycle:\nuserService -> userRepository -> userService",
    ),
    (
        "property_binding",
        "Failed to bind properties under 'spring.datasource.url' to java.lang.String",
    ),
    (
        "application_context",
        "org.springframework.context.ApplicationContextException: Unable to start embedded container",
    ),
]

_SPRING_POM = """\
<project>
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.0</version>
  </parent>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
  </dependencies>
</project>
"""


class TestSpringConfigRepair:
    def test_spring_pom_not_flagged_as_malicious(self):
        """Legitimate Spring Boot pom.xml must pass injection scan."""
        assert is_safe(_SPRING_POM, source="pom.xml:spring-boot"), (
            "Legitimate Spring Boot pom.xml must not be flagged"
        )

    def test_missing_bean_error_task_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = JavaRepairPipeline.make_test_task(
            task_id="spring-001",
            failure_type="junit_failure",
            error_message=_SPRING_ERRORS[0][1],
            framework="spring-boot",
        )
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="55" * 8,
            output_hash="66" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_circular_dep_error_task_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = JavaRepairPipeline.make_test_task(
            task_id="spring-002",
            failure_type="junit_failure",
            error_message=_SPRING_ERRORS[1][1],
        )
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="55" * 8,
            output_hash="66" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_all_spring_errors_produce_signed_records(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        for name, error_msg in _SPRING_ERRORS:
            task = JavaRepairPipeline.make_test_task(
                task_id=f"spring-{name}",
                failure_type="junit_failure",
                error_message=error_msg,
            )
            record = cm._normalize_record(
                corpus_type=CorpusType.CODE_VERDICT,
                task_id=task.task_id,
                input_hash="77" * 8,
                output_hash="88" * 8,
                source_benchmark="java_corpus",
                payload=task.to_corpus_payload(),
            )
            assert cm.verify(record) is True, f"Signature invalid for spring-{name}"

    def test_spring_error_truncated_correctly(self):
        long_stack = "org.springframework.beans.factory.BeanCreationException: " + "x" * 600
        task = JavaRepairPipeline.make_test_task(
            task_id="spring-truncate",
            error_message=long_stack,
        )
        payload = task.to_corpus_payload()
        assert len(payload["error_message"]) <= 500

    def test_spring_record_has_all_required_fields(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = JavaRepairPipeline.make_test_task(
            task_id="spring-fields",
            failure_type="junit_failure",
            error_message="NoSuchBeanDefinitionException: UserService",
        )
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="99" * 8,
            output_hash="aa" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        for field in (
            "schema_version",
            "corpus_type",
            "task_id",
            "_sig",
            "language",
            "build_system",
            "failure_type",
        ):
            assert field in record, f"Missing field: {field}"
