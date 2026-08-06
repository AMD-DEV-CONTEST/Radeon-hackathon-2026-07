# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import freeze_lora_adapter as freezer  # noqa: E402


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _inputs(tmp_path: Path) -> dict[str, Path]:
    adapter = tmp_path / "candidate"
    adapter.mkdir()
    _json(adapter / "adapter_config.json", {"r": 16})
    (adapter / "adapter_model.safetensors").write_bytes(b"adapter")
    metrics = tmp_path / "metrics.json"
    hardware = tmp_path / "hardware.json"
    agent = tmp_path / "manifest.json"
    _json(metrics, {"passed": True, "optimizerSteps": 90, "completedEpochs": 2})
    _json(hardware, {"modelRevision": freezer.REVISION})
    _json(agent, {"passed": True, "counts": {"train": 720}})
    model = tmp_path / "model"
    model.mkdir()
    weight_map = {}
    for index in range(1, 9):
        name = f"model-{index:05d}-of-00008.safetensors"
        (model / name).write_bytes(f"shard-{index}".encode())
        weight_map[f"layer.{index}"] = name
    _json(model / "model.safetensors.index.json", {"weight_map": weight_map})
    return {"adapter": adapter, "metrics": metrics, "hardware": hardware, "agent": agent, "model": model}


def test_freeze_copies_adapter_and_hashes_eight_base_shards(tmp_path: Path) -> None:
    values = _inputs(tmp_path)
    output = tmp_path / "release"
    result = freezer.freeze(
        adapter=values["adapter"], metrics=values["metrics"],
        hardware=values["hardware"], agent_manifest=values["agent"],
        model_dir=values["model"], output_dir=output,
    )
    assert result["frozen"] is True
    assert len(result["baseShards"]) == 8
    assert result["adapterTreeSha256"] == freezer.tree_hash(output / "adapter")
    assert result["weightsBundled"] is False


def test_freeze_rejects_failed_training(tmp_path: Path) -> None:
    values = _inputs(tmp_path)
    _json(values["metrics"], {"passed": False, "optimizerSteps": 90, "completedEpochs": 2})
    with pytest.raises(freezer.FreezeError, match="have not passed"):
        freezer.freeze(
            adapter=values["adapter"], metrics=values["metrics"],
            hardware=values["hardware"], agent_manifest=values["agent"],
            model_dir=values["model"], output_dir=tmp_path / "release",
        )


def test_tree_hash_uses_portable_utf8_relative_path_order(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_bytes(b"upper")
    (tmp_path / "adapter_config.json").write_bytes(b"lower")
    expected = freezer.hashlib.sha256()
    for name in ("README.md", "adapter_config.json"):
        encoded = name.encode("utf-8")
        expected.update(len(encoded).to_bytes(4, "big"))
        expected.update(encoded)
        expected.update(bytes.fromhex(freezer.sha256_file(tmp_path / name)))
    assert freezer.tree_hash(tmp_path) == expected.hexdigest()
