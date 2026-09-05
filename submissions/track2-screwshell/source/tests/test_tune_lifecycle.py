"""Unit tests for LlamaServerLifecycle.start_argv (tune-loop plan, Todo 2).

No real llama-server / GPU. We mock the port/health/completion primitives and
the Popen so the takeover + hard-failure semantics can be exercised in-process.
"""
from __future__ import annotations

import subprocess

import screwshell.autotune.governor as G
from screwshell.autotune.governor import LlamaServerLifecycle


class _FakePopen:
    def __init__(self, pid=12345):
        self.pid = pid
        self.returncode = None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _patch(monkeypatch, *, health=True, complete=True, listener_pid=None):
    monkeypatch.setattr(G, "_port_free", lambda p, h="127.0.0.1": True)
    monkeypatch.setattr(G, "_health_ok", lambda u, t=2.0: health)

    def _fake_popen(*a, **k):
        return _FakePopen()

    monkeypatch.setattr(G.subprocess, "Popen", _fake_popen)
    if listener_pid is not None:
        monkeypatch.setattr(G, "_listener_pid", lambda p: str(listener_pid))

    if complete:
        class _Resp:
            def read(self):
                return b"{}"
        monkeypatch.setattr(G.urllib.request, "urlopen", lambda *a, **k: _Resp())
    else:
        def _boom(*a, **k):
            raise OSError("completion failed")
        monkeypatch.setattr(G.urllib.request, "urlopen", _boom)


def test_start_argv_uses_list_not_shell(monkeypatch):
    captured = {}
    monkeypatch.setattr(G, "_port_free", lambda p, h="127.0.0.1": True)
    monkeypatch.setattr(G, "_health_ok", lambda u, t=2.0: True)

    class _CapPopen:
        def __init__(self, *a, **k):
            captured["args"] = a[0] if a else k.get("args")
            captured["shell"] = k.get("shell", False)
            self.pid = 1

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass
    monkeypatch.setattr(G.subprocess, "Popen", _CapPopen)

    class _Resp:
        def read(self):
            return b"{}"
    monkeypatch.setattr(G.urllib.request, "urlopen", lambda *a, **k: _Resp())

    lc = LlamaServerLifecycle("ignored-template", port=8099)
    ok, _ = lc.start_argv(["llama-server", "--model", "/m", "--jinja"])
    assert ok is True
    assert captured["shell"] is False          # never shell=True
    assert isinstance(captured["args"], list)  # argv list form
    lc.stop()


def test_start_argv_hard_failure_when_health_down(monkeypatch):
    _patch(monkeypatch, health=False, complete=False)
    lc = LlamaServerLifecycle("t", port=8099)
    ok, elapsed = lc.start_argv(["llama-server", "--model", "/m"])
    assert ok is False                         # hard failure signal
    assert isinstance(elapsed, float)


def test_start_argv_takeover_kills_external(monkeypatch):
    killed = {}
    # Port is OCCUPIED (simulating an external production server) so takeover
    # must kill the listener before starting.
    monkeypatch.setattr(G, "_port_free", lambda p, h="127.0.0.1": False)
    monkeypatch.setattr(G, "_listener_pid", lambda p: "99999")
    monkeypatch.setattr(G, "_health_ok", lambda u, t=2.0: True)
    monkeypatch.setattr(G.subprocess, "Popen", lambda *a, **k: _FakePopen())

    class _Resp:
        def read(self):
            return b"{}"
    monkeypatch.setattr(G.urllib.request, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(G.os, "kill", lambda pid, sig: killed.setdefault("pids", []).append(pid))

    lc = LlamaServerLifecycle("t", port=8099)
    ok, _ = lc.start_argv(["llama-server", "--model", "/m"], takeover=True)
    assert ok is True
    assert 99999 in killed.get("pids", [])      # external listener was killed
    lc.stop()


def test_start_argv_failure_signal_shape(monkeypatch):
    _patch(monkeypatch, health=True, complete=False)  # health up but completion fails
    lc = LlamaServerLifecycle("t", port=8099)
    result = lc.start_argv(["llama-server", "--model", "/m"])
    assert isinstance(result, tuple) and len(result) == 2
    ok, to_serve = result
    assert ok is False
    lc.stop()
