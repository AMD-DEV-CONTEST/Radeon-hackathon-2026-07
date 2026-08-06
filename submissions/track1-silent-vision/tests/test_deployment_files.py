from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_SCRIPTS = (
    "scripts/start_real_rocm.sh",
    "scripts/setup_amd_real.sh",
    "scripts/amd_real_oneclick.sh",
)


def test_env_example_uses_only_active_settings_and_fixed_phrase_checkpoint():
    from backend.config import Settings

    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    active_keys = {
        line.split("=", 1)[0].strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }

    assert active_keys <= set(Settings.model_fields)
    assert "COMMAND_FEATURE_DIM" not in text
    assert "models/fixed-phrase.pt" in text
    assert "models/command_classifier.pt" not in text


def _run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _base_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    persistence_root = tmp_path / "persistent"
    checkpoint = persistence_root / "models" / "fixed-phrase.pt"
    log_path = tmp_path / "python-calls.jsonl"
    env = os.environ.copy()
    for name in (
        "COMMAND_BACKEND",
        "COMMAND_CLASSIFIER_CHECKPOINT",
        "SV_ROOT",
        "PERSISTENCE_ROOT",
        "TORCH_HOME",
        "PYTHON_BIN",
    ):
        env.pop(name, None)
    env.update(
        {
            "SV_ROOT": str(persistence_root),
            "PERSISTENCE_ROOT": str(persistence_root),
            "PYTHON_CALL_LOG": str(log_path),
        }
    )
    return env, checkpoint, log_path


def _make_logging_python(tmp_path: Path) -> Path:
    executable = tmp_path / "logging-python"
    executable.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            from pathlib import Path
            import sys

            record = {
                "args": sys.argv[1:],
                "backend": os.environ.get("COMMAND_BACKEND"),
                "checkpoint": os.environ.get("COMMAND_CLASSIFIER_CHECKPOINT"),
            }
            if sys.argv[1:] == ["-"]:
                record["stdin"] = sys.stdin.read()
            with Path(os.environ["PYTHON_CALL_LOG"]).open("a", encoding="utf-8") as log:
                log.write(json.dumps(record) + "\\n")
            """
        ),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _read_calls(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("script", OFFICIAL_SCRIPTS)
def test_official_scripts_default_to_torch_with_the_fixed_phrase_checkpoint(
    script, tmp_path
):
    env, checkpoint, log_path = _base_env(tmp_path)
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"synthetic checkpoint")
    env["PYTHON_BIN"] = str(_make_logging_python(tmp_path))

    result = _run(script, env)

    assert result.returncode == 0, result.stderr
    calls = _read_calls(log_path)
    assert calls
    assert {call["backend"] for call in calls} == {"torch"}
    assert {call["checkpoint"] for call in calls} == {str(checkpoint)}


@pytest.mark.parametrize("script", OFFICIAL_SCRIPTS)
def test_official_scripts_fail_closed_before_python_when_checkpoint_is_missing(
    script, tmp_path
):
    env, checkpoint, log_path = _base_env(tmp_path)
    env["PYTHON_BIN"] = str(_make_logging_python(tmp_path))

    result = _run(script, env)

    assert result.returncode != 0
    assert str(checkpoint) in result.stderr
    assert _read_calls(log_path) == []


def test_oneclick_allows_only_an_explicit_visibly_labeled_prototype_recording_mode(
    tmp_path,
):
    env, _, log_path = _base_env(tmp_path)
    env["PYTHON_BIN"] = str(_make_logging_python(tmp_path))
    env["COMMAND_BACKEND"] = "prototype"

    result = _run("scripts/amd_real_oneclick.sh", env)

    assert result.returncode == 0, result.stderr
    assert "recording mode" in result.stdout.lower()
    calls = _read_calls(log_path)
    assert calls
    assert {call["backend"] for call in calls} == {"prototype"}


@pytest.mark.parametrize("script", OFFICIAL_SCRIPTS)
def test_official_scripts_reject_fake_backend(script, tmp_path):
    env, _, log_path = _base_env(tmp_path)
    env["PYTHON_BIN"] = str(_make_logging_python(tmp_path))
    env["COMMAND_BACKEND"] = "fake"

    result = _run(script, env)

    assert result.returncode != 0
    assert "torch or prototype" in result.stderr.lower()
    assert _read_calls(log_path) == []


def _make_fake_python_modules(tmp_path: Path) -> Path:
    module_root = tmp_path / "fake-modules"
    module_root.mkdir()
    (module_root / "torch.py").write_text(
        textwrap.dedent(
            """
            import os

            __version__ = "2.9.1+rocm-test"

            class version:
                _hip = os.environ.get("FAKE_TORCH_HIP", "7.2")
                hip = _hip if _hip else None

            class cuda:
                @staticmethod
                def is_available():
                    return os.environ.get("FAKE_TORCH_AVAILABLE", "1") == "1"

                @staticmethod
                def device_count():
                    return int(os.environ.get("FAKE_TORCH_DEVICE_COUNT", "1"))

                @staticmethod
                def get_device_name(index):
                    if index != 0 or cuda.device_count() < 1:
                        raise RuntimeError("cuda:0 unavailable")
                    return "Synthetic Radeon"

            def device(name):
                if name != "cuda:0":
                    raise RuntimeError("unexpected device")
                return name

            def empty(size, device):
                if device != "cuda:0" or os.environ.get("FAKE_TORCH_ALLOCATE", "1") != "1":
                    raise RuntimeError("cuda:0 allocation failed")
                return object()
            """
        ),
        encoding="utf-8",
    )
    uvicorn = module_root / "uvicorn"
    uvicorn.mkdir()
    (uvicorn / "__init__.py").write_text("", encoding="utf-8")
    (uvicorn / "__main__.py").write_text(
        textwrap.dedent(
            """
            import json
            import os
            from pathlib import Path
            import sys

            Path(os.environ["LAUNCH_RECORD"]).write_text(
                json.dumps({
                    "args": sys.argv[1:],
                    "backend": os.environ.get("COMMAND_BACKEND"),
                    "checkpoint": os.environ.get("COMMAND_CLASSIFIER_CHECKPOINT"),
                }),
                encoding="utf-8",
            )
            """
        ),
        encoding="utf-8",
    )
    return module_root


def _real_python_start_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    env, checkpoint, _ = _base_env(tmp_path)
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"synthetic checkpoint")
    launch_record = tmp_path / "launch.json"
    module_root = _make_fake_python_modules(tmp_path)
    env.update(
        {
            "PYTHON_BIN": sys.executable,
            "PYTHONPATH": os.pathsep.join(
                filter(None, (str(module_root), env.get("PYTHONPATH", "")))
            ),
            "LAUNCH_RECORD": str(launch_record),
        }
    )
    return env, checkpoint, launch_record


def test_start_preflights_hip_and_cuda_zero_before_launch(tmp_path):
    env, checkpoint, launch_record = _real_python_start_env(tmp_path)

    result = _run("scripts/start_real_rocm.sh", env)

    assert result.returncode == 0, result.stderr
    launched = json.loads(launch_record.read_text(encoding="utf-8"))
    assert launched["backend"] == "torch"
    assert launched["checkpoint"] == str(checkpoint)
    assert "cuda:0" in result.stdout


@pytest.mark.parametrize(
    "failure_env",
    [
        {"FAKE_TORCH_HIP": ""},
        {"FAKE_TORCH_AVAILABLE": "0"},
        {"FAKE_TORCH_DEVICE_COUNT": "0"},
        {"FAKE_TORCH_ALLOCATE": "0"},
    ],
)
def test_start_never_launches_when_rocm_or_cuda_zero_preflight_fails(
    failure_env, tmp_path
):
    env, _, launch_record = _real_python_start_env(tmp_path)
    env.update(failure_env)

    result = _run("scripts/start_real_rocm.sh", env)

    assert result.returncode != 0
    assert not launch_record.exists()


def _make_smoke_dispatch_python(tmp_path: Path) -> Path:
    executable = tmp_path / "smoke-python"
    executable.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            from pathlib import Path
            import sys

            args = sys.argv[1:]
            with Path(os.environ["PYTHON_CALL_LOG"]).open("a", encoding="utf-8") as log:
                log.write(json.dumps({"args": args}) + "\\n")
            if args[:2] == ["-m", "pytest"]:
                raise SystemExit(0)
            if args and args[0].endswith("scripts/infer_command_clip.py"):
                print(os.environ["FAKE_INFERENCE_JSON"])
                raise SystemExit(0)
            if args and args[0] == "-":
                real_python = os.environ["REAL_PYTHON"]
                os.execv(real_python, [real_python, *args])
            raise SystemExit(f"unexpected smoke Python invocation: {args}")
            """
        ),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _smoke_env(
    tmp_path: Path, prediction: dict[str, object]
) -> tuple[dict[str, str], Path]:
    env, checkpoint, log_path = _base_env(tmp_path)
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"synthetic checkpoint")
    sample = tmp_path / "mouth-roi.npy"
    sample.write_bytes(b"synthetic NPY")
    module_root = _make_fake_python_modules(tmp_path)
    env.update(
        {
            "COMMAND_CLASSIFIER_CHECKPOINT": str(checkpoint),
            "COMMAND_SMOKE_SAMPLE": str(sample),
            "COMMAND_SMOKE_LANGUAGE": "zh",
            "PYTHON_BIN": str(_make_smoke_dispatch_python(tmp_path)),
            "REAL_PYTHON": sys.executable,
            "PYTHONPATH": os.pathsep.join(
                filter(None, (str(module_root), env.get("PYTHONPATH", "")))
            ),
            "FAKE_INFERENCE_JSON": json.dumps(prediction),
        }
    )
    return env, log_path


@pytest.mark.parametrize("language", ["zh", "en"])
def test_rocm_smoke_runs_phrase_tests_and_a_checkpoint_backed_prediction(
    tmp_path, language
):
    env, log_path = _smoke_env(
        tmp_path,
        {"backend": "torch", "device": "cuda:0", "thresholdSource": "checkpoint"},
    )
    env["COMMAND_SMOKE_LANGUAGE"] = language

    result = _run("scripts/smoke_rocm.sh", env)

    assert result.returncode == 0, result.stderr
    calls = _read_calls(log_path)
    pytest_call = next(call for call in calls if call["args"][:2] == ["-m", "pytest"])
    assert {
        "tests/test_phrase_model.py",
        "tests/test_phrase_checkpoint.py",
        "tests/test_phrase_runtime.py",
    } <= set(pytest_call["args"])
    inference_call = next(
        call
        for call in calls
        if call["args"] and call["args"][0].endswith("scripts/infer_command_clip.py")
    )
    assert "--checkpoint" in inference_call["args"]
    assert "--mouth-roi" in inference_call["args"]
    assert inference_call["args"][-2:] == ["--language", language]


@pytest.mark.parametrize("language", [None, "", "fr"])
def test_rocm_smoke_requires_a_supported_explicit_language(tmp_path, language):
    env, _ = _smoke_env(
        tmp_path,
        {"backend": "torch", "device": "cuda:0", "thresholdSource": "checkpoint"},
    )
    if language is None:
        env.pop("COMMAND_SMOKE_LANGUAGE")
    else:
        env["COMMAND_SMOKE_LANGUAGE"] = language

    result = _run("scripts/smoke_rocm.sh", env)

    assert result.returncode != 0
    assert "COMMAND_SMOKE_LANGUAGE must be zh or en" in result.stderr


def test_rocm_smoke_fails_if_prediction_is_not_on_torch_cuda_zero(tmp_path):
    env, _ = _smoke_env(
        tmp_path,
        {"backend": "torch", "device": "cpu", "thresholdSource": "checkpoint"},
    )

    result = _run("scripts/smoke_rocm.sh", env)

    assert result.returncode != 0
    assert "cuda:0" in result.stderr


@pytest.mark.parametrize("script", (*OFFICIAL_SCRIPTS, "scripts/smoke_rocm.sh"))
def test_deployment_scripts_have_valid_shell_syntax(script):
    result = subprocess.run(
        ["bash", "-n", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
