from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import torch

from parcel_sorter.pi05_direct_action_head_adapter import (
    PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3,
    PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4,
    PI05_DIRECT_ACTION_STATE_RESIDUAL_MODULE,
)
from parcel_sorter.pi05_mode_head_adapter import (
    PI05_MODE_HEAD_STATE_RESIDUAL_MODULE,
    PI05_STRUCTURED_DECISION_HEAD_STATE_RESIDUAL_PROTOCOL,
)
from parcel_sorter.pi05_weighted_loss import (
    PI05_DIRECT_ACTION_UNBOUNDED_TARGET_PROTOCOL,
)
from parcel_sorter.mobile_pi05_training_contract import _payload_sha256


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "calibrate_mobile_pi05_heads_rocm",
    ROOT / "scripts" / "calibrate_mobile_pi05_heads_rocm.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CalibrateMobilePi05HeadsTest(unittest.TestCase):
    def _manifest(self) -> dict:
        pools = {
            f"cell-{cell:02d}": [cell * 100 + offset for offset in range(20)]
            for cell in range(60)
        }
        return {
            "protocol": "parcel-competition-mode-stage-progress-sampler-v1",
            "indices_by_cell": pools,
        }

    def test_selects_fixed_prefix_from_every_cell(self) -> None:
        selected = MODULE.select_competition_indices(
            self._manifest(), samples_per_cell=10
        )
        self.assertEqual(len(selected), 600)
        self.assertEqual(len(set(selected)), 600)
        self.assertEqual(selected[:10], list(range(10)))

    def test_rejects_incomplete_manifest(self) -> None:
        manifest = self._manifest()
        manifest["indices_by_cell"].pop("cell-00")
        with self.assertRaisesRegex(ValueError, "60"):
            MODULE.select_competition_indices(manifest, samples_per_cell=10)

    def test_rejects_duplicate_selected_frames(self) -> None:
        manifest = self._manifest()
        manifest["indices_by_cell"]["cell-01"][0] = 0
        with self.assertRaisesRegex(ValueError, "not unique"):
            MODULE.select_competition_indices(manifest, samples_per_cell=10)

    def test_calibration_keeps_out_of_quantile_target_only_for_v4(self) -> None:
        action = torch.tensor([[4.0, -3.0, 0.5]])

        v3 = MODULE.prepare_calibration_direct_action_target(
            action, direct_action_head_protocol=PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3
        )
        v4 = MODULE.prepare_calibration_direct_action_target(
            action, direct_action_head_protocol=PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4
        )

        torch.testing.assert_close(v3, torch.tensor([[1.0, -1.0, 0.5]]))
        torch.testing.assert_close(v4, action)

    def test_protocol_promotion_copies_v3_and_binds_v4_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "promoted"
            source.mkdir()
            (source / "adapter_model.safetensors").write_bytes(b"adapter")
            (source / "adapter_config.json").write_text(
                json.dumps(
                    {
                        "modules_to_save": [
                            PI05_DIRECT_ACTION_STATE_RESIDUAL_MODULE,
                            PI05_MODE_HEAD_STATE_RESIDUAL_MODULE,
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source_contract = {
                "direct_action_head_protocol": PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3,
                "direct_action_target_protocol": (
                    "normalized_quantile_clipped_first_action_v2"
                ),
                "mode_head_protocol": (
                    PI05_STRUCTURED_DECISION_HEAD_STATE_RESIDUAL_PROTOCOL
                ),
            }
            (source / "PI05_TRAINING_CONTRACT.json").write_text(
                json.dumps(source_contract), encoding="utf-8"
            )

            provenance = MODULE.promote_v3_checkpoint_to_linear_v4(source, output)
            source_after = json.loads(
                (source / "PI05_TRAINING_CONTRACT.json").read_text(encoding="utf-8")
            )
            promoted = json.loads(
                (output / "PI05_TRAINING_CONTRACT.json").read_text(encoding="utf-8")
            )

        self.assertEqual(source_after, source_contract)
        self.assertEqual(
            promoted["direct_action_head_protocol"],
            PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4,
        )
        self.assertEqual(
            promoted["direct_action_target_protocol"],
            PI05_DIRECT_ACTION_UNBOUNDED_TARGET_PROTOCOL,
        )
        self.assertEqual(
            promoted["direct_action_protocol_promotion"], provenance
        )
        self.assertEqual(
            provenance["source_direct_action_head_protocol"],
            PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3,
        )
        fingerprinted = dict(promoted)
        contract_sha256 = fingerprinted.pop("contract_sha256")
        self.assertEqual(contract_sha256, _payload_sha256(fingerprinted))

    def test_promotion_temp_creates_only_missing_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "checkpoints" / "000400"

            scratch = MODULE.create_protocol_promotion_temp_directory(output)
            try:
                scratch_path = Path(scratch.name)
                self.assertTrue(output.parent.is_dir())
                self.assertTrue(scratch_path.is_dir())
                self.assertFalse(output.exists())
            finally:
                scratch.cleanup()

    def test_mode_only_scope_freezes_direct_action_modules(self) -> None:
        class SavedModule(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.modules_to_save = torch.nn.ModuleDict(
                    {"default": torch.nn.Linear(2, 2)}
                )

        policy = torch.nn.Module()
        policy.base_model = torch.nn.Module()
        policy.base_model.model = torch.nn.Module()
        for name in MODULE.HEAD_MODULE_NAMES:
            setattr(policy.base_model.model, name, SavedModule())

        trainable = MODULE._enable_saved_heads(
            policy, module_names=MODULE.MODE_ONLY_MODULE_NAMES
        )
        trainable_names = [name for name, _ in trainable]

        self.assertTrue(trainable_names)
        self.assertTrue(all("mode_head" in name for name in trainable_names))
        for name, parameter in policy.named_parameters():
            if "direct_action" in name:
                self.assertFalse(parameter.requires_grad)
            elif "modules_to_save.default" in name:
                self.assertTrue(parameter.requires_grad)

    def test_rejects_unknown_saved_head_selection(self) -> None:
        policy = torch.nn.Linear(2, 2)
        with self.assertRaisesRegex(ValueError, "invalid"):
            MODULE._enable_saved_heads(policy, module_names=("unknown",))


if __name__ == "__main__":
    unittest.main()
