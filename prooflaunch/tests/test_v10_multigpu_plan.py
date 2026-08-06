from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_multigpu import (
    ExecutionClass,
    build_multigpu_plan,
    execution_class_for,
)


ROOT = Path(__file__).resolve().parents[1]


class V10MultiGpuPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.program = json.loads(
            (
                ROOT / "evidence" / "v10" / "program-manifest.json"
            ).read_text(encoding="utf-8")
        )

    def test_all_1500_todos_bind_to_the_program_policy(self) -> None:
        plans = build_multigpu_plan(self.program["todos"])
        self.assertEqual(len(plans), 1500)
        self.assertTrue(
            all(item.program_multigpu_binding for item in plans)
        )
        self.assertTrue(
            all("truthful_no_silent_fallback" in item.required_gates for item in plans)
        )
        generated = json.loads(
            (
                ROOT
                / "evidence"
                / "v10"
                / "multigpu-execution-plan.json"
            ).read_text(encoding="utf-8")
        )
        launches = generated["launch_contracts"]
        self.assertIn("--parallelism single", launches["gemma_single_gpu_baseline"])
        self.assertIn("--parallelism ddp", launches["gemma_ddp_2gpu"])
        self.assertIn("--parallelism fsdp2", launches["gemma_fsdp2_2gpu"])
        self.assertIn(
            "verify_multigpu_training_admission.py",
            launches["training_admission"],
        )
        expected_contract_hash = generated.pop("contract_sha256")
        canonical = json.dumps(
            generated,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            expected_contract_hash,
        )

    def test_training_uses_ddp_then_fsdp2_and_never_device_map(self) -> None:
        plans = build_multigpu_plan(self.program["todos"])
        training = [
            item
            for item in plans
            if item.execution_class is ExecutionClass.TRAINING
        ]
        self.assertTrue(training)
        self.assertTrue(
            all(
                item.preferred_strategy
                == "ddp_after_memory_fit_preflight"
                and item.fallback_strategy
                == "fsdp2_after_equivalence_preflight"
                and item.minimum_world_size == 2
                for item in training
            )
        )

    def test_non_gpu_atomic_work_is_program_bound_not_fake_gpu_work(self) -> None:
        plans = build_multigpu_plan(self.program["todos"])
        rules_task = plans[0]
        self.assertEqual(
            rules_task.execution_class,
            ExecutionClass.CONTROLLER,
        )
        self.assertFalse(
            rules_task.requires_direct_multigpu_observation
        )
        self.assertEqual(rules_task.minimum_world_size, 1)

    def test_every_workstream_has_exactly_one_execution_class(self) -> None:
        observed = {
            int(todo["workstream_id"]) for todo in self.program["todos"]
        }
        self.assertEqual(observed, set(range(1, 37)))
        self.assertEqual(
            {execution_class_for(item) for item in observed},
            set(ExecutionClass),
        )

    def test_current_single_gpu_radeon_preflight_blocks_multigpu_claim(
        self,
    ) -> None:
        receipt = json.loads(
            (
                ROOT
                / "evidence"
                / "RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["observed"]["torchCudaDeviceCount"], 1)
        self.assertEqual(
            receipt["requiredForDirectMultiGpuEvidence"][
                "minimumPhysicalGpuCount"
            ],
            2,
        )
        self.assertFalse(
            receipt["effect"]["singleGpuMaySatisfyMultiGpuClaim"]
        )
        self.assertEqual(
            receipt["effect"]["directMultiGpuTodoCount"],
            1100,
        )
        browser_sync = json.loads(
            (
                ROOT / "evidence" / "RADEON_BROWSER_SYNC_2026-07-30.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            browser_sync["uploads"][0][
                "localMetadataBoundToUploadPayload"
            ]["directMultiGpuObservationTodoCount"],
            1100,
        )
        self.assertFalse(
            browser_sync["uploads"][0][
                "localMetadataBoundToUploadPayload"
            ]["allowedSilentSingleGpuFallback"]
        )


if __name__ == "__main__":
    unittest.main()
