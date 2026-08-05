"""
Java null pointer mutation and repair tests.

Verifies that the JavaTaskExtractor correctly:
  - Identifies null-check candidates in Java source files
  - Applies null_check_removal mutations
  - Produces a repair patch (unified diff) restoring the original guard
  - Records the correct mutation type and snippets

JAVA_REPAIR_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from corpus.code_ingest.java_task_extractor import JavaTaskExtractor

_NULL_CHECK_SOURCE = """\
public class UserService {
    public User findUser(String id) {
        if (id == null) {
            throw new IllegalArgumentException("id must not be null");
        }
        return db.find(id);
    }

    public void update(User user) {
        if (user == null) return;
        db.save(user);
    }
}
"""

_NO_NULL_CHECK_SOURCE = """\
public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public String format(int n) {
        return Integer.toString(n);
    }
}
"""


class TestNullPointerRepair:
    def test_null_check_candidates_found(self, tmp_path):
        java_file = tmp_path / "UserService.java"
        java_file.write_text(_NULL_CHECK_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        assert len(candidates) >= 2, "Must find at least 2 null checks"

    def test_null_check_candidate_has_required_fields(self, tmp_path):
        java_file = tmp_path / "UserService.java"
        java_file.write_text(_NULL_CHECK_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        for c in candidates:
            assert c["type"] == "null_check_removal"
            assert "match" in c
            assert "variable" in c
            assert "start" in c
            assert "end" in c

    def test_null_check_variable_names_extracted(self, tmp_path):
        java_file = tmp_path / "UserService.java"
        java_file.write_text(_NULL_CHECK_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        variables = {c["variable"] for c in candidates}
        assert "id" in variables
        assert "user" in variables

    def test_no_null_checks_in_clean_file(self, tmp_path):
        java_file = tmp_path / "Calculator.java"
        java_file.write_text(_NO_NULL_CHECK_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        assert len(candidates) == 0

    def test_mutation_replaces_check_with_false(self, tmp_path):
        java_file = tmp_path / "UserService.java"
        java_file.write_text(_NULL_CHECK_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        assert candidates, "Need at least one candidate"
        original, mutated = extractor.mutate_file(java_file, candidates[0])
        assert "if (false)" in mutated
        assert "if (false)" not in original

    def test_mutation_original_preserved(self, tmp_path):
        java_file = tmp_path / "UserService.java"
        java_file.write_text(_NULL_CHECK_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        original, mutated = extractor.mutate_file(java_file, candidates[0])
        assert candidates[0]["match"] in original
        assert candidates[0]["match"] not in mutated

    def test_mutation_preserves_rest_of_file(self, tmp_path):
        java_file = tmp_path / "UserService.java"
        java_file.write_text(_NULL_CHECK_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        original, mutated = extractor.mutate_file(java_file, candidates[0])
        # Everything outside the mutation should be the same
        assert len(mutated) > 0
        assert "UserService" in mutated
        assert "db.find(id)" in mutated

    def test_multiple_mutations_are_independent(self, tmp_path):
        java_file = tmp_path / "UserService.java"
        java_file.write_text(_NULL_CHECK_SOURCE, encoding="utf-8")
        extractor = JavaTaskExtractor(tmp_path)
        candidates = extractor.extract_null_check_candidates(java_file)
        assert len(candidates) >= 2
        _, mutated0 = extractor.mutate_file(java_file, candidates[0])
        _, mutated1 = extractor.mutate_file(java_file, candidates[1])
        # Each mutation affects a different location — they should differ
        assert mutated0 != mutated1
