import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from parcel_sorter.mobile_dataset import mobile_policy_visual_keys
from parcel_sorter.mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    PI05_GRASP_MODES,
)
from parcel_sorter.mobile_pi05_research_protocol import (
    PI05_TASK_STAGES,
    PI05_TINY_OVERFIT_ROLE,
    build_stage_panel,
    build_training_launch_audit,
    file_sha256,
    validate_tiny_overfit_gate,
)
from parcel_sorter.mobile_pi05_training_contract import build_pi05_training_contract
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
)


SCRIPT = Path(__file__).parents[1] / "scripts/write_mobile_pi05_tiny_overfit_gate.py"
SPEC = importlib.util.spec_from_file_location("write_mobile_pi05_tiny_overfit_gate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WriteMobilePI05TinyOverfitGateTests(unittest.TestCase):
    def test_writes_gate_only_for_complete_fingerprinted_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset"
            (dataset / "meta").mkdir(parents=True)
            (dataset / "meta/info.json").write_text(
                json.dumps(
                    {
                        "fps": 30,
                        "total_frames": 18,
                        "features": {
                            "observation.state": {
                                "shape": [80],
                                "names": list(MOBILE_PI05_ABSOLUTE_STATE_NAMES),
                            },
                            "action": {
                                "shape": [23],
                                "names": list(MOBILE_PI05_ABSOLUTE_ACTION_NAMES),
                            },
                            **{
                                key: {"shape": [224, 224, 3]}
                                for key in mobile_policy_visual_keys("rgbd")
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (dataset / "meta/stats.json").write_text("{}\n", encoding="utf-8")
            manifest_path = dataset / "PI05_ABSOLUTE_DATASET_MANIFEST.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "action_contract": "absolute_v1",
                        "normalization_stats_policy": "quantile-v1",
                        "mode_conditioning_policy": "hidden_all_stages",
                        "task_language_policy": "mode_blind",
                    }
                ),
                encoding="utf-8",
            )
            observations = []
            index = 0
            for mode in PI05_GRASP_MODES:
                for stage in PI05_TASK_STAGES:
                    observations.append(
                        {
                            "observation_id": f"observation-{index}",
                            "dataset_index": index,
                            "episode_index": index,
                            "source_identity": "tiny-source",
                            "grasp_mode": mode,
                            "stage": stage,
                            "action_label_available": True,
                        }
                    )
                    index += 1
            panel = build_stage_panel(
                observations,
                role=PI05_TINY_OVERFIT_ROLE,
                dataset_root=dataset,
                dataset_manifest_sha256=file_sha256(manifest_path),
                minimum_observations_per_mode_stage=1,
                minimum_independent_sources_per_mode=1,
            )
            thresholds = json.loads(
                (
                    Path(__file__).parents[1]
                    / "configs/mobile_pi05_tiny_overfit_action_thresholds_v1.json"
                ).read_text(encoding="utf-8")
            )
            launch = build_training_launch_audit(
                training_role="tiny_overfit",
                action_contract="absolute_v1",
                dataset_manifest_sha256=panel["dataset_manifest_sha256"],
                requested_training_steps=100,
                scheduler_warmup_steps=10,
                scheduler_decay_steps=100,
                stage_panel=panel,
                action_thresholds=thresholds,
            )
            contract = build_pi05_training_contract(
                dataset,
                base_model="pi05_base",
                base_revision="abc",
                chunk_size=30,
                n_action_steps=1,
                action_projection_protocol=PI05_FULL_ACTION_PROJECTION_PROTOCOL,
                training_role="tiny_overfit",
                requested_training_steps=100,
                training_batch_size=1,
                scheduler_type="cosine_decay",
                scheduler_warmup_steps=10,
                scheduler_decay_steps=100,
                training_launch_audit=launch,
            )
            contract_path = root / "PI05_TRAINING_CONTRACT.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            checkpoint = root / "checkpoints/000100/pretrained_model"
            checkpoint.mkdir(parents=True)
            (checkpoint / "adapter_model.safetensors").write_text(
                "adapter", encoding="utf-8"
            )
            screen = {
                "protocol": MODULE.SCREEN_PROTOCOL,
                "status": "passed",
                "checkpoint": str(checkpoint),
                "observation_panel_role": PI05_TINY_OVERFIT_ROLE,
                "stage_panel_sha256": panel["panel_sha256"],
                "action_thresholds_sha256": thresholds["thresholds_sha256"],
                "dataset_manifest_sha256": panel["dataset_manifest_sha256"],
                "action_contract": "pi05_absolute_v1",
                "routing_error_count": 0,
                "action_fidelity_error_count": 0,
                "structural_error_count": 0,
                "mode_stage_cells": 18,
                "errors": [],
            }
            screen_path = root / "screen.json"
            screen_path.write_text(json.dumps(screen), encoding="utf-8")
            screen["screen_path"] = str(screen_path)

            gate = MODULE.build_gate(
                screen=screen,
                panel=panel,
                thresholds=thresholds,
                checkpoint=checkpoint,
                training_contract=contract_path,
            )

        self.assertEqual(validate_tiny_overfit_gate(gate)["status"], "passed")


if __name__ == "__main__":
    unittest.main()
