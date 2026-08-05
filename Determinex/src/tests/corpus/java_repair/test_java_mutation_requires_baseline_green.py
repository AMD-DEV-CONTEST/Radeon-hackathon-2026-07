"""
Java mutation pipeline baseline enforcement tests.

Verifies that the JavaTaskExtractor refuses to proceed with mutation if the
baseline test run fails. A repo that already has failing tests must not
produce repair tasks (we cannot distinguish pre-existing failures from
mutation-induced failures).

JAVA_REPAIR_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from corpus.code_ingest.java_repair_pipeline import JavaRepairPipeline
from corpus.code_ingest.java_task_extractor import JavaTaskExtractor
from corpus.corpus_manager import CorpusManager

_JAVA_SOURCE = """\
public class Counter {
    private int count = 0;

    public void increment() {
        if (count == null) return;  // obviously wrong: int cannot be null
        count++;
    }

    public int get() {
        return count;
    }
}
"""

_JAVA_WITH_NULL_CHECK = """\
public class Guard {
    public String process(String input) {
        if (input == null) throw new IllegalArgumentException("input must not be null");
        return input.trim();
    }
}
"""


def _make_executor(baseline_passes: bool):
    """Return a fake Maven executor for testing."""
    call_count = {"n": 0}

    def executor(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
        call_count["n"] += 1
        is_baseline = call_count["n"] == 1
        if is_baseline:
            if baseline_passes:
                return (0, "BUILD SUCCESS\nTests run: 5, Failures: 0", "")
            else:
                return (1, "", "BUILD FAILURE\nTests run: 5, Failures: 2, Errors: 0")
        else:
            # Post-mutation run always fails (mutation worked)
            return (1, "", "NullPointerException at Guard.java:3")

    return executor


class TestMutationRequiresBaselineGreen:
    def test_extractor_returns_empty_when_baseline_fails(self, tmp_path):
        """If baseline fails, extract_tasks must return []."""
        # Write a Java file with a null check so mutation candidates exist
        (tmp_path / "Guard.java").write_text(_JAVA_WITH_NULL_CHECK, encoding="utf-8")
        (tmp_path / "pom.xml").write_text(
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>com.test</groupId><artifactId>test</artifactId>"
            "<version>1.0</version></project>",
            encoding="utf-8",
        )
        extractor = JavaTaskExtractor(tmp_path)

        # Patch _run to simulate a failing baseline
        extractor._run = lambda cmd, cwd=None: (1, "", "BUILD FAILURE")  # type: ignore[method-assign]

        tasks = extractor.extract_tasks(max_tasks=5)
        assert tasks == [], "Must return empty list when baseline fails"

    def test_extractor_proceeds_when_baseline_passes(self, tmp_path):
        """If baseline passes AND mutation causes failure, tasks are returned."""
        (tmp_path / "Guard.java").write_text(_JAVA_WITH_NULL_CHECK, encoding="utf-8")
        (tmp_path / "pom.xml").write_text(
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>com.test</groupId><artifactId>test</artifactId>"
            "<version>1.0</version></project>",
            encoding="utf-8",
        )
        extractor = JavaTaskExtractor(tmp_path)

        call_n = {"n": 0}

        def fake_run(cmd, cwd=None):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return (0, "BUILD SUCCESS", "")  # baseline passes
            else:
                return (1, "", "NullPointerException at Guard.java:3")  # mutation fails

        extractor._run = fake_run  # type: ignore[method-assign]

        tasks = extractor.extract_tasks(max_tasks=5)
        # Should have at least one task (one null check in Guard.java)
        assert len(tasks) >= 1

    def test_pipeline_reports_baseline_failure_via_process_result(self, tmp_path):
        """Pipeline process_repo returns tasks=0 when executor signals baseline fail."""
        (tmp_path / "LICENSE").write_text("MIT License", encoding="utf-8")
        src = tmp_path / "src"
        src.mkdir()
        (src / "Guard.java").write_text(_JAVA_WITH_NULL_CHECK, encoding="utf-8")
        (tmp_path / "pom.xml").write_text(
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>com.test</groupId><artifactId>test</artifactId>"
            "<version>1.0</version></project>",
            encoding="utf-8",
        )
        cm = CorpusManager(root=tmp_path / "corpus")

        # Always-failing executor — baseline never passes
        def always_fail(cmd, cwd, timeout):
            return (1, "", "BUILD FAILURE\nTests: 3, Failures: 1")

        pipeline = JavaRepairPipeline(corpus_manager=cm, executor=always_fail)
        result = pipeline.process_repo(tmp_path, "java_corpus")
        assert result.accepted, "Repo should not be rejected at license gate"
        assert result.tasks_extracted == 0

    def test_pipeline_extracts_tasks_when_executor_simulates_success(self, tmp_path):
        """Pipeline extracts tasks when executor: baseline=pass, mutation=fail."""
        (tmp_path / "LICENSE").write_text("MIT License", encoding="utf-8")
        (tmp_path / "Guard.java").write_text(_JAVA_WITH_NULL_CHECK, encoding="utf-8")
        (tmp_path / "pom.xml").write_text(
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>com.test</groupId><artifactId>test</artifactId>"
            "<version>1.0</version></project>",
            encoding="utf-8",
        )
        cm = CorpusManager(root=tmp_path / "corpus")
        executor = _make_executor(baseline_passes=True)
        pipeline = JavaRepairPipeline(corpus_manager=cm, executor=executor)
        result = pipeline.process_repo(tmp_path, "java_corpus")
        assert result.accepted
        assert result.tasks_extracted >= 1

    def test_baseline_failure_message_captured(self, tmp_path):
        """verify_baseline must return (False, error_msg) when build fails."""
        (tmp_path / "pom.xml").write_text(
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>t</groupId><artifactId>t</artifactId>"
            "<version>1</version></project>",
            encoding="utf-8",
        )
        extractor = JavaTaskExtractor(tmp_path)
        extractor._run = lambda cmd, cwd=None: (1, "", "Tests run: 3, Failures: 1, Errors: 0")  # type: ignore[method-assign]

        ok, msg = extractor.verify_baseline()
        assert ok is False
        assert len(msg) > 0
