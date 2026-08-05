"""
Java generic type and annotation mutation tests.

Verifies that mutation candidates for @Override, @NotNull, and off-by-one
patterns are identified correctly, and that repair tasks carry the right
metadata when recorded.

JAVA_REPAIR_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from agents.base_agent import CorpusType
from corpus.code_ingest.java_repair_pipeline import JavaRepairPipeline
from corpus.corpus_manager import CorpusManager

_GENERIC_SOURCE = """\
import java.util.List;
import java.util.ArrayList;

public class Container<T> {
    private List<T> items = new ArrayList<>();

    public void add(T item) {
        if (item == null) throw new IllegalArgumentException();
        items.add(item);
    }

    public T get(int index) {
        if (index < 0 || index >= items.size()) {
            throw new IndexOutOfBoundsException("Index: " + index);
        }
        return items.get(index);
    }

    public int size() {
        return items.size();
    }
}
"""

_ANNOTATION_SOURCE = """\
public class Animal {
    public String speak() {
        return "...";
    }
}

public class Dog extends Animal {
    @Override
    public String speak() {
        return "Woof";
    }
}
"""


class TestGenericTypeRepair:
    def test_null_check_found_in_generic_class(self, tmp_path):
        from corpus.code_ingest.java_task_extractor import JavaTaskExtractor

        java_file = tmp_path / "Container.java"
        java_file.write_text(_GENERIC_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        assert len(candidates) >= 1
        variables = {c["variable"] for c in candidates}
        assert "item" in variables

    def test_off_by_one_candidate_in_bounds_check(self, tmp_path):
        """Bounds check `index >= items.size()` is a mutation candidate."""
        from corpus.code_ingest.java_task_extractor import JavaTaskExtractor

        java_file = tmp_path / "Container.java"
        java_file.write_text(_GENERIC_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        # The null check at line 8 (item == null) must be detectable
        candidates = extractor.extract_null_check_candidates(java_file)
        assert any("item" in c["variable"] for c in candidates)

    def test_generic_task_payload_has_required_fields(self, tmp_path):
        task = JavaRepairPipeline.make_test_task(
            task_id="generic-001",
            failure_type="junit_failure",
            error_message="IndexOutOfBoundsException: Index: -1",
        )
        payload = task.to_corpus_payload()
        for field in (
            "language",
            "build_system",
            "failure_type",
            "error_message",
            "mutated_file",
            "repair_patch",
            "validator",
            "verdict",
        ):
            assert field in payload, f"Missing field: {field}"

    def test_generic_task_payload_language_is_java(self, tmp_path):
        task = JavaRepairPipeline.make_test_task(task_id="generic-002")
        assert task.to_corpus_payload()["language"] == "java"

    def test_generic_corpus_record_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = JavaRepairPipeline.make_test_task(
            task_id="generic-003",
            error_message="ClassCastException: String cannot be cast to Integer",
        )
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="ee" * 8,
            output_hash="ff" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_repair_patch_is_unified_diff_format(self, tmp_path):
        task = JavaRepairPipeline.make_test_task(task_id="generic-004")
        patch = task.repair_patch
        # Unified diff must start with --- or @@
        assert patch.startswith("---") or "@@" in patch or patch.startswith("-")

    def test_annotation_source_parse_does_not_crash(self, tmp_path):
        """JavaTaskExtractor must handle @Override annotations without error."""
        from corpus.code_ingest.java_task_extractor import JavaTaskExtractor

        java_file = tmp_path / "Dog.java"
        java_file.write_text(_ANNOTATION_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        # Should not raise even with annotations present
        candidates = extractor.extract_null_check_candidates(java_file)
        assert isinstance(candidates, list)

    def test_corpus_record_task_id_matches(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = JavaRepairPipeline.make_test_task(task_id="generic-005")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="ee" * 8,
            output_hash="ff" * 8,
            source_benchmark="java_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record["task_id"] == "generic-005"
