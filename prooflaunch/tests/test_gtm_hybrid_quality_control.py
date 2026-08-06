from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_hybrid_quality_control import (
    HybridQualityControlError,
    compile_hybrid_quality_control,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMHybridQualityControlTests(unittest.TestCase):
    def compile(self, root: Path = ROOT) -> dict[str, object]:
        return compile_hybrid_quality_control(
            project_root=root,
            ledger_path=root / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json",
            challenger_admission_path=root / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json",
            capture_manifest_path=root / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json",
            local_discovery_path=root / "evidence/v10/local-first-model-resource-discovery.json",
            cloud_plan_path=root / "evidence/v10/free-cloud-execution-plan-v2.json",
        )

    def test_compiles_thirteen_ready_local_lanes_and_130_real_pk_jobs(self) -> None:
        payload = self.compile()
        self.assertEqual(len(payload["lanes"]), 13)
        self.assertEqual(len(payload["jobs"]), 130)
        self.assertEqual(payload["portfolio"]["local_ready_category_count"], 13)
        self.assertEqual(payload["portfolio"]["challenger_dossier_count_admitted"], 13)
        self.assertTrue(all(job["candidate_status"] == "READY_LOCAL_CANDIDATE" for job in payload["jobs"]))
        self.assertTrue(all(len(job["quality_axis_score_contract"]) > 0 for job in payload["jobs"]))

    def test_cloud_and_radeon_are_optional_without_weakening_human_gate(self) -> None:
        payload = self.compile()
        invariants = payload["routing_invariants"]
        self.assertTrue(invariants["hardware_and_provider_are_replaceable"])
        self.assertTrue(invariants["local_pipeline_continues_without_cloud"])
        self.assertFalse(invariants["radeon_required_for_product_closure"])
        self.assertFalse(invariants["model_judge_can_promote"])
        self.assertTrue(invariants["human_release_required"])
        self.assertFalse(payload["portfolio"]["product_local_runtime_blocked_by_cloud"])
        self.assertEqual(payload["portfolio"]["candidate_wins"], 0)

    def test_every_lane_has_located_outputs_gates_failures_and_pinned_reuse(self) -> None:
        payload = self.compile()
        for lane in payload["lanes"]:
            self.assertGreaterEqual(len(lane["output_contract"]), 5)
            self.assertGreaterEqual(len(lane["hard_gates"]), 5)
            self.assertGreaterEqual(len(lane["failure_signals"]), 4)
            self.assertTrue(lane["open_source_reuse"])
            self.assertTrue(all(project["revision"] for project in lane["open_source_reuse"]))

    def test_all_thirteen_lanes_and_130_jobs_bind_specialist_craft_execution(self) -> None:
        payload = self.compile()
        playbooks = [lane["specialist_craft_playbook"] for lane in payload["lanes"]]
        self.assertEqual(len({row["content_sha256"] for row in playbooks}), 13)
        self.assertEqual(sum(row["work_order_count"] for row in playbooks), 153)
        self.assertEqual(
            sum(row["selected_atomic_skill_assignment_count"] for row in playbooks),
            718,
        )
        self.assertTrue(
            all(
                not set(row["producer_role_ids"]) & set(row["reviewer_role_ids"])
                and row["review_loop"]["maximum_revision_rounds"] == 1
                and row["review_loop"]["all_three_must_re_review_after_repair"]
                for row in playbooks
            )
        )
        self.assertEqual(
            sum(
                job["specialist_craft_job_binding"]["automatic_external_action_count"]
                for job in payload["jobs"]
            ),
            0,
        )
        self.assertTrue(
            all(
                job["specialist_craft_job_binding"]["frozen_brief_sha256"]
                == job["frozen_brief_sha256"]
                for job in payload["jobs"]
            )
        )

    def test_tampered_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = json.loads((ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json").read_text())
            ledger["product_pk_rows"][0]["comparison_status"] = "won"
            path.write_text(json.dumps(ledger), encoding="utf-8")
            with self.assertRaisesRegex(HybridQualityControlError, "digest"):
                compile_hybrid_quality_control(
                    project_root=ROOT,
                    ledger_path=path,
                    challenger_admission_path=ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json",
                    capture_manifest_path=ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json",
                    local_discovery_path=ROOT / "evidence/v10/local-first-model-resource-discovery.json",
                    cloud_plan_path=ROOT / "evidence/v10/free-cloud-execution-plan-v2.json",
                )


if __name__ == "__main__":
    unittest.main()
