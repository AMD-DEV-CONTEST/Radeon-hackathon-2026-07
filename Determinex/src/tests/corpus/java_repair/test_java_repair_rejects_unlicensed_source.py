"""
Java repair pipeline license gate tests.

Verifies that the repair pipeline rejects Java repos without a green-bucket
license before any mutation or corpus write occurs.

JAVA_REPAIR_LOCK_001 / CORPUS_LICENSE_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from corpus.code_ingest.java_repair_pipeline import JavaRepairPipeline
from corpus.corpus_manager import CorpusManager

_JAVA_SOURCE = """\
public class Calc {
    public int add(int a, int b) {
        if (a == null) throw new IllegalArgumentException();
        return a + b;
    }
}
"""

_POM = """\
<project><modelVersion>4.0.0</modelVersion>
<groupId>com.test</groupId><artifactId>test</artifactId>
<version>1.0</version></project>
"""


def _make_repo(tmp_path: Path, license_text: str | None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Calc.java").write_text(_JAVA_SOURCE, encoding="utf-8")
    (repo / "pom.xml").write_text(_POM, encoding="utf-8")
    if license_text is not None:
        (repo / "LICENSE").write_text(license_text, encoding="utf-8")
    return repo


class TestJavaRepairRejectsUnlicensedSource:
    def test_no_license_file_is_rejected(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        repo = _make_repo(tmp_path, license_text=None)
        result = pipeline.process_repo(repo, "java_corpus")
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_gpl_license_is_rejected(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        repo = _make_repo(tmp_path, "GNU GENERAL PUBLIC LICENSE\nVersion 3, June 2007")
        result = pipeline.process_repo(repo, "java_corpus")
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_agpl_license_is_rejected(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        repo = _make_repo(tmp_path, "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3")
        result = pipeline.process_repo(repo, "java_corpus")
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_lgpl_license_is_rejected(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        repo = _make_repo(tmp_path, "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1")
        result = pipeline.process_repo(repo, "java_corpus")
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_mit_license_passes_gate(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        # Executor: baseline=pass, but mutation runs fail (so tasks=0, but gate passed)
        call_n = {"n": 0}

        def executor(cmd, cwd, timeout):
            call_n["n"] += 1
            return (1, "", "BUILD FAILURE") if call_n["n"] > 1 else (0, "BUILD SUCCESS", "")

        pipeline = JavaRepairPipeline(corpus_manager=cm, executor=executor)
        repo = _make_repo(tmp_path, "MIT License")
        result = pipeline.process_repo(repo, "java_corpus")
        assert result.accepted, f"MIT repo must pass license gate; got: {result.rejected_reason}"
        assert result.license_spdx == "MIT"
        assert result.license_bucket == "green"

    def test_apache_license_passes_gate(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        executor = lambda cmd, cwd, timeout: (0, "BUILD SUCCESS", "")
        pipeline = JavaRepairPipeline(corpus_manager=cm, executor=executor)
        repo = _make_repo(tmp_path, "Apache License\nVersion 2.0, January 2004")
        result = pipeline.process_repo(repo, "java_corpus")
        assert result.accepted
        assert result.license_bucket == "green"

    def test_rejected_result_has_zero_tasks(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        repo = _make_repo(tmp_path, license_text=None)
        result = pipeline.process_repo(repo, "java_corpus")
        assert result.tasks_extracted == 0
        assert result.tasks_written == 0

    def test_rejected_result_has_empty_task_ids(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = JavaRepairPipeline(corpus_manager=cm)
        repo = _make_repo(tmp_path, "GPL-3.0")
        result = pipeline.process_repo(repo, "java_corpus")
        assert result.task_ids == []
