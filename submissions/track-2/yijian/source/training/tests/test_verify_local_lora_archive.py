from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_local_lora_archive.py"
SPEC = importlib.util.spec_from_file_location("verify_local_lora_archive", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_verify_local_archive_matches_freeze_tree(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "README.md").write_text("adapter", encoding="utf-8")
    manifest = {"adapterTreeSha256": MODULE.tree_hash(adapter)}
    (tmp_path / "adapter-freeze-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (adapter / "adapter_model.safetensors").write_bytes(b"weights")
    manifest["adapterTreeSha256"] = MODULE.tree_hash(adapter)
    (tmp_path / "adapter-freeze-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert MODULE.verify(tmp_path)["passed"] is True
