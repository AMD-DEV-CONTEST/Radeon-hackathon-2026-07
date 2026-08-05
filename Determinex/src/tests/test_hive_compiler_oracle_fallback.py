from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_wsl2_service_failure_falls_back_to_direct(monkeypatch, tmp_path):
    from hive import compiler

    calls: list[tuple[list[str], str]] = []

    def fake_wsl2(cmd, workspace, lang, timeout, allow_network):
        raise RuntimeError("[Oracle] WSL2 service execution failed: Wsl/Service/0x8007274c")

    def fake_direct(cmd, workspace, lang, timeout, allow_network):
        calls.append((cmd, lang))
        return subprocess.CompletedProcess(cmd, 0, stdout="direct ok", stderr="")

    monkeypatch.setenv("DETERMINEX_REQUIRE_DOCKER", "0")
    monkeypatch.setattr(compiler, "_oracle_backend", lambda: "wsl2")
    monkeypatch.setattr(compiler, "_wsl2_oracle_run", fake_wsl2)
    monkeypatch.setattr(compiler, "_direct_oracle_run", fake_direct)

    result = compiler._docker_run(["cargo", "check"], tmp_path, "rust", 1)

    assert result.returncode == 0
    assert result.stdout == "direct ok"
    assert calls == [(["cargo", "check"], "rust")]


def test_wsl2_missing_toolchain_falls_back_to_direct(monkeypatch, tmp_path):
    from hive import compiler

    calls: list[tuple[list[str], str]] = []

    def fake_wsl2(cmd, workspace, lang, timeout, allow_network):
        return subprocess.CompletedProcess(
            cmd,
            127,
            stdout="env: 'cargo': No such file or directory",
            stderr="",
        )

    def fake_direct(cmd, workspace, lang, timeout, allow_network):
        calls.append((cmd, lang))
        return subprocess.CompletedProcess(cmd, 0, stdout="direct ok", stderr="")

    monkeypatch.setenv("DETERMINEX_REQUIRE_DOCKER", "0")
    monkeypatch.setattr(compiler, "_oracle_backend", lambda: "wsl2")
    monkeypatch.setattr(compiler, "_wsl2_oracle_run", fake_wsl2)
    monkeypatch.setattr(compiler, "_direct_oracle_run", fake_direct)

    result = compiler._docker_run(["cargo", "test"], tmp_path, "rust", 1)

    assert result.returncode == 0
    assert result.stdout == "direct ok"
    assert calls == [(["cargo", "test"], "rust")]


def test_wsl2_no_installed_distribution_falls_back_to_direct(monkeypatch, tmp_path):
    from hive import compiler

    calls: list[tuple[list[str], str]] = []

    no_distro = "W\x00i\x00n\x00d\x00o\x00w\x00s\x00 \x00S\x00u\x00b\x00s\x00y\x00s\x00t\x00e\x00m\x00 \x00f\x00o\x00r\x00 \x00L\x00i\x00n\x00u\x00x\x00 \x00h\x00a\x00s\x00 \x00n\x00o\x00 \x00i\x00n\x00s\x00t\x00a\x00l\x00l\x00e\x00d\x00 \x00d\x00i\x00s\x00t\x00r\x00i\x00b\x00u\x00t\x00i\x00o\x00n\x00s\x00."

    def fake_wsl2(cmd, workspace, lang, timeout, allow_network):
        return subprocess.CompletedProcess(cmd, 1, stdout=no_distro, stderr="")

    def fake_direct(cmd, workspace, lang, timeout, allow_network):
        calls.append((cmd, lang))
        return subprocess.CompletedProcess(cmd, 0, stdout="direct ok", stderr="")

    monkeypatch.setenv("DETERMINEX_REQUIRE_DOCKER", "0")
    monkeypatch.setattr(compiler, "_oracle_backend", lambda: "wsl2")
    monkeypatch.setattr(compiler, "_wsl2_oracle_run", fake_wsl2)
    monkeypatch.setattr(compiler, "_direct_oracle_run", fake_direct)

    result = compiler._docker_run(["cargo", "check"], tmp_path, "rust", 1)

    assert result.returncode == 0
    assert result.stdout == "direct ok"
    assert calls == [(["cargo", "check"], "rust")]


def test_safe_compiler_env_preserves_standard_user_toolchain_bins(monkeypatch, tmp_path):
    from hive import compiler

    fake_home = tmp_path / "home"
    cargo_bin = fake_home / ".cargo" / "bin"
    cargo_bin.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")

    safe = compiler._make_safe_env()

    # os.pathsep, not a literal ';'. The separator is ':' on Linux, so splitting on ';'
    # returned ONE entry containing the whole PATH and the membership check could never
    # pass -- the test asserted a Windows-shaped fact and only ever ran on Windows.
    path_entries = safe["PATH"].split(os.pathsep)
    assert str(cargo_bin) in path_entries
    assert "ANTHROPIC_API_KEY" not in safe


def test_direct_cargo_target_dir_prefers_writable_env_override(monkeypatch, tmp_path):
    from hive import compiler

    target = tmp_path / "cargo-target"
    monkeypatch.setenv("DETERMINEX_HIVE_CARGO_TARGET_DIR", str(target))

    selected = compiler._select_cargo_target_dir()

    assert selected == target
    assert target.is_dir()


def test_executor_correctness_gate_blocks_failed_post_escalation_tests(monkeypatch, tmp_path):
    from hive import executor
    from hive.manifest import ManifestSession, StepRecord

    session = ManifestSession(
        session_id="correctness-gate-test",
        lang="rust",
        md_spec_path="",
        project_root=str(tmp_path),
        correctness_test_harness="tests/correctness.rs",
    )
    step = StepRecord(id=1, instruction="write exact function", target_file="src/lib.rs")
    monkeypatch.setattr(executor, "detect_compile_hack", lambda code: False)
    monkeypatch.setattr(
        executor, "run_correctness_tests", lambda *args: (False, "assertion failed")
    )

    allowed, error = executor._correctness_allows_completion(
        session, step, tmp_path, "pub fn bad() {}"
    )

    assert allowed is False
    assert step.correctness_result == "compile_hacked"
    assert step.quality == "compile_hacked"
    assert "Correctness Test FAIL" in error


def test_builder_retry_context_includes_correctness_harness_for_semantic_failures(tmp_path):
    from hive.manifest import ManifestSession, StepRecord
    from hive.prompt_builder import _build_builder_messages

    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "pkg_semantic"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\n',
        encoding="utf-8",
    )
    harness = tmp_path / "tests" / "correctness.rs"
    harness.parent.mkdir()
    harness.write_text(
        "use pkg_semantic::lane_d_message;\n\n"
        "#[test]\n"
        "fn lane_d_message_matches_spec() {\n"
        '    assert_eq!(lane_d_message(), "determinex lane d rust e2e");\n'
        "}\n",
        encoding="utf-8",
    )
    session = ManifestSession(
        session_id="semantic-retry-test",
        lang="rust",
        md_spec_path="",
        project_root=str(tmp_path),
        correctness_test_harness="tests/correctness.rs",
    )
    step = StepRecord(id=1, instruction="Write lane_d_message.", target_file="src/lib.rs")

    messages = _build_builder_messages(
        session,
        step,
        tmp_path,
        compiler_error="[Correctness Test FAIL] cargo boilerplate without useful assertion tail",
        attempt=1,
    )

    system_msg = messages[0]["content"]
    user_msg = messages[1]["content"]
    assert "Previous attempt compiled but failed correctness tests" in system_msg
    assert "CORRECTNESS TEST HARNESS" in user_msg
    assert 'assert_eq!(lane_d_message(), "determinex lane d rust e2e")' in user_msg


def test_rust_correctness_runner_uses_stable_cargo_test_args(monkeypatch, tmp_path):
    from hive import compiler

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(
        'pub fn lane_d_message() -> String { "determinex lane d rust e2e".to_string() }\n',
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "correctness.rs").write_text(
        "use pkg_semantic::lane_d_message;\n\n"
        "#[test]\n"
        "fn lane_d_message_matches_spec() {\n"
        '    assert_eq!(lane_d_message(), "determinex lane d rust e2e");\n'
        "}\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_docker_run(cmd, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 101, stdout="", stderr="unresolved import")
        return subprocess.CompletedProcess(cmd, 0, stdout="test result: ok", stderr="")

    monkeypatch.setattr(compiler, "_docker_run", fake_docker_run)

    passed, output = compiler.run_correctness_tests(tmp_path, "rust", "tests/correctness.rs")

    assert passed is True
    assert output == "test result: ok"
    assert calls == [["cargo", "test"], ["cargo", "test"]]


def test_adjudication_cosine_is_nonfatal_when_embedder_download_fails(monkeypatch):
    from hive import hardware

    def boom():
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(hardware, "get_adjudication_embedder", boom)

    assert hardware.adjudication_cosine("instruction", "code") == 0.0


def test_executor_detects_backticked_rust_missing_main_error():
    from hive import executor

    rustc_output = "error[E0601]: `main` function not found in crate `pkg`\n"

    assert executor._is_rust_missing_main_error(rustc_output) is True


def test_missing_main_repair_prints_lane_d_message_when_step_requires_it(tmp_path):
    from hive import executor

    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "pkg-semantic"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )

    code = executor._rust_missing_main_repair(
        tmp_path,
        "Write complete src/main.rs that prints lane_d_message followed by one newline.",
    )

    assert (
        code
        == 'use pkg_semantic::lane_d_message;\n\nfn main() {\n    println!("{}", lane_d_message());\n}\n'
    )


def test_docker_required_still_blocks_wsl2_fallback(monkeypatch, tmp_path):
    from hive import compiler

    monkeypatch.setenv("DETERMINEX_REQUIRE_DOCKER", "1")
    monkeypatch.setattr(compiler, "_oracle_backend", lambda: "wsl2")

    with pytest.raises(RuntimeError, match="DETERMINEX_REQUIRE_DOCKER=1"):
        compiler._docker_run(["cargo", "check"], tmp_path, "rust", 1)


def test_wsl2_oracle_run_raises_on_wsl_service_failure(monkeypatch, tmp_path):
    from hive import compiler

    service_failure = (
        "A\x00 \x00c\x00o\x00n\x00n\x00e\x00c\x00t\x00i\x00o\x00n\x00 "
        "attempt failed.\x00\n\x00Error code: Wsl/Service/0x8007274c\x00"
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout=service_failure, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Wsl/Service/0x8007274c"):
        compiler._wsl2_oracle_run(["cargo", "check"], tmp_path, "rust", 1)


def test_empty_rust_main_only_is_compile_hack():
    from hive.compiler import detect_compile_hack

    assert detect_compile_hack("fn main() {}")
    assert detect_compile_hack("\nfn main() {\n}\n")
    assert not detect_compile_hack('fn main() { println!("determinex lane d rust e2e"); }')


def test_daemon_timeout_does_not_wait_for_stuck_monitor():
    from hive.executor import _run_daemon_timeout

    started = time.perf_counter()

    def never_returns():
        time.sleep(5)

    with pytest.raises(concurrent.futures.TimeoutError):
        _run_daemon_timeout(never_returns, 0.05)

    assert time.perf_counter() - started < 1.0


def test_builder_health_preflight_switches_to_exact_ok_fallback(monkeypatch):
    from hive import executor

    class _Message:
        def __init__(self, content: str):
            self.content = content

    class _Choice:
        def __init__(self, content: str):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content: str):
            self.choices = [_Choice(content)]

    calls: list[str] = []

    def fake_api_call(*args, **kwargs):
        model = kwargs["model"]
        calls.append(model)
        if model == "determinex/engineer":
            return _Response("def unrelated_sorting_example(): pass")
        if model == "local/coder":
            return _Response("ok")
        raise AssertionError(f"unexpected model {model!r}")

    monkeypatch.setattr(executor, "api_call", fake_api_call)
    monkeypatch.setattr(executor, "_resolve_model", lambda alias: (f"ollama/{alias}", {}))
    monkeypatch.setattr(executor, "_ollama_extra", lambda model, role, hw_profile=None: {})
    monkeypatch.setattr(executor, "get_hw_profile", lambda: None)

    assignments = {"builder": "determinex/engineer"}
    ok, reason = executor._preflight_builder_health(
        assignments,
        fallback_aliases=["local/coder"],
        timeout=1,
    )

    assert ok is True
    assert assignments["builder"] == "local/coder"
    assert calls == ["determinex/engineer", "local/coder"]
    assert "switched builder" in reason


def test_local_builder_fallback_aliases_use_registered_ollama_tags(monkeypatch):
    """Regression test for a real bug found live 2026-07-02: litellm_config.yaml
    named local fallback tags that did not match the tags actually pulled by
    the desktop setup path, meaning the builder fallback chain could be silently
    non-functional. The active workstation and frontend readiness code use the
    Qwen "-instruct" Ollama tags, so the config values are pinned to those exact
    tags, AND (when an Ollama daemon is reachable) this test
    independently confirms those exact tags are live-registered, so this
    exact class of drift can't silently regress again."""
    from hive import api_client

    monkeypatch.setattr(api_client, "_alias_map", None)
    aliases = api_client._load_alias_map()

    assert aliases["local/coder"]["model"] == "ollama/qwen2.5-coder:1.5b-instruct"
    assert aliases["local/fast"]["model"] == "ollama/qwen2.5-coder:3b-instruct"

    configured_tags = {
        aliases["local/coder"]["model"].removeprefix("ollama/"),
        aliases["local/fast"]["model"].removeprefix("ollama/"),
    }
    try:
        import urllib.request

        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as resp:
            import json

            registered = {m["name"] for m in json.load(resp)["models"]}
    except Exception:
        pytest.skip("no Ollama daemon reachable at localhost:11434 -- skipping live tag check")
        return

    for tag in configured_tags:
        assert (
            any(tag == r or r.startswith(tag + ":") for r in registered)
            or f"{tag}:latest" in registered
        ), (
            f"litellm_config.yaml configures '{tag}' but it is not in the live "
            f"Ollama registry ({sorted(registered)}) -- this is the exact bug "
            f"this test exists to catch."
        )


def test_cloud_only_model_assignments_do_not_require_ollama(monkeypatch):
    from hive import executor

    monkeypatch.setenv("DETERMINEX_ALLOW_CLOUD_FALLBACK", "1")

    assert (
        executor._required_ollama_models(
            {
                "builder": "cloud/deepseek-coder",
                "monitor": "cloud/claude-fast",
                "oracle": "cloud/gemini-flash",
                "architect": "cloud/gpt4o",
            }
        )
        == {}
    )


def test_ollama_model_install_detection_uses_exact_tags():
    from hive import executor

    installed = {
        "determinex-engineer-v11-dsl:latest",
        "qwen2.5-coder:1.5b-instruct",
    }

    assert executor._ollama_model_installed("ollama/determinex-engineer-v11-dsl", installed)
    assert executor._ollama_model_installed("ollama/qwen2.5-coder:1.5b-instruct", installed)
    assert not executor._ollama_model_installed("ollama/qwen2.5-coder:1.5b", installed)


def test_builder_health_preflight_omits_ollama_extra_body_for_cloud(monkeypatch):
    from hive import executor

    class _Message:
        content = "ok"

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    def fake_api_call(*args, **kwargs):
        assert kwargs["model"] == "cloud/deepseek-coder"
        assert kwargs.get("extra_body", {}) == {}
        return _Response()

    monkeypatch.setattr(executor, "api_call", fake_api_call)
    monkeypatch.setattr(executor, "_resolve_model", lambda alias: ("deepseek/deepseek-coder", {}))
    monkeypatch.setattr(executor, "get_hw_profile", lambda: None)

    assignments = {"builder": "cloud/deepseek-coder"}
    ok, reason = executor._preflight_builder_health(assignments, fallback_aliases=[], timeout=1)

    assert ok is True
    assert assignments["builder"] == "cloud/deepseek-coder"
    assert "passed health preflight" in reason
