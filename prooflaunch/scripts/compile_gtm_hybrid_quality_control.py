#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.gtm_hybrid_quality_control import compile_hybrid_quality_control


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    payload = compile_hybrid_quality_control(
        project_root=ROOT,
        ledger_path=ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json",
        challenger_admission_path=ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json",
        capture_manifest_path=ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json",
        local_discovery_path=ROOT / "evidence/v10/local-first-model-resource-discovery.json",
        cloud_plan_path=ROOT / "evidence/v10/free-cloud-execution-plan-v2.json",
        output_json=ROOT / "evidence/v10/gtm-hybrid-quality-control-v1.json",
        output_markdown=ROOT / "docs/product/GTM_HYBRID_QUALITY_CONTROL_V1.md",
    )
    print(json.dumps({
        "status": "compiled",
        "local_lanes": f"{payload['portfolio']['local_ready_category_count']}/13",
        "cloud_api_roles": f"{payload['portfolio']['cloud_api_role_count_ready']}/4",
        "cloud_gpu": payload["portfolio"]["cloud_gpu_training_status"],
        "pk_jobs": payload["portfolio"]["job_count"],
        "wins": payload["portfolio"]["candidate_wins"],
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
