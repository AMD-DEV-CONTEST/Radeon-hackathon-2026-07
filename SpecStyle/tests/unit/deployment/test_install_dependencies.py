"""Tests for AMD dependency installer torch-preservation contract."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[3] / "deployment/amd/scripts/install_dependencies.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_dependencies", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load_installer()


def fingerprints(marker: str = "a") -> dict[str, str]:
    return {
        "torch": "2.9.1",
        "torch_hip": "7.2.1",
        "torch_binary_sha256": "d" * 64,
        "torch_file_sha256": marker * 64,
        "torch_metadata_sha256": "b" * 64,
        "torch_record_sha256": "c" * 64,
    }


def test_lock_excludes_forbidden_packages() -> None:
    planned = installer.locked_requirements()
    assert planned
    assert all("torch" not in item.lower() for item in planned)
    assert installer.lock_sha() == installer.lock_sha()
    with pytest.raises(ValueError):
        installer.locked_requirements({"torch": "2.9.1"})


@pytest.mark.parametrize(
    "name",
    (
        "--extra-index-url=https://attacker.invalid/simple",
        "name==other",
        "https://attacker.invalid/package",
        "line\nbreak",
    ),
)
def test_lock_rejects_distribution_names_that_can_change_pip_argv(name: str) -> None:
    with pytest.raises(ValueError, match="invalid dependency name"):
        installer.locked_requirements({name: "1.0.0"})


def test_lock_covers_verified_amd_ui_runtime() -> None:
    assert installer.DEPENDENCIES["gradio"] == "6.15.1"
    assert installer.DEPENDENCIES["gradio-client"] == "2.5.0"
    assert installer.DEPENDENCIES["Pillow"] == "12.3.0"
    assert installer.DEPENDENCIES["python-multipart"] == "0.0.32"
    assert installer.DEPENDENCIES["starlette"] == "1.3.1"
    assert installer.DEPENDENCIES["importlib-metadata"] == "9.0.0"
    assert installer.DEPENDENCIES["peft"] == "0.18.1"
    assert {
        "Brotli",
        "groovy",
        "hf-gradio",
        "safehttpx",
    }.issubset(installer.DEPENDENCIES)
    assert len(installer.DEPENDENCIES) >= 60


def test_build_pip_command_uses_no_deps_and_refuses_torch() -> None:
    command = installer.build_pip_command(["diffusers==0.39.0", "Pillow==11.3.0"])
    assert command[:6] == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
    ]
    assert "--no-deps" in command
    assert "diffusers==0.39.0" in command
    with pytest.raises(ValueError):
        installer.build_pip_command(["torch==2.9.1"])


def test_dry_run_does_not_invoke_pip(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def boom(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("pip must not run in dry-run")

    monkeypatch.setattr(
        installer,
        "packages_to_install",
        lambda _deps=None: (["diffusers==0.39.0"], []),
    )
    result, code = installer.install_dependencies(
        dry_run=True,
        require_torch=True,
        import_torch=lambda: object(),
        fingerprints=lambda _torch: fingerprints("a"),
        runner=boom,
    )
    assert code == 0
    assert result["status"] == "PASS"
    assert result["reason_code"] == "DRY_RUN"
    assert result["installed"] == ["diffusers==0.39.0"]
    assert result["torch_unchanged"] is True
    assert calls == []


def test_install_fails_when_torch_drifts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        installer,
        "packages_to_install",
        lambda _deps=None: (["diffusers==0.39.0"], []),
    )
    monkeypatch.setattr(
        installer, "current_versions", lambda _names: {"diffusers": "0.39.0"}
    )
    markers = iter(["a", "z"])

    def runner(command, **_kwargs):
        assert "diffusers==0.39.0" in command
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result, code = installer.install_dependencies(
        require_torch=True,
        import_torch=lambda: object(),
        fingerprints=lambda _torch: fingerprints(next(markers)),
        runner=runner,
    )
    assert code == 2
    assert result["status"] == "FAIL"
    assert result["reason_code"] == "TORCH_DRIFT"


def test_install_succeeds_when_torch_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    planned = list(installer.DEPENDENCIES)
    monkeypatch.setattr(
        installer,
        "packages_to_install",
        lambda _deps=None: (
            [f"{name}=={installer.DEPENDENCIES[name]}" for name in planned],
            [],
        ),
    )
    monkeypatch.setattr(
        installer,
        "current_versions",
        lambda _names: dict(installer.DEPENDENCIES),
    )
    seen: list[list[str]] = []

    def runner(command, **_kwargs):
        seen.append(list(command))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    result, code = installer.install_dependencies(
        repo_sha="deadbeef",
        require_torch=True,
        import_torch=lambda: object(),
        fingerprints=lambda _torch: fingerprints("a"),
        runner=runner,
    )
    assert code == 0
    assert result["status"] == "PASS"
    assert result["repo_sha"] == "deadbeef"
    assert result["torch_unchanged"] is True
    assert result["torch_before"] == result["torch_after"]
    assert seen and "--no-deps" in seen[0]
    assert set(result["schema_version"] for _ in [0]) == {1}
    assert set(result) == installer.SCHEMA_KEYS


def test_missing_torch_is_hard_failure() -> None:
    result, code = installer.install_dependencies(
        require_torch=True,
        import_torch=lambda: (_ for _ in ()).throw(ImportError("no torch")),
        fingerprints=lambda _torch: fingerprints("a"),
        runner=lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert code == 2
    assert result["reason_code"] == "TORCH_MISSING"


def test_pip_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        installer,
        "packages_to_install",
        lambda _deps=None: (["Pillow==11.3.0"], []),
    )

    def runner(_command, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    result, code = installer.install_dependencies(
        require_torch=True,
        import_torch=lambda: object(),
        fingerprints=lambda _torch: fingerprints("a"),
        runner=runner,
    )
    assert code == 2
    assert result["reason_code"] == "PIP_FAILED"


def test_install_fails_when_pip_check_finds_broken_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        installer,
        "packages_to_install",
        lambda _deps=None: (["diffusers==0.39.0"], []),
    )
    monkeypatch.setattr(
        installer,
        "current_versions",
        lambda _names: dict(installer.DEPENDENCIES),
    )

    def runner(command, **_kwargs):
        failed = command[-1] == "check"
        return SimpleNamespace(
            returncode=1 if failed else 0,
            stdout=(
                "gradio 4.44.1 has requirement pillow<11, but you have pillow 11.3.0."
                if failed
                else ""
            ),
            stderr="",
        )

    result, code = installer.install_dependencies(
        require_torch=True,
        import_torch=lambda: object(),
        fingerprints=lambda _torch: fingerprints("a"),
        runner=runner,
    )

    assert code == 2
    assert result["reason_code"] == "PIP_CHECK_FAILED"
    assert result["pip_check_command"][-3:] == ["-m", "pip", "check"]


def test_install_records_but_ignores_external_pip_check_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        installer,
        "packages_to_install",
        lambda _deps=None: ([], list(installer.locked_requirements())),
    )
    monkeypatch.setattr(
        installer,
        "current_versions",
        lambda _names: dict(installer.DEPENDENCIES),
    )

    def runner(command, **_kwargs):
        assert command[-1] == "check"
        return SimpleNamespace(
            returncode=1,
            stdout=(
                "cupy-cuda12x 14.0.1 has requirement numpy>=2.0, "
                "but you have numpy 1.26.4.\n"
                "vllm 0.16.1 has requirement pydantic>=2.12.0, "
                "but you have pydantic 2.11.10.\n"
            ),
            stderr="",
        )

    result, code = installer.install_dependencies(
        require_torch=True,
        import_torch=lambda: object(),
        fingerprints=lambda _torch: fingerprints("a"),
        runner=runner,
    )

    assert code == 0
    assert result["pip_check_external_conflicts"] == 2


def test_install_fails_closed_on_unparseable_pip_check_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        installer,
        "packages_to_install",
        lambda _deps=None: ([], list(installer.locked_requirements())),
    )
    monkeypatch.setattr(
        installer,
        "current_versions",
        lambda _names: dict(installer.DEPENDENCIES),
    )

    result, code = installer.install_dependencies(
        require_torch=True,
        import_torch=lambda: object(),
        fingerprints=lambda _torch: fingerprints("a"),
        runner=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="unexpected resolver output",
            stderr="",
        ),
    )

    assert code == 2
    assert result["reason_code"] == "PIP_CHECK_FAILED"


def test_install_runs_pip_check_when_every_pin_is_already_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        installer,
        "packages_to_install",
        lambda _deps=None: ([], list(installer.locked_requirements())),
    )
    monkeypatch.setattr(
        installer,
        "current_versions",
        lambda _names: dict(installer.DEPENDENCIES),
    )
    seen: list[list[str]] = []

    def runner(command, **_kwargs):
        seen.append(list(command))
        return SimpleNamespace(
            returncode=0, stdout="No broken requirements found.", stderr=""
        )

    result, code = installer.install_dependencies(
        require_torch=True,
        import_torch=lambda: object(),
        fingerprints=lambda _torch: fingerprints("a"),
        runner=runner,
    )

    assert code == 0
    assert seen == [[sys.executable, "-m", "pip", "check"]]
    assert result["pip_check_command"] == seen[0]


def test_cli_writes_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        installer,
        "install_dependencies",
        lambda **_kwargs: (
            {
                "schema_version": 1,
                "status": "PASS",
                "reason_code": "DRY_RUN",
                "repo_sha": None,
                "lock_sha": "d" * 64,
                "planned": [],
                "installed": [],
                "skipped": [],
                "torch_before": None,
                "torch_after": None,
                "torch_unchanged": False,
                "pip_command": [],
            },
            0,
        ),
    )
    out = tmp_path / "evidence" / "deps.json"
    code = installer.main(["--dry-run", "--json-out", str(out)])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["status"] == "PASS"
    assert out.stat().st_mode & 0o777 == 0o600
