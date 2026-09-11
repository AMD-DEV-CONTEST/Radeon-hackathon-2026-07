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
    PI05_TINY_OVERFIT_GATE_PROTOCOL,
    PI05_TINY_OVERFIT_ROLE,
    build_training_launch_audit,
    canonical_payload_sha256,
    file_sha256,
)
from parcel_sorter.mobile_pi05_training_contract import build_pi05_training_contract
from parcel_sorter.mobile_pi05_training_contract import _payload_sha256
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
)

SCRIPT = Path(__file__).parents[1] / "scripts" / "select_mobile_pi05_route_checkpoint.py"
SPEC = importlib.util.spec_from_file_location("select_pi05_checkpoint", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

RESUME_SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "audit_mobile_pi05_resume_training.py"
)
RESUME_SPEC = importlib.util.spec_from_file_location("audit_pi05_resume", RESUME_SCRIPT)
RESUME_MODULE = importlib.util.module_from_spec(RESUME_SPEC)
assert RESUME_SPEC.loader is not None
RESUME_SPEC.loader.exec_module(RESUME_MODULE)


def _write_checkpoint(root: Path, step: int) -> Path:
    checkpoint = root / "checkpoints" / f"{step:06d}" / "pretrained_model"
    checkpoint.mkdir(parents=True)
    for name in (
        "adapter_model.safetensors",
        "adapter_config.json",
        "config.json",
        "train_config.json",
    ):
        (checkpoint / name).write_text(name, encoding="utf-8")
    _write_training_contract(root)
    return checkpoint


def _write_training_contract(root: Path) -> None:
    path = root / "PI05_TRAINING_CONTRACT.json"
    if path.is_file():
        return
    dataset = root / "dataset"
    (dataset / "meta").mkdir(parents=True)
    (dataset / "meta/info.json").write_text(
        json.dumps(
            {
                "fps": 30,
                "total_frames": 100,
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
    tiny_gate = {
        "schema_version": 1,
        "protocol": PI05_TINY_OVERFIT_GATE_PROTOCOL,
        "status": "passed",
        "panel_role": PI05_TINY_OVERFIT_ROLE,
        "action_contract": "absolute_v1",
        "routing_error_count": 0,
        "action_fidelity_error_count": 0,
        "structural_error_count": 0,
        "mode_stage_cells": 18,
        "panel_sha256": "1" * 64,
        "thresholds_sha256": "2" * 64,
        "checkpoint_sha256": "3" * 64,
        "training_contract_sha256": "4" * 64,
        "dataset_manifest_sha256": "5" * 64,
        "screen_sha256": "6" * 64,
    }
    tiny_gate["gate_sha256"] = canonical_payload_sha256(
        tiny_gate, hash_field="gate_sha256"
    )
    launch_audit = build_training_launch_audit(
        training_role="candidate",
        action_contract="absolute_v1",
        dataset_manifest_sha256=file_sha256(manifest_path),
        requested_training_steps=12000,
        scheduler_warmup_steps=1000,
        scheduler_decay_steps=12000,
        tiny_overfit_gate=tiny_gate,
        independent_source_counts={mode: 2 for mode in PI05_GRASP_MODES},
    )
    (root / "PI05_TRAINING_LAUNCH_AUDIT.json").write_text(
        json.dumps(launch_audit), encoding="utf-8"
    )
    contract = build_pi05_training_contract(
        dataset,
        base_model="pi05_base",
        base_revision="abc",
        chunk_size=30,
        n_action_steps=1,
        action_projection_protocol=PI05_FULL_ACTION_PROJECTION_PROTOCOL,
        training_role="candidate",
        requested_training_steps=12000,
        training_batch_size=1,
        scheduler_type="cosine_decay",
        scheduler_warmup_steps=1000,
        scheduler_decay_steps=12000,
        training_launch_audit=launch_audit,
    )
    path.write_text(json.dumps(contract), encoding="utf-8")


def _write_screen(root: Path, step: int, *, passed: bool = True) -> Path:
    checkpoint = _write_checkpoint(root, step)
    contract = json.loads(
        (root / "PI05_TRAINING_CONTRACT.json").read_text(encoding="utf-8")
    )
    path = root / f"step-{step}.json"
    payload = {
        "protocol": MODULE.SCREEN_PROTOCOL,
        "status": "passed" if passed else "failed",
        "checkpoint": str(checkpoint),
        "dataset": "/frozen/development",
        "action_contract": "pi05_absolute_v1",
        "observation_panel_role": MODULE.PANEL_ROLE,
        "stage_panel_sha256": "a" * 64,
        "action_thresholds_sha256": "b" * 64,
        "dataset_manifest_sha256": contract["dataset_manifest_sha256"],
        "deployment_calibrated_thresholds": True,
        "sample_seeds": [11, 12, 13],
        "action_fidelity_required": True,
        "mode_stage_cells": 18,
        "routing_error_count": 0 if passed else 1,
        "action_fidelity_error_count": 0,
        "structural_error_count": 0,
        "errors": [] if passed else ["mode_error"],
        "metrics": {
            "probes": 18,
            "correct_probes": 18 if passed else 17,
            "probe_accuracy": 1.0 if passed else 17 / 18,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class PI05RouteCheckpointSelectionTests(unittest.TestCase):
    def test_selects_earliest_complete_stage_action_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screens = [_write_screen(root, step) for step in (12000, 3000, 9000, 6000)]

            result = MODULE.select_checkpoint(screens, expected_count=4)

            self.assertEqual(result["selected_step"], 3000)
            self.assertEqual(result["stage_panel_sha256"], "a" * 64)
            self.assertEqual(len(result["candidates"]), 4)

    def test_rejects_incomplete_checkpoint_panel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screens = [_write_screen(root, step) for step in (3000, 6000, 9000)]

            with self.assertRaisesRegex(ValueError, "expected 4"):
                MODULE.select_checkpoint(screens, expected_count=4)

    def test_skips_a_failed_earlier_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screens = [
                _write_screen(root, 3000, passed=False),
                _write_screen(root, 6000),
                _write_screen(root, 9000),
                _write_screen(root, 12000),
            ]

            result = MODULE.select_checkpoint(screens, expected_count=4)

            self.assertEqual(result["selected_step"], 6000)

    def test_rejects_route_only_screen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screens = [_write_screen(root, step) for step in (3000, 6000, 9000, 12000)]
            payload = json.loads(screens[0].read_text(encoding="utf-8"))
            payload["action_fidelity_required"] = False
            screens[0].write_text(json.dumps(payload), encoding="utf-8")

            result = MODULE.select_checkpoint(screens, expected_count=4)

            self.assertEqual(result["selected_step"], 6000)
            self.assertFalse(result["candidates"][0]["stage_action_gate_passed"])

    def test_rejects_checkpoint_screens_mixed_across_training_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screens = [
                _write_screen(root, 3000),
                _write_screen(root, 6000),
                _write_screen(root, 9000),
                _write_screen(root / "other-run", 12000),
            ]

            with self.assertRaisesRegex(ValueError, "one training run"):
                MODULE.select_checkpoint(screens, expected_count=4)


class PI05ResumeAuditTests(unittest.TestCase):
    def test_accepts_only_an_exact_candidate_contract_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = _write_checkpoint(root, 6000)
            existing = root / "PI05_TRAINING_CONTRACT.json"
            proposed = root / "proposed-contract.json"
            proposed.write_bytes(existing.read_bytes())
            existing_launch_audit = root / "PI05_TRAINING_LAUNCH_AUDIT.json"
            proposed_launch_audit = root / "proposed-launch-audit.json"
            proposed_launch_audit.write_bytes(existing_launch_audit.read_bytes())

            audit = RESUME_MODULE.audit_resume(
                existing_contract_path=existing,
                proposed_contract_path=proposed,
                existing_launch_audit_path=existing_launch_audit,
                proposed_launch_audit_path=proposed_launch_audit,
                checkpoint=checkpoint,
                checkpoint_step=6000,
            )

            self.assertEqual(audit["status"], "passed")
            self.assertEqual(audit["checkpoint_step"], 6000)

            changed = json.loads(proposed.read_text(encoding="utf-8"))
            changed["base_revision"] = "different"
            changed.pop("contract_sha256")
            changed["contract_sha256"] = _payload_sha256(changed)
            proposed.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "change the frozen"):
                RESUME_MODULE.audit_resume(
                    existing_contract_path=existing,
                    proposed_contract_path=proposed,
                    existing_launch_audit_path=existing_launch_audit,
                    proposed_launch_audit_path=proposed_launch_audit,
                    checkpoint=checkpoint,
                    checkpoint_step=6000,
                )


if __name__ == "__main__":
    unittest.main()
