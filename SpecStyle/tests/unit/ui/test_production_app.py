"""Production Gradio launcher composition and filesystem contracts."""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from specstyle.errors import DomainError, InfrastructureError


def _trusted_roots(runtime: Path) -> None:
    runtime.mkdir(mode=0o700)
    for name in ("config", "evidence", "models"):
        (runtime / name).mkdir(mode=0o700)


def test_runtime_paths_require_trusted_inputs_before_creating_mutable_roots(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_app import production_runtime_paths

    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (runtime / "config").mkdir(mode=0o700)
    (runtime / "models").mkdir(mode=0o700)

    with pytest.raises(DomainError, match="evidence"):
        production_runtime_paths(runtime)

    assert not (runtime / "jobs").exists()
    assert not (runtime / "tmp").exists()


def test_runtime_paths_create_distinct_private_product_directories(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_app import production_runtime_paths

    runtime = tmp_path / "runtime"
    _trusted_roots(runtime)

    paths = production_runtime_paths(runtime)

    values = tuple(Path(getattr(paths, field)) for field in paths.__slots__)
    identities = {(path.stat().st_dev, path.stat().st_ino) for path in values}
    assert len(identities) == 8
    for path in values[3:]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
        assert path.stat().st_uid == os.geteuid()


def test_build_services_borrows_then_closes_bootstrap_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_app

    runtime = tmp_path / "runtime"
    _trusted_roots(runtime)
    paths = production_app.production_runtime_paths(runtime)
    context, base, bound = object(), object(), object()
    borrowed: list[int] = []

    def bootstrap(*fds: int) -> object:
        borrowed.extend(fds)
        assert all(os.fstat(fd).st_ino > 0 for fd in fds)
        return context

    monkeypatch.setattr(
        production_app, "load_production_ui_compiler_context", bootstrap
    )
    monkeypatch.setattr(
        production_app,
        "load_production_context_config",
        lambda *_fds: object(),
        raising=False,
    )
    monkeypatch.setattr(
        production_app,
        "require_validated_production_threshold",
        lambda _context: None,
        raising=False,
    )
    monkeypatch.setattr(
        production_app, "build_default_services", lambda candidate: base
    )
    monkeypatch.setattr(
        production_app,
        "bind_production_run_one_services",
        lambda candidate, candidate_paths: bound,
    )

    assert production_app.build_production_ui_services(paths) is bound
    assert len(borrowed) == 3
    for fd in borrowed:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_build_services_keeps_compiler_but_disables_unvalidated_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_app

    runtime = tmp_path / "runtime"
    _trusted_roots(runtime)
    paths = production_app.production_runtime_paths(runtime)
    context_config, compiler, base, unavailable = (object() for _ in range(4))

    monkeypatch.setattr(
        production_app,
        "load_production_context_config",
        lambda *_fds: context_config,
        raising=False,
    )
    monkeypatch.setattr(
        production_app,
        "load_production_ui_compiler_context",
        lambda *_fds: compiler,
    )
    monkeypatch.setattr(
        production_app,
        "build_default_services",
        lambda candidate: base if candidate is compiler else pytest.fail("compiler"),
    )

    def reject(candidate: object) -> None:
        assert candidate is context_config
        raise DomainError("PRODUCTION_THRESHOLD_NOT_VALIDATED")

    monkeypatch.setattr(
        production_app,
        "require_validated_production_threshold",
        reject,
        raising=False,
    )
    monkeypatch.setattr(
        production_app,
        "bind_production_run_one_services",
        lambda *_args: pytest.fail("normal Production must stay unbound"),
    )
    monkeypatch.setattr(
        production_app,
        "bind_unavailable_production_services",
        lambda candidate, reason: (
            unavailable
            if candidate is base and reason == "PRODUCTION_THRESHOLD_NOT_VALIDATED"
            else pytest.fail("unavailable binding")
        ),
        raising=False,
    )

    assert production_app.build_production_ui_services(paths) is unavailable


def test_build_services_closes_opened_descriptor_when_later_open_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_app

    runtime = tmp_path / "runtime"
    _trusted_roots(runtime)
    paths = production_app.production_runtime_paths(runtime)
    real_open = production_app._open_directory
    opened: list[int] = []
    primary = InfrastructureError("second open failed")

    def fail_second(path: Path) -> int:
        if opened:
            raise primary
        descriptor = real_open(path)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(production_app, "_open_directory", fail_second)

    with pytest.raises(InfrastructureError) as raised:
        production_app.build_production_ui_services(paths)

    assert raised.value is primary
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_public_bind_requires_auth_and_uses_restricted_gradio_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_app

    runtime = tmp_path / "runtime"
    _trusted_roots(runtime)
    paths = production_app.production_runtime_paths(runtime)
    services, calls = object(), []
    monkeypatch.setattr(production_app, "production_runtime_paths", lambda _: paths)
    monkeypatch.setattr(
        production_app, "build_production_ui_services", lambda _: services
    )
    monkeypatch.setattr(
        production_app,
        "launch_app",
        lambda candidate, **kwargs: calls.append((candidate, kwargs)) or "launched",
    )

    with pytest.raises(DomainError, match="authentication"):
        production_app.launch_production_ui(runtime, host="0.0.0.0", environ={})
    result = production_app.launch_production_ui(
        runtime,
        host="0.0.0.0",
        port=7860,
        environ={
            "SPECSTYLE_UI_USERNAME": "reviewer",
            "SPECSTYLE_UI_PASSWORD": "a-long-random-password",
        },
    )

    assert result == "launched"
    assert calls[0][0] is services
    kwargs = calls[0][1]
    assert kwargs["server_name"] == "0.0.0.0"
    assert kwargs["server_port"] == 7860
    assert kwargs["share"] is False
    assert kwargs["auth"] == ("reviewer", "a-long-random-password")
    assert kwargs["allowed_paths"] == [str(paths.export_root)]
    assert str(paths.config_root) in kwargs["blocked_paths"]
    assert kwargs["max_file_size"] == "32mb"


def test_local_bind_does_not_require_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_app

    runtime = tmp_path / "runtime"
    _trusted_roots(runtime)
    paths = production_app.production_runtime_paths(runtime)
    monkeypatch.setattr(production_app, "production_runtime_paths", lambda _: paths)
    monkeypatch.setattr(
        production_app, "build_production_ui_services", lambda _: object()
    )
    captured = {}
    monkeypatch.setattr(
        production_app,
        "launch_app",
        lambda _services, **kwargs: captured.update(kwargs),
    )

    production_app.launch_production_ui(runtime, environ={})

    assert captured["server_name"] == "127.0.0.1"
    assert captured["auth"] is None


def test_amd_launcher_is_a_thin_production_entrypoint() -> None:
    launcher = (
        Path(__file__).parents[3]
        / "deployment"
        / "amd"
        / "scripts"
        / "launch_production_ui.py"
    )

    text = launcher.read_text(encoding="ascii")
    assert "specstyle.ui.production_app import main" in text
    assert "launch_production_ui_smoke" not in text


def test_preview_bootstrap_failure_degrades_without_blocking_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_app

    runtime = tmp_path / "runtime"
    _trusted_roots(runtime)
    paths = production_app.production_runtime_paths(runtime)
    (runtime / "preview-config").mkdir(mode=0o700)
    preview_paths = production_app.preview_runtime_paths(runtime)
    base = object()
    fallback = object()
    monkeypatch.setattr(
        production_app, "load_production_ui_compiler_context", lambda *_args: object()
    )
    monkeypatch.setattr(production_app, "build_default_services", lambda _: base)
    monkeypatch.setattr(
        production_app, "bind_production_run_one_services", lambda *_args: base
    )
    monkeypatch.setattr(
        production_app,
        "bind_preview_run_one_services",
        lambda *_args: (_ for _ in ()).throw(DomainError("bad preview")),
    )
    monkeypatch.setattr(
        production_app, "reconcile_preview_ui_display", lambda _paths: ()
    )
    monkeypatch.setattr(
        production_app,
        "bind_unavailable_preview_services",
        lambda candidate, reason: (
            fallback
            if candidate is base and reason == "PREVIEW_UNAVAILABLE"
            else pytest.fail("invalid fallback")
        ),
    )
    monkeypatch.setattr(
        production_app,
        "bind_unavailable_preview_wall_services",
        lambda candidate, reason: (
            candidate
            if candidate is fallback and reason == "PREVIEW_UNAVAILABLE"
            else pytest.fail("invalid wall fallback")
        ),
    )

    result, exposed_paths = production_app.bind_optional_preview_services(
        base, preview_paths
    )

    assert result is fallback
    assert exposed_paths is None
    allowed, blocked = production_app._gradio_paths(paths, preview_paths, exposed_paths)
    assert str(preview_paths.display_root) not in allowed
    assert str(preview_paths.preview_config_root) in blocked
    assert str(preview_paths.evidence_root) in blocked
    assert str(preview_paths.staging_root) in blocked
    assert str(preview_paths.display_root) in blocked


def test_launch_allowlists_preview_display_and_blocks_private_preview_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_app

    runtime = tmp_path / "runtime"
    _trusted_roots(runtime)
    (runtime / "preview-config").mkdir(mode=0o700)
    captured: dict[str, object] = {}

    services = object()

    def bind(base: object, preview_paths: object | None) -> tuple[object, object]:
        assert base is services
        captured["preview_paths"] = preview_paths
        return base, preview_paths

    monkeypatch.setattr(
        production_app, "build_production_ui_services", lambda _paths: services
    )
    monkeypatch.setattr(production_app, "bind_optional_preview_services", bind)
    monkeypatch.setattr(
        production_app,
        "launch_app",
        lambda _services, **kwargs: captured.update(kwargs),
    )

    production_app.launch_production_ui(runtime, environ={})

    preview = captured["preview_paths"]
    assert preview is not None
    assert captured["allowed_paths"] == [
        str(runtime / "jobs" / "ui-production" / "export"),
        str(preview.display_root),
    ]
    assert str(preview.preview_config_root) in captured["blocked_paths"]
    assert str(preview.evidence_root) in captured["blocked_paths"]
    assert str(preview.staging_root) in captured["blocked_paths"]
    assert str(preview.display_root) not in captured["blocked_paths"]
