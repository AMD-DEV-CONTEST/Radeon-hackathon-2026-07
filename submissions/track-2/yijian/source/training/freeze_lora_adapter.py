# -*- coding: utf-8 -*-
"""Freeze a passed LoRA adapter with immutable base, data and environment evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


REVISION = "40c069824f4251a91eefaf281ebe4c544efd3e18"
SCHEMA = "yijian-lora-adapter-freeze-v1"


class FreezeError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    items = (value for value in path.rglob("*") if value.is_file())
    for item in sorted(items, key=lambda value: value.relative_to(path).as_posix().encode("utf-8")):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FreezeError(f"{path} must contain a JSON object")
    return value


def freeze(
    *, adapter: Path, metrics: Path, hardware: Path, agent_manifest: Path,
    model_dir: Path, output_dir: Path,
) -> dict[str, Any]:
    if output_dir.exists():
        raise FreezeError(f"freeze output already exists: {output_dir}")
    metric_value = read_json(metrics)
    hardware_value = read_json(hardware)
    agent_value = read_json(agent_manifest)
    if metric_value.get("passed") is not True:
        raise FreezeError("full training metrics have not passed")
    if metric_value.get("optimizerSteps") != 90 or abs(float(metric_value.get("completedEpochs") or 0) - 2) > 1e-6:
        raise FreezeError("full training must complete exactly 90 optimizer steps and two epochs")
    if hardware_value.get("modelRevision") != REVISION:
        raise FreezeError("base model revision mismatch")
    if agent_value.get("passed") is not True or (agent_value.get("counts") or {}).get("train") != 720:
        raise FreezeError("agent SFT manifest has not passed the 720-row gate")
    if not (adapter / "adapter_config.json").is_file():
        raise FreezeError("adapter_config.json is missing")
    index_path = model_dir / "model.safetensors.index.json"
    index = read_json(index_path)
    shards = sorted(set((index.get("weight_map") or {}).values()))
    if len(shards) != 8:
        raise FreezeError(f"expected eight base shards, found {len(shards)}")
    missing = [name for name in shards if not (model_dir / name).is_file()]
    if missing:
        raise FreezeError(f"missing base shards: {missing}")

    output_dir.mkdir(parents=True)
    frozen_adapter = output_dir / "adapter"
    shutil.copytree(adapter, frozen_adapter)
    manifest = {
        "schemaVersion": SCHEMA,
        "frozen": True,
        "frozenAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "displayName": "YIJIAN LoRA",
        "servedModelName": "yijian-lora",
        "baseModel": "Qwen/Qwen3-14B",
        "baseRevision": REVISION,
        "baseShards": {name: sha256_file(model_dir / name) for name in shards},
        "adapterTreeSha256": tree_hash(frozen_adapter),
        "inputs": {
            "fullMetricsSha256": sha256_file(metrics),
            "hardwareSha256": sha256_file(hardware),
            "agentManifestSha256": sha256_file(agent_manifest),
            "modelIndexSha256": sha256_file(index_path),
        },
        "weightsBundled": False,
        "redistributionPolicy": "adapter retained locally and in the user's private cloud; base weights are re-fetched by pinned revision",
    }
    (output_dir / "adapter-freeze-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--hardware", type=Path, required=True)
    parser.add_argument("--agent-manifest", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = freeze(
        adapter=args.adapter.resolve(), metrics=args.metrics.resolve(),
        hardware=args.hardware.resolve(), agent_manifest=args.agent_manifest.resolve(),
        model_dir=args.model_dir.resolve(), output_dir=args.output_dir.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
