"""Tests for Determinex LLM-neutral program advisory packets."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

advisor_mod = importlib.import_module("ide.llm_program_advisor")
surface_mod = importlib.import_module("ide.backend_command_surface")

build_advisory_packet = advisor_mod.build_advisory_packet
classify_intent = advisor_mod.classify_intent
IDEBackendCommandSurface = surface_mod.IDEBackendCommandSurface


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / "src" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    return root


def test_intent_classifier_handles_creation_upkeep_and_repair():
    assert classify_intent("create a new cli app") == "creation"
    assert classify_intent("update dependencies and refactor") == "upkeep"
    assert classify_intent("fix the failing tests") == "repair"


def test_advisory_packet_is_model_agnostic_and_verifier_first(tmp_path: Path):
    packet = build_advisory_packet(
        user_request="fix the failing tests",
        workspace=_workspace(tmp_path),
    )
    payload = packet.to_dict()

    assert payload["schema_version"] == "determinex-llm-program-advisory-v1"
    assert payload["intent"] == "repair"
    assert payload["advisory_only"] is True
    assert payload["source_mutation_authorized"] is False
    assert payload["training_eligible"] is False
    assert payload["universal_verified_support_claimed"] is False
    assert payload["llm_contract"]["model_agnostic"] is True
    assert "python" in payload["language_signals"]
    assert "pyproject.toml" in payload["build_signals"]
    assert any("verifier" in step.lower() for step in payload["verifier_plan"])
    assert "Do not claim universal language" in " ".join(payload["blocked_claims"])


def test_backend_command_surfaces_advisory_without_authority(tmp_path: Path):
    surface = IDEBackendCommandSurface()
    result = surface.call(
        "generate_llm_program_advisory",
        workspace=_workspace(tmp_path),
        user_request="maintain this project and update dependencies safely",
    )

    assert result.status == "IDE_COMMAND_OK"
    assert result.source_mutation_authorized is False
    assert result.training_eligible is False
    assert result.payload["intent"] == "upkeep"
    assert result.payload["advisory_only"] is True
    assert result.payload["universal_verified_support_claimed"] is False


def test_tauri_driver_dispatches_advisory_command(tmp_path: Path):
    args = {
        "workspace": str(_workspace(tmp_path)),
        "user_request": "create a tiny command line program",
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "ide" / "_tauri_driver.py"),
            "generate_llm_program_advisory",
            json.dumps(args),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    response = json.loads(proc.stdout.strip().splitlines()[-1])
    assert response["command"] == "generate_llm_program_advisory"
    assert response["status"] == "TAURI_COMMAND_OK"
    assert response["source_mutation_authorized"] is False
    assert response["training_eligible"] is False
    assert response["payload"]["intent"] == "creation"
