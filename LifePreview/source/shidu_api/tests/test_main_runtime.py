from __future__ import annotations

from typing import Any

import pytest


def _run_and_capture(monkeypatch: pytest.MonkeyPatch) -> tuple[object, dict[str, Any]]:
    import uvicorn

    from shidu_api import main

    app = object()
    captured: dict[str, Any] = {}
    monkeypatch.setattr(main, "configured_app", lambda: app)

    def run(target: object, **kwargs: Any) -> None:
        captured["target"] = target
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", run)
    main.main()
    return app, captured


def test_main_keeps_default_bind_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHIDU_API_HOST", raising=False)
    monkeypatch.delenv("SHIDU_API_PORT", raising=False)

    app, captured = _run_and_capture(monkeypatch)

    assert captured == {"target": app, "host": "0.0.0.0", "port": 8082}


def test_main_uses_native_process_bind_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHIDU_API_HOST", "127.0.0.1")
    monkeypatch.setenv("SHIDU_API_PORT", "18082")

    app, captured = _run_and_capture(monkeypatch)

    assert captured == {"target": app, "host": "127.0.0.1", "port": 18082}


@pytest.mark.parametrize("value", ["", "0", "65536", "8082.0", "+8082", " 8082"])
def test_main_rejects_invalid_port(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    import uvicorn

    from shidu_api import main

    monkeypatch.setenv("SHIDU_API_PORT", value)
    monkeypatch.setattr(main, "configured_app", lambda: pytest.fail("must fail first"))
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: pytest.fail("must not run"))

    with pytest.raises(RuntimeError, match="SHIDU_API_PORT"):
        main.main()
