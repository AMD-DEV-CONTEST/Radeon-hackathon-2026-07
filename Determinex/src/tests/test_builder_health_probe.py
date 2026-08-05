from __future__ import annotations

import json
from pathlib import Path

from scripts.hive import builder_health_probe


def test_builder_health_probe_reports_selected_fallback(monkeypatch):
    calls: list[tuple[dict[str, str], list[str], int]] = []

    def fake_preflight(assignments, *, fallback_aliases=None, timeout=None):
        calls.append((dict(assignments), list(fallback_aliases or []), int(timeout or 0)))
        assignments["builder"] = "local/coder"
        return True, "switched builder from ollama/determinex-engineer-v11-dsl to local/coder"

    monkeypatch.setattr(builder_health_probe.executor, "_preflight_builder_health", fake_preflight)

    result = builder_health_probe.run_probe(
        model="ollama/determinex-engineer-v11-dsl",
        fallback_model="local/coder",
        timeout=3,
    )

    assert result["schema_version"] == "determinex-builder-health-probe-v1"
    assert result["status"] == "passed"
    assert result["release_ready"] is False
    assert result["builder_model_requested"] == "ollama/determinex-engineer-v11-dsl"
    assert result["builder_model_selected"] == "local/coder"
    assert result["exact_blocker"] == ""
    assert calls == [({"builder": "ollama/determinex-engineer-v11-dsl"}, ["local/coder"], 3)]


def test_builder_health_probe_preserves_exact_blocker(monkeypatch):
    def fake_preflight(assignments, *, fallback_aliases=None, timeout=None):
        return False, "builder health preflight failed; ollama/determinex-engineer-v11-dsl: Timeout"

    monkeypatch.setattr(builder_health_probe.executor, "_preflight_builder_health", fake_preflight)

    result = builder_health_probe.run_probe(model="ollama/determinex-engineer-v11-dsl", timeout=5)

    assert result["status"] == "blocked"
    assert result["release_ready"] is False
    assert result["builder_model_selected"] == "ollama/determinex-engineer-v11-dsl"
    assert (
        result["exact_blocker"]
        == "builder health preflight failed; ollama/determinex-engineer-v11-dsl: Timeout"
    )
    assert "does not prove the first E2E workflow" in result["claim_boundary"]


def test_builder_health_probe_default_uses_configured_alias_fallbacks(monkeypatch):
    calls: list[tuple[dict[str, str], object, int]] = []

    def fake_preflight(assignments, *, fallback_aliases=None, timeout=None):
        calls.append((dict(assignments), fallback_aliases, int(timeout or 0)))
        return True, "builder determinex/engineer passed health preflight"

    monkeypatch.setattr(builder_health_probe.executor, "_preflight_builder_health", fake_preflight)

    result = builder_health_probe.run_probe(timeout=7)

    assert result["status"] == "passed"
    assert result["builder_model_requested"] == "determinex/engineer"
    assert calls == [({"builder": "determinex/engineer"}, None, 7)]


def test_builder_health_probe_cli_writes_json(monkeypatch, tmp_path: Path):
    def fake_preflight(assignments, *, fallback_aliases=None, timeout=None):
        return True, "builder ollama/determinex-engineer-v11-dsl passed health preflight"

    monkeypatch.setattr(builder_health_probe.executor, "_preflight_builder_health", fake_preflight)
    output = tmp_path / "probe.json"

    rc = builder_health_probe.main(
        [
            "--model",
            "ollama/determinex-engineer-v11-dsl",
            "--timeout",
            "2",
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["output_path"] == output.as_posix()
