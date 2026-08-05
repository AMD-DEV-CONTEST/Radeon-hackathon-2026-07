"""Regression coverage for the Determinex VS Code extension surface."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXTENSION_TS = _REPO_ROOT / "frontend" / "vscode-extension" / "src" / "extension.ts"
_PACKAGE_JSON = _REPO_ROOT / "frontend" / "vscode-extension" / "package.json"
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_extension_registers_each_command_once():
    src = _EXTENSION_TS.read_text(encoding="utf-8")
    registered = re.findall(r'registerCommand\("([^"]+)"', src)
    counts = Counter(registered)
    assert counts
    assert all(count == 1 for count in counts.values()), counts


def test_package_configuration_keys_are_unique_and_model_default_survives():
    raw = _PACKAGE_JSON.read_text(encoding="utf-8")
    keys = re.findall(r'"(determinex\.[^"]+)"\s*:', raw)
    counts = Counter(keys)
    assert all(count == 1 for count in counts.values()), counts

    package = json.loads(raw)
    props = package["contributes"]["configuration"]["properties"]
    assert props["determinex.model"]["default"] == "determinex-engineer-v11-dsl"
    assert props["determinex.pythonPath"]["default"] == "python"


def test_tauri_driver_recognizes_flagship_commands_without_cli_only_gap():
    from ide import _tauri_driver

    preview = _tauri_driver._dispatch("preview_idea_oracle", {"idea_text": ""})
    assert preview["status"] == "TAURI_COMMAND_OK"
    assert preview["command"] == "preview_idea_oracle"

    governance = _tauri_driver._dispatch("get_governance_status", {})
    assert governance["status"] == "TAURI_COMMAND_OK"
    assert governance["command"] == "get_governance_status"


if __name__ == "__main__":
    test_extension_registers_each_command_once()
    test_package_configuration_keys_are_unique_and_model_default_survives()
    test_tauri_driver_recognizes_flagship_commands_without_cli_only_gap()
    print("extension and tauri driver regression assertions passed")
