#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.gtm_adaptive_capability_graph import compile_adaptive_capability_graph_matrix


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    payload = compile_adaptive_capability_graph_matrix(
        hybrid_path=ROOT / "evidence/v10/gtm-hybrid-quality-control-v1.json",
        radar_path=ROOT / "config/gtm_open_source_capability_radar_v1.json",
        candidate_registry_path=ROOT / "config/gtm_adaptive_oss_skill_candidates_v1.json",
        output_json=ROOT / "evidence/v10/gtm-adaptive-capability-graph-matrix-v1.json",
        output_markdown=ROOT / "docs/product/GTM_ADAPTIVE_CAPABILITY_GRAPH_V1.md",
    )
    print(json.dumps({
        "status": "compiled",
        "contexts": payload["coverage"]["context_count"],
        "lane_decisions": payload["coverage"]["lane_decision_count"],
        "zero_budget_paid_activations": payload["coverage"]["zero_budget_paid_activation_count"],
        "automatic_external_actions": payload["coverage"]["automatic_external_action_count"],
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
