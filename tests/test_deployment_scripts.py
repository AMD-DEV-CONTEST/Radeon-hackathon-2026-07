import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _manifest_module() -> ModuleType:
    script = Path("scripts/verify_model_manifest.py").resolve()
    spec = importlib.util.spec_from_file_location("verify_model_manifest", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_manifest_verifier_accepts_exact_hash(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"real local fixture")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    manifest = tmp_path / "model-manifest.json"
    manifest.write_text(
        json.dumps({"revision": "immutable-test-revision", "model_sha256": digest}),
        encoding="utf-8",
    )

    result = _manifest_module().verify(model, manifest)

    assert result["status"] == "PASS"
    assert result["model_sha256"] == digest


def test_model_manifest_verifier_rejects_mismatch(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fixture")
    manifest = tmp_path / "model-manifest.json"
    manifest.write_text(
        json.dumps({"revision": "revision", "model_sha256": "0" * 64}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mismatch"):
        _manifest_module().verify(model, manifest)


def test_server_scripts_use_safe_process_contract() -> None:
    scripts = Path("scripts")
    required = {
        "server_env.sh",
        "server_probe.sh",
        "start_local_llm.sh",
        "stop_local_llm.sh",
        "start_buildguard_api.sh",
        "stop_buildguard_api.sh",
        "start_buildguard_ui.sh",
        "stop_buildguard_ui.sh",
        "start_all.sh",
        "stop_all.sh",
        "health_check.sh",
        "run_competition_validation.sh",
        "export_runtime_evidence.sh",
    }
    assert required <= {path.name for path in scripts.iterdir()}
    helper = (scripts / "process_helpers.sh").read_text(encoding="utf-8")
    assert '[[ "$pid" =~ ^[1-9][0-9]*$ ]]' in helper
    assert "/proc/$pid/cmdline" in helper
    assert "kill -TERM" in helper
    assert "kill -KILL" in helper
    environment = (scripts / "server_env.sh").read_text(encoding="utf-8")
    assert "/persistent/BuildGuard-Radeon-backup" in environment
    assert 'BG_PVC="${BG_PVC:-' in environment
    health_check = (scripts / "health_check.sh").read_text(encoding="utf-8")
    assert "/agent/chat/stream" in health_check
    assert "OK Chat-first API contract" in health_check


def test_model_inventory_verifies_every_configured_artifact(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"inventory fixture")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    manifest = tmp_path / "model-manifest.json"
    manifest.write_text(
        json.dumps({"revision": "immutable", "model_sha256": digest}),
        encoding="utf-8",
    )
    inventory = tmp_path / "models.yaml"
    inventory.write_text(
        "models:\n"
        "  fixture:\n"
        f"    artifact: {model.as_posix()}\n"
        f"    manifest: {manifest.as_posix()}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_model_inventory.py",
            str(inventory),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "PASS"
