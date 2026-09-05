"""Gateway reliability tests (no GPU required; filesystem + mocked proc)."""
from __future__ import annotations

from pathlib import Path

from screwshell.gateway.reliability import (
    _port_in_use, prelaunch_check, validate_paths,
)


def test_validate_paths_missing_model():
    res = validate_paths("/no/such/model.gguf")
    assert res.ok is False
    assert any("底模" in e for e in res.errors)


def test_validate_paths_missing_lora():
    res = validate_paths("/no/model.gguf", ["/no/lora.gguf"])
    assert res.ok is False
    assert any("LoRA" in e for e in res.errors)


def test_validate_paths_ok(tmp_path, monkeypatch):
    model = tmp_path / "m.gguf"
    model.write_text("x")
    monkeypatch.setattr("screwshell.gateway.reliability._which", lambda n: True)
    res = validate_paths(str(model))
    assert res.ok is True


def test_validate_paths_missing_binary(tmp_path, monkeypatch):
    model = tmp_path / "m.gguf"
    model.write_text("x")
    monkeypatch.setattr("screwshell.gateway.reliability._which", lambda n: False)
    res = validate_paths(str(model), binary="/no/llama-server")
    assert res.ok is False
    assert any("二进制" in e for e in res.errors)


def test_prelaunch_port_check(monkeypatch, tmp_path):
    model = tmp_path / "m.gguf"
    model.write_text("x")
    monkeypatch.setattr("screwshell.gateway.reliability._which", lambda n: True)

    def _true(*a, **k):
        return True

    def _false(*a, **k):
        return False

    # port free -> ok
    monkeypatch.setattr("screwshell.gateway.reliability._port_in_use", _false)
    res = prelaunch_check(str(model), port=8080)
    assert res.ok is True

    # port in use -> error (refuse to start silently)
    monkeypatch.setattr("screwshell.gateway.reliability._port_in_use", _true)
    res = prelaunch_check(str(model), port=8080)
    assert res.ok is False
    assert any("端口" in e for e in res.errors)


def test_port_in_use_false_on_dev_box():
    # no llama-server should be listening on this odd port on a dev box
    assert _port_in_use(58080) is False
