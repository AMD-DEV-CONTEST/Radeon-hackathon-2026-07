from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MATRIX_SCRIPT = PROJECT_ROOT / "scripts" / "run_experiment_matrix.sh"
COLLECTOR_SCRIPT = PROJECT_ROOT / "scripts" / "collect_rocm_evidence.sh"
APP_SCRIPT = PROJECT_ROOT / "scripts" / "serve_app.sh"
MODEL_SCRIPT = PROJECT_ROOT / "scripts" / "serve_model.sh"


def _model_launcher_environment(
    tmp_path: Path,
    fake_server: Path,
    model: Path,
) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sha256sum = fake_bin / "sha256sum"
    fake_sha256sum.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s  %s\\n' '{'0' * 64}' \"${{@: -1}}\"\n",
        encoding="utf-8",
    )
    fake_sha256sum.chmod(0o700)
    environment = os.environ.copy()
    environment.update(
        {
            "LLAMA_SERVER": str(fake_server),
            "MODEL_PATH": str(model),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )
    return environment


def _collector_provenance_arguments(tmp_path: Path) -> list[str]:
    return [
        "--live-evidence-file",
        str(tmp_path / "live-rocm.log"),
        "--expected-model-sha256",
        "a" * 64,
        "--model-repository",
        "owner/model",
        "--model-revision",
        "b" * 40,
        "--model-license",
        "Apache-2.0",
        "--expected-llama-server-sha256",
        "c" * 64,
        "--llama-cpp-commit",
        "d" * 40,
        "--llama-build",
        "ROCm test build",
        "--python-executable",
        "python3",
    ]


def test_experiment_matrix_declares_the_controlled_a_to_e_sequence() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8")

    expected_rows = (
        'A) thinking="on";  flash_attn="off"; batch_size="256"; '
        'ubatch_size="64";  parallel_slots="1"',
        'B) thinking="off"; flash_attn="off"; batch_size="256"; '
        'ubatch_size="64";  parallel_slots="1"',
        'C) thinking="off"; flash_attn="on";  batch_size="256"; '
        'ubatch_size="64";  parallel_slots="1"',
        'D) thinking="off"; flash_attn="on";  batch_size="512"; '
        'ubatch_size="128"; parallel_slots="1"',
        'E) thinking="off"; flash_attn="on";  batch_size="512"; '
        'ubatch_size="128"; parallel_slots="4"',
    )
    for row in expected_rows:
        assert row in script
    assert 'log_verbosity="5"' in script
    assert 'echo "log_verbosity=${log_verbosity}"' in script


def test_app_launcher_uses_the_source_tree_without_build_isolation() -> None:
    script = APP_SCRIPT.read_text(encoding="utf-8")

    assert 'export PYTHONPATH="${project_dir}/src${PYTHONPATH:+:${PYTHONPATH}}"' in script
    assert "exec python -m radeonstay.main" in script


def test_experiment_matrix_has_safe_dry_run_and_c2_binding() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8")

    assert "--run A|B|C|D|E|all" in script
    assert "--dry-run" in script
    assert "--expected-commit" in script
    assert "--expected-model-sha256" in script
    assert "--expected-llama-server-sha256" in script
    assert "assert_c2_binding" in script
    assert "assert_artifact_binding" in script
    assert "status --porcelain=v1 --untracked-files=all -- ." in script
    assert "c2_binding_status=verified" in script
    assert script.index("if (( dry_run == 1 ))") < script.index(
        'mkdir -m 0700 -- "${output_root}"'
    )


def test_experiment_matrix_preserves_runs_and_reuses_evidence_collector() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8")

    assert 'local run_dir="${output_root}/${experiment}"' in script
    assert 'local evidence_dir="${run_dir}/evidence"' in script
    assert "collect_rocm_evidence.sh" in script
    assert "status=failed stage=${current_stage}" in script
    assert "artifact_retention=preserve_all_outputs_on_failure" in script
    assert "failure_artifacts=preserved" in script
    assert "failed_experiments" in script
    assert "compare_benchmarks.py" in script
    assert "--require-accepted" in script
    for comparison in (
        '"A:B:thinking"',
        '"B:C:flash-attention"',
        '"C:D:batch"',
        '"D:E:parallel"',
    ):
        assert comparison in script


def test_experiment_matrix_collects_live_evidence_before_controlled_shutdown() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8")

    live = script.index('current_stage="collect_live_rocm_evidence"')
    shutdown = script.index('current_stage="controlled_child_shutdown"')
    final = script.index('current_stage="collect_rocm_evidence"')
    assert live < shutdown < final
    assert '--live-evidence-file "${live_evidence_file}"' in script
    assert '--phase live \\' in script
    assert '--phase final \\' in script
    assert script.count('"${evidence_arguments[@]}"') == 2


def test_collector_binds_declared_provenance_and_live_snapshot() -> None:
    script = COLLECTOR_SCRIPT.read_text(encoding="utf-8")

    for field in (
        "expected_model_sha256",
        "model_repository",
        "model_revision",
        "model_license",
        "expected_llama_server_sha256",
        "llama_cpp_commit",
        "llama_build",
        "python_version",
        "requirements_lock_sha256",
        "live_rocm_sha256",
    ):
        assert f'echo "{field}=${{{field}}}"' in script
    assert '[[ "${model_sha256}" != "${expected_model_sha256}" ]]' in script
    assert (
        '[[ "${llama_server_sha256}" != "${expected_llama_server_sha256}" ]]'
        in script
    )
    live_phase = script[
        script.index('if [[ "${collection_phase}" == "live" ]]; then') :
        script.index('if ! grep -Fqx "evidence_log_status=complete"')
    ]
    assert live_phase.index('echo "rocm_smi_end"') < live_phase.index(
        'echo "status=complete"'
    )
    for complete_marker in (
        'grep -Fqx "python_executable=${python_executable_path}"',
        'grep -Fqx "python_version=${python_version}"',
        'grep -Fqx "rocminfo_end"',
        'grep -Fqx "rocm_smi_end"',
    ):
        assert complete_marker in script


def test_matrix_rejects_a_model_that_does_not_match_the_expected_hash(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sha256sum = fake_bin / "sha256sum"
    fake_sha256sum.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s  %s\\n' '{'f' * 64}' \"${{@: -1}}\"\n",
        encoding="utf-8",
    )
    fake_sha256sum.chmod(0o700)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    server = tmp_path / "llama-server"
    server.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    server.chmod(0o700)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    completed = subprocess.run(
        [
            "bash",
            str(MATRIX_SCRIPT),
            "--run-prefix",
            "hash-check",
            "--run",
            "A",
            "--expected-commit",
            "e" * 40,
            "--expected-model-sha256",
            "0" * 64,
            "--expected-llama-server-sha256",
            "1" * 64,
            "--output-root",
            str(tmp_path / "matrix"),
            "--model-file",
            str(model),
            "--model-repository",
            "owner/model",
            "--model-revision",
            "2" * 40,
            "--model-license",
            "Apache-2.0",
            "--llama-server",
            str(server),
            "--llama-cpp-commit",
            "3" * 40,
            "--llama-build",
            "ROCm test build",
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode != 0
    assert "does not match expected" in completed.stderr


def test_experiment_matrix_contains_no_destructive_cleanup() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8").lower()

    forbidden = (
        "rm -rf",
        "rm --",
        "shred ",
        "unlink ",
        "kubectl delete",
        "docker rm",
        "podman rm",
    )
    for command in forbidden:
        assert command not in script


def test_model_launcher_rejects_newline_in_evidence_path(tmp_path: Path) -> None:
    fake_server = tmp_path / "llama\nserver"
    fake_server.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_server.chmod(0o700)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    environment = _model_launcher_environment(tmp_path, fake_server, model)

    completed = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "serve_model.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 2
    assert "must not contain CR or LF" in completed.stderr


def test_model_launcher_rechecks_resolved_evidence_paths(tmp_path: Path) -> None:
    physical = tmp_path / "physical\nroot"
    physical.mkdir()
    safe_link = tmp_path / "safe-model-root"
    safe_link.symlink_to(physical, target_is_directory=True)
    fake_server = physical / "llama-server"
    fake_server.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_server.chmod(0o700)
    (physical / "model.gguf").write_bytes(b"model")
    environment = os.environ.copy()
    environment.update(
        {
            "LLAMA_SERVER": str(safe_link / "llama-server"),
            "MODEL_PATH": str(safe_link / "model.gguf"),
        }
    )

    completed = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "serve_model.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 2
    assert "Resolved LLAMA_SERVER" in completed.stderr


def test_model_launcher_requires_verbose_startup_logging(tmp_path: Path) -> None:
    fake_server = tmp_path / "llama-server"
    fake_server.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"--help\" ]]; then\n"
        "  printf '%s\\n' '--flash-attn MODE --jinja --metrics'\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_server.chmod(0o700)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    environment = _model_launcher_environment(tmp_path, fake_server, model)

    completed = subprocess.run(
        ["bash", str(MODEL_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 2
    assert "does not expose required --log-verbosity" in completed.stderr


def test_model_launcher_enables_and_records_verbose_startup_logging(
    tmp_path: Path,
) -> None:
    captured_args = tmp_path / "captured-args.txt"
    fake_server = tmp_path / "llama-server"
    fake_server.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"--help\" ]]; then\n"
        "  printf '%s\\n' "
        "'--log-verbosity N --flash-attn MODE --jinja --metrics'\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' \"$@\" > \"${FAKE_ARGS_FILE:?}\"\n",
        encoding="utf-8",
    )
    fake_server.chmod(0o700)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    environment = _model_launcher_environment(tmp_path, fake_server, model)
    environment["FAKE_ARGS_FILE"] = str(captured_args)

    completed = subprocess.run(
        ["bash", str(MODEL_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0
    assert "log_verbosity=5" in completed.stdout
    arguments = captured_args.read_text(encoding="utf-8").splitlines()
    option_index = arguments.index("--log-verbosity")
    assert arguments[option_index + 1] == "5"


def test_evidence_collector_rejects_newline_in_artifact_path(tmp_path: Path) -> None:
    placeholder = str(tmp_path / "placeholder")
    completed = subprocess.run(
        [
            "bash",
            str(PROJECT_ROOT / "scripts" / "collect_rocm_evidence.sh"),
            "--run-id",
            "run-1",
            "--output-dir",
            str(tmp_path / "evidence\nforged"),
            *_collector_provenance_arguments(tmp_path),
            "--retrieval-file",
            placeholder,
            "--quality-file",
            placeholder,
            "--benchmark-file",
            placeholder,
            "--monitor-file",
            placeholder,
            "--server-log",
            placeholder,
            "--model-file",
            placeholder,
            "--llama-server",
            placeholder,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 3
    assert "must not contain CR or LF" in completed.stderr


def test_collectors_recheck_resolved_output_paths(tmp_path: Path) -> None:
    physical = tmp_path / "physical\nroot"
    physical.mkdir()
    safe_link = tmp_path / "safe-output-root"
    safe_link.symlink_to(physical, target_is_directory=True)
    placeholder = str(tmp_path / "placeholder")
    collector = subprocess.run(
        [
            "bash",
            str(PROJECT_ROOT / "scripts" / "collect_rocm_evidence.sh"),
            "--run-id",
            "run-1",
            "--output-dir",
            str(safe_link / "evidence"),
            *_collector_provenance_arguments(tmp_path),
            "--retrieval-file",
            placeholder,
            "--quality-file",
            placeholder,
            "--benchmark-file",
            placeholder,
            "--monitor-file",
            placeholder,
            "--server-log",
            placeholder,
            "--model-file",
            placeholder,
            "--llama-server",
            placeholder,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    monitor = subprocess.run(
        [
            "bash",
            str(PROJECT_ROOT / "scripts" / "monitor_rocm.sh"),
            "--run-id",
            "run-1",
            "--output",
            str(safe_link / "monitor.log"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert collector.returncode == 3
    assert "Resolved output path" in collector.stderr
    assert monitor.returncode == 3
    assert "Resolved monitor paths" in monitor.stderr
