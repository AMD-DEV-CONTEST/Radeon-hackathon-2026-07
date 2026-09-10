"""Production UI compiler-context bootstrap ownership contracts."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from specstyle.errors import DomainError, InfrastructureError
from specstyle.workflow import production_service


class _Closable:
    def __init__(self, error: BaseException | None = None) -> None:
        self.closed = 0
        self.error = error

    def close(self) -> None:
        self.closed += 1
        if self.error is not None:
            raise self.error


def test_context_loader_closes_pipeline_but_borrows_supply(monkeypatch) -> None:
    loaded, supply, context = _Closable(), _Closable(), object()
    monkeypatch.setattr(
        production_service,
        "_bind_pipeline_loader",
        lambda *args: lambda: loaded,
    )
    monkeypatch.setattr(
        production_service,
        "_compiler_context_for_loaded",
        lambda factory, candidate: context,
    )

    result = production_service.load_production_compiler_context(
        supply, object(), object(), lambda _version: object()
    )

    assert result is context
    assert loaded.closed == 1
    assert supply.closed == 0


def test_context_loader_closes_pipeline_on_factory_failure(monkeypatch) -> None:
    loaded, error = _Closable(), DomainError("context failed")
    monkeypatch.setattr(
        production_service,
        "_bind_pipeline_loader",
        lambda *args: lambda: loaded,
    )
    monkeypatch.setattr(
        production_service,
        "_compiler_context_for_loaded",
        lambda *_args: (_ for _ in ()).throw(error),
    )

    with pytest.raises(DomainError) as raised:
        production_service.load_production_compiler_context(
            object(), object(), object(), lambda _version: object()
        )

    assert raised.value is error
    assert loaded.closed == 1


def test_context_loader_never_swallows_pipeline_close_failure(monkeypatch) -> None:
    error = InfrastructureError("pipeline close failed")
    loaded = _Closable(error)
    monkeypatch.setattr(
        production_service,
        "_bind_pipeline_loader",
        lambda *args: lambda: loaded,
    )
    monkeypatch.setattr(
        production_service,
        "_compiler_context_for_loaded",
        lambda *_args: object(),
    )

    with pytest.raises(InfrastructureError) as raised:
        production_service.load_production_compiler_context(
            object(), object(), object(), lambda _version: object()
        )

    assert raised.value is error
    assert loaded.closed == 1


def test_context_loader_preserves_factory_failure_when_close_also_fails(
    monkeypatch,
) -> None:
    primary = DomainError("context failed")
    loaded = _Closable(InfrastructureError("pipeline close failed"))
    monkeypatch.setattr(
        production_service,
        "_bind_pipeline_loader",
        lambda *args: lambda: loaded,
    )
    monkeypatch.setattr(
        production_service,
        "_compiler_context_for_loaded",
        lambda *_args: (_ for _ in ()).throw(primary),
    )

    with pytest.raises(DomainError) as raised:
        production_service.load_production_compiler_context(
            object(), object(), object(), lambda _version: object()
        )

    assert raised.value is primary
    assert raised.value.__notes__ == [
        "production compiler context pipeline cleanup failed"
    ]
    assert loaded.closed == 1


def _directory_fds(tmp_path: Path) -> tuple[int, int, int]:
    paths = tuple(tmp_path / name for name in ("config", "evidence", "models"))
    for path in paths:
        path.mkdir()
    return tuple(os.open(path, os.O_RDONLY | os.O_DIRECTORY) for path in paths)


def test_bootstrap_composes_context_and_closes_only_verified_supply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.workflow import production_bootstrap as bootstrap

    fds = _directory_fds(tmp_path)
    context_config, supply_config = (
        object(),
        SimpleNamespace(graph=object(), manifests=object(), approvals=object()),
    )
    supply, environment, factory, context = _Closable(), object(), object(), object()
    calls: list[object] = []
    monkeypatch.setattr(
        bootstrap,
        "load_production_context_config",
        lambda config, evidence: (
            calls.append(("context", config, evidence)) or context_config
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "load_production_supply_config",
        lambda config: calls.append(("supply-config", config)) or supply_config,
    )
    monkeypatch.setattr(
        bootstrap,
        "verify_pipeline_supply",
        lambda models, graph, manifests, approvals: (
            calls.append(("verify", models, graph, manifests, approvals)) or supply
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "capture_environment",
        lambda: calls.append("environment") or environment,
    )
    monkeypatch.setattr(
        bootstrap,
        "make_production_compiler_context_factory",
        lambda config, env, graph: (
            calls.append(("factory", config, env, graph)) or factory
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "load_production_compiler_context",
        lambda borrowed, graph, env, build, **_kwargs: (
            calls.append(("load", borrowed, graph, env, build)) or context
        ),
    )
    try:
        result = bootstrap.load_production_ui_compiler_context(*fds)
        assert result is context
        assert supply.closed == 1
        assert all(os.fstat(fd).st_ino > 0 for fd in fds)
        assert calls[0][0] == "context" and calls[-1][0] == "load"
    finally:
        for fd in fds:
            os.close(fd)


def test_bootstrap_closes_supply_on_context_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.workflow import production_bootstrap as bootstrap

    fds, supply = _directory_fds(tmp_path), _Closable()
    config = SimpleNamespace(graph=object(), manifests=(), approvals=())
    monkeypatch.setattr(
        bootstrap, "load_production_context_config", lambda *_: object()
    )
    monkeypatch.setattr(bootstrap, "load_production_supply_config", lambda *_: config)
    monkeypatch.setattr(bootstrap, "verify_pipeline_supply", lambda *_: supply)
    monkeypatch.setattr(bootstrap, "capture_environment", lambda: object())
    monkeypatch.setattr(
        bootstrap, "make_production_compiler_context_factory", lambda *_: object()
    )
    error = DomainError("bootstrap failed")
    monkeypatch.setattr(
        bootstrap,
        "load_production_compiler_context",
        lambda *_, **_kwargs: (_ for _ in ()).throw(error),
    )
    try:
        with pytest.raises(DomainError) as raised:
            bootstrap.load_production_ui_compiler_context(*fds)
        assert raised.value is error
        assert supply.closed == 1
    finally:
        for fd in fds:
            os.close(fd)


def test_bootstrap_preserves_context_failure_when_supply_close_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.workflow import production_bootstrap as bootstrap

    fds = _directory_fds(tmp_path)
    primary = DomainError("bootstrap failed")
    supply = _Closable(InfrastructureError("supply close failed"))
    config = SimpleNamespace(graph=object(), manifests=(), approvals=())
    monkeypatch.setattr(
        bootstrap, "load_production_context_config", lambda *_: object()
    )
    monkeypatch.setattr(bootstrap, "load_production_supply_config", lambda *_: config)
    monkeypatch.setattr(bootstrap, "verify_pipeline_supply", lambda *_: supply)
    monkeypatch.setattr(bootstrap, "capture_environment", lambda: object())
    monkeypatch.setattr(
        bootstrap, "make_production_compiler_context_factory", lambda *_: object()
    )
    monkeypatch.setattr(
        bootstrap,
        "load_production_compiler_context",
        lambda *_, **_kwargs: (_ for _ in ()).throw(primary),
    )
    try:
        with pytest.raises(DomainError) as raised:
            bootstrap.load_production_ui_compiler_context(*fds)
        assert raised.value is primary
        assert raised.value.__notes__ == ["production supply cleanup failed"]
        assert supply.closed == 1
    finally:
        for fd in fds:
            os.close(fd)


def test_bootstrap_rejects_aliased_roots_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.workflow import production_bootstrap as bootstrap

    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(
        bootstrap,
        "load_production_context_config",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not load")),
    )
    try:
        with pytest.raises(DomainError, match="distinct"):
            bootstrap.load_production_ui_compiler_context(fd, fd, fd)
        assert os.fstat(fd).st_ino > 0
    finally:
        os.close(fd)
