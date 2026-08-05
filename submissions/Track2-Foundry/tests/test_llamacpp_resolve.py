"""Regression tests: llama.cpp resolution must not depend on the
contest image's /opt/llama.cpp existing. Order: configured path, then
$LLAMA_CPP_HOME, then common locations — and a failure names every
path it tried."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foundry import llamacpp


def _make_exe(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_configured_path_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(llamacpp, "COMMON_HOMES", [])
    monkeypatch.delenv("LLAMA_CPP_HOME", raising=False)
    exe = _make_exe(tmp_path / f"llama-server{llamacpp._EXE_SUFFIX}")
    assert llamacpp.resolve_binary(exe, "llama-server") == exe


def test_sibling_binary_from_configured_server(tmp_path, monkeypatch):
    monkeypatch.setattr(llamacpp, "COMMON_HOMES", [])
    monkeypatch.delenv("LLAMA_CPP_HOME", raising=False)
    server = _make_exe(tmp_path / f"llama-server{llamacpp._EXE_SUFFIX}")
    bench = _make_exe(tmp_path / f"llama-bench{llamacpp._EXE_SUFFIX}")
    assert llamacpp.resolve_binary(server, "llama-bench") == bench


def test_env_home_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(llamacpp, "COMMON_HOMES", [])
    exe = _make_exe(tmp_path / "build" / "bin"
                    / f"llama-server{llamacpp._EXE_SUFFIX}")
    monkeypatch.setenv("LLAMA_CPP_HOME", str(tmp_path))
    got = llamacpp.resolve_binary("/nonexistent/llama-server", "llama-server")
    assert got == exe


def test_common_location_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("LLAMA_CPP_HOME", raising=False)
    exe = _make_exe(tmp_path / "bin" / f"llama-server{llamacpp._EXE_SUFFIX}")
    monkeypatch.setattr(llamacpp, "COMMON_HOMES", [tmp_path])
    assert llamacpp.resolve_binary(None, "llama-server") == exe


def test_failure_names_tried_paths_and_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(llamacpp, "COMMON_HOMES", [tmp_path / "nowhere"])
    monkeypatch.setattr(llamacpp, "REPO_ROOT", tmp_path)  # isolate tools/ glob
    monkeypatch.delenv("LLAMA_CPP_HOME", raising=False)
    with pytest.raises(RuntimeError) as exc:
        llamacpp.resolve_binary(None, "llama-server")
    msg = str(exc.value)
    assert "nowhere" in msg and "LLAMA_CPP_HOME" in msg


def test_resolve_src_finds_convert_script(tmp_path, monkeypatch):
    monkeypatch.setattr(llamacpp, "COMMON_HOMES", [])
    monkeypatch.delenv("LLAMA_CPP_HOME", raising=False)
    (tmp_path / "convert_hf_to_gguf.py").write_text("# stub")
    assert llamacpp.resolve_src(tmp_path) == tmp_path


def test_resolve_src_failure_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(llamacpp, "COMMON_HOMES", [tmp_path / "x"])
    monkeypatch.setattr(llamacpp, "REPO_ROOT", tmp_path)  # isolate tools/ glob
    monkeypatch.delenv("LLAMA_CPP_HOME", raising=False)
    with pytest.raises(RuntimeError) as exc:
        llamacpp.resolve_src(None)
    assert "convert_hf_to_gguf.py" in str(exc.value)
    assert "export.llama_src" in str(exc.value)
