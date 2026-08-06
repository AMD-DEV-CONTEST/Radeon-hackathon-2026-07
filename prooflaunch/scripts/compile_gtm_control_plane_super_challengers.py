#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_control_plane_named_pk import AD_SCHEMA, AGENT_SCHEMA, MEMORY_SCHEMA, compile_control_plane, verify


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/codex-control-plane-super-challengers-v1.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/control-plane-super-challengers-v1"
LINEAGE_PATHS = [
    ROOT / "artifacts/gtm-last-mile-pk-v1/text-super-challenger-v1/creative-brief.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v1/content-calendar.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/decision-intelligence-super-challengers-v1/data-strategy-decision-memo.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/decision-intelligence-super-challengers-v1/product-analytics-measurement-system.json",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    lineage = []
    for path in LINEAGE_PATHS:
        if not path.is_file():
            raise SystemExit(f"missing lineage asset: {path}")
        lineage.append({"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    memory, agent, ads = compile_control_plane(config, lineage=lineage)
    verify(memory, MEMORY_SCHEMA)
    verify(agent, AGENT_SCHEMA)
    verify(ads, AD_SCHEMA)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "cross-device-memory-execution-system.json": memory,
        "employee-agent-mission-system.json": agent,
        "advertising-activation-review-system.json": ads,
    }
    for filename, payload in outputs.items():
        atomic_write_text(args.output_dir / filename, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "outputs": [str(args.output_dir / filename) for filename in outputs],
        "memory_tests": len(memory["retrieval_tests"]),
        "agent_nodes": len(agent["graph_nodes"]),
        "ad_routes": len(ads["creative_matrix"]),
        "named_product_stress_tests": sum(len(payload["opponent_stress_tests"]) for payload in outputs.values()),
        "completed_named_product_pk_count": 0,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
