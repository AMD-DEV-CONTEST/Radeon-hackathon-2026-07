"""Lock for the 2026-07-18 model-ladder preflight check.

Found live driving gron: the reimpl drive's escalation tier named
'ollama/qwen2.5-coder:14b-instruct', but that model was never pulled on the box.
Every escalation attempt across 6+ decompose stations silently produced a
generation-error string that got treated as just another wrong-code candidate --
there was no distinction anywhere in the search/router loop between "the model
tried hard and failed" and "the model was never reachable at all". Six stations,
~10-15 min each on real compute, before a human diagnosed it by querying Ollama
directly.

preflight_ladder() mirrors the equivalent check already in scripts/hive/executor.py
('Ollama model pre-flight') for this sibling subsystem: verify every ladder entry
is actually reachable (Ollama has the model / the relevant cloud API key is set)
BEFORE main() spends a single second on observe/decompose.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import determinex_pb_reimpl as reimpl  # noqa: E402


def _fake_urlopen_with_models(*names):
    class _Resp:
        def read(self_inner):
            import json

            return json.dumps({"models": [{"name": n} for n in names]}).encode()

    def _urlopen(req, timeout=5):
        return _Resp()

    return _urlopen


def test_missing_ollama_model_is_flagged():
    with patch("urllib.request.urlopen", _fake_urlopen_with_models("qwen2.5-coder:7b-instruct")):
        problems = reimpl.preflight_ladder(
            [
                "ollama/qwen2.5-coder:7b-instruct",
                "ollama/qwen2.5-coder:14b-instruct",  # not in the fake tag list
            ]
        )
    assert len(problems) == 1
    assert "14b-instruct" in problems[0]
    assert "ollama pull" in problems[0]


def test_all_present_ollama_models_pass_clean():
    with patch(
        "urllib.request.urlopen",
        _fake_urlopen_with_models("qwen2.5-coder:7b-instruct", "deepseek-coder-v2:16b"),
    ):
        problems = reimpl.preflight_ladder(
            [
                "ollama/qwen2.5-coder:7b-instruct",
                "ollama/deepseek-coder-v2:16b",
            ]
        )
    assert problems == []


def test_missing_deepseek_key_is_flagged(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(reimpl, "_api_key", lambda name: "" if name == "DEEPSEEK_API_KEY" else "x")
    problems = reimpl.preflight_ladder(["deepseek-chat"])
    assert len(problems) == 1
    assert "DEEPSEEK_API_KEY" in problems[0]


def test_present_deepseek_key_passes_clean(monkeypatch):
    monkeypatch.setattr(reimpl, "_api_key", lambda name: "sk-fake-key-for-test")
    problems = reimpl.preflight_ladder(["deepseek-chat"])
    assert problems == []


def test_ollama_unreachable_is_flagged_not_silently_ignored():
    def _boom(req, timeout=5):
        raise OSError("connection refused")

    with patch("urllib.request.urlopen", _boom):
        problems = reimpl.preflight_ladder(["ollama/qwen2.5-coder:7b-instruct"])
    assert len(problems) == 1
    assert "could not reach Ollama" in problems[0]
