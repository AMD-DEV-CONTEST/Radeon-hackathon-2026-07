#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_agent_control_plane_v2 import build_agent_control_plane, compile_campaign_replay_receipt, verify_agent_control_plane, verify_campaign_replay_receipt


ROOT = Path(__file__).resolve().parents[1]
H = "a" * 64


def main() -> int:
    control = build_agent_control_plane(); verify_agent_control_plane(control)
    artifacts = []
    parent = []
    for index, artifact_type in enumerate(("brief", "evidence", "hypothesis", "script", "asset", "approval", "experiment", "result"), 1):
        artifact_id = f"synthetic-{artifact_type}-{index}"
        artifacts.append({"artifact_id": artifact_id, "artifact_type": artifact_type, "content_sha256": H, "parent_artifact_ids": list(parent), "created_by": "synthetic-regression-fixture", "created_at": "2026-08-05T00:00:00Z"})
        parent = [artifact_id]
    node_receipts = [{"node_id": node, "input_sha256": H, "output_sha256": H, "model_receipt_sha256": H, "tool_receipt_sha256s": [H], "human_decision_receipt_sha256s": [H] if node in {"review", "publishing"} else []} for node in ("diagnostic", "evidence", "strategy", "creative", "production", "adaptation", "review", "publishing", "measurement", "learning")]
    run = compile_campaign_replay_receipt(control, {"run_id": "synthetic-agent-control-regression", "artifacts": artifacts, "node_receipts": node_receipts, "requested_high_risk_actions": [], "human_authorizations": []})
    verify_campaign_replay_receipt(run)
    payload = {"schema": "ProofLaunchGTMAgentControlPlaneBundleV2", "control_plane": control, "synthetic_replay_receipt": run, "truth_boundary": "Synthetic replay proves control structure only."}
    import hashlib
    payload["content_sha256"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    output = ROOT / "evidence/v10/gtm-agent-control-plane-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "node_count": len(control["graph"]["nodes"]), "agent_count": len(control["agents"]), "run_status": run["status"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
