from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_multimodal_seed_compiler import compile_multimodal_seed
from prooflaunch_remix.gtm_omnichannel_activation import (
    OmnichannelActivationError,
    compile_omnichannel_activation,
    verify_omnichannel_activation,
)


ROOT = Path(__file__).resolve().parents[1]


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class OmnichannelActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        execution = json.loads(
            (
                ROOT
                / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/text-creative-challenger-execution.json"
            ).read_text(encoding="utf-8")
        )
        candidate = execution["candidates"][0]["candidate"]
        plan = json.loads(
            (
                ROOT
                / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/text-creative-challenger-plan.json"
            ).read_text(encoding="utf-8")
        )
        admission: dict[str, object] = {
            "schema": "ProofLaunchMultimodalProductionAdmissionV1",
            "campaign_id": plan["campaign_id"],
            "strategy_id": plan["strategy_id"],
            "challenger_plan_sha256": plan["content_sha256"],
            "proof_claim_id": plan["proof_claim_id"],
            "selected_territory_id": candidate["territory_id"],
            "selected_candidate_content_sha256": candidate[
                "candidate_content_sha256"
            ],
            "selected_candidate": candidate,
            "prompt_compilation_authorized": True,
            "gpu_execution_authorized": False,
            "spend_authorized": False,
            "external_publish_authorized": False,
            "effect_claim_eligible": False,
            "content_sha256": None,
        }
        admission["content_sha256"] = digest(admission)
        bindings = json.loads(
            (ROOT / "config/comfyui_execution_bindings_v1.json").read_text(
                encoding="utf-8"
            )
        )
        handoff = json.loads(
            (
                ROOT / "artifacts/comfyui-gpu-handoff-20260801/handoff.json"
            ).read_text(encoding="utf-8")
        )
        self.admission = admission
        self.multimodal = compile_multimodal_seed(admission, bindings, handoff)

    def test_human_selected_system_compiles_nine_bound_activation_lanes(self) -> None:
        plan = compile_omnichannel_activation(self.admission, self.multimodal)
        verify_omnichannel_activation(plan)
        self.assertEqual(plan["lane_count"], 9)
        self.assertEqual(plan["campaign_id"], "prooflaunch-zero-budget-b2b-v1")
        self.assertEqual(len(plan["lanes"]), 9)
        self.assertTrue(plan["same_creative_system_across_lanes"])
        self.assertTrue(plan["same_evidence_spine_across_lanes"])
        self.assertEqual(plan["external_actions_executed"], 0)
        self.assertFalse(plan["effect_claim_eligible"])
        self.assertTrue(
            all(lane["human_release_required"] for lane in plan["lanes"])
        )
        self.assertTrue(
            all(not lane["automatic_publish_enabled"] for lane in plan["lanes"])
        )
        by_id = {lane["lane_id"]: lane["draft"] for lane in plan["lanes"]}
        self.assertEqual(
            by_id["landing_page"]["supporting_proof"], plan["approved_proof"]
        )
        self.assertEqual(
            by_id["content_schedule"]["slot_count"], 7
        )
        self.assertFalse(
            by_id["effect_instrumentation"]["causal_revenue_claim_allowed"]
        )

    def test_tampering_or_wrong_multimodal_binding_fails_closed(self) -> None:
        plan = compile_omnichannel_activation(self.admission, self.multimodal)
        tampered = dict(plan)
        tampered["automatic_publish_enabled"] = True
        with self.assertRaises(OmnichannelActivationError):
            verify_omnichannel_activation(tampered)
        wrong = dict(self.multimodal)
        wrong["multimodal_admission_sha256"] = "0" * 64
        wrong["content_sha256"] = None
        wrong["content_sha256"] = digest(wrong)
        with self.assertRaisesRegex(
            OmnichannelActivationError, "not bound"
        ):
            compile_omnichannel_activation(self.admission, wrong)


if __name__ == "__main__":
    unittest.main()
