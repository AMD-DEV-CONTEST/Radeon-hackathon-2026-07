from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_agent_control_plane_v2 import build_agent_control_plane, compile_campaign_replay_receipt, verify_agent_control_plane, verify_campaign_replay_receipt


H = "a" * 64
NODES = ("diagnostic", "evidence", "strategy", "creative", "production", "adaptation", "review", "publishing", "measurement", "learning")


def complete_run() -> dict:
    artifacts = []; parents = []
    for i, artifact_type in enumerate(("brief", "evidence", "hypothesis", "script", "asset", "approval", "experiment", "result")):
        artifact_id = f"a-{i}"; artifacts.append({"artifact_id": artifact_id, "artifact_type": artifact_type, "content_sha256": H, "parent_artifact_ids": list(parents), "created_by": "test", "created_at": "2026-08-05T00:00:00Z"}); parents = [artifact_id]
    receipts = [{"node_id": node, "input_sha256": H, "output_sha256": H, "model_receipt_sha256": H, "tool_receipt_sha256s": [H], "human_decision_receipt_sha256s": []} for node in NODES]
    return {"run_id": "run-1", "artifacts": artifacts, "node_receipts": receipts, "requested_high_risk_actions": [], "human_authorizations": []}


class GTMAgentControlPlaneV2Tests(unittest.TestCase):
    def test_ten_nodes_loops_agents_artifacts_and_harness_are_fixed(self) -> None:
        control = build_agent_control_plane(); verify_agent_control_plane(control)
        self.assertEqual(len(control["graph"]["nodes"]), 10)
        self.assertEqual(len(control["agents"]), 10)
        self.assertEqual(len(control["artifact_graph"]["types"]), 8)
        self.assertEqual(len(control["harness"]["required_controls"]), 9)

    def test_complete_run_is_replayable_without_external_action(self) -> None:
        receipt = compile_campaign_replay_receipt(build_agent_control_plane(), complete_run()); verify_campaign_replay_receipt(receipt)
        self.assertEqual(receipt["status"], "replayable_prepared_run")
        self.assertFalse(receipt["external_action_executed"])

    def test_missing_evidence_and_high_risk_approval_emit_precise_blockers(self) -> None:
        run = complete_run(); run["artifacts"] = [row for row in run["artifacts"] if row["artifact_type"] != "evidence"]
        # Rebuild a valid parent chain after removing the evidence fixture.
        parents = []
        for row in run["artifacts"]: row["parent_artifact_ids"] = list(parents); parents = [row["artifact_id"]]
        run["requested_high_risk_actions"] = [{"action_type": "publish", "object_sha256": H}]
        receipt = compile_campaign_replay_receipt(build_agent_control_plane(), run)
        codes = {row["blocker_code"] for row in receipt["blockers"]}
        self.assertIn("missing_evidence_artifact", codes)
        self.assertIn("missing_high_risk_authorization", codes)
        self.assertTrue(all(row["generic_copy_fallback_allowed"] is False for row in receipt["blockers"]))

    def test_tampering_fails(self) -> None:
        receipt = compile_campaign_replay_receipt(build_agent_control_plane(), complete_run()); broken = copy.deepcopy(receipt); broken["external_action_executed"] = True
        with self.assertRaises(Exception): verify_campaign_replay_receipt(broken)


if __name__ == "__main__": unittest.main()
