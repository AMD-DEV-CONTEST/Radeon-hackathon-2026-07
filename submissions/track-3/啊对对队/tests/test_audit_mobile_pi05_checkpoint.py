import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_mobile_pi05_checkpoint.py"
SPEC = importlib.util.spec_from_file_location("audit_mobile_pi05_checkpoint", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AuditMobilePI05CheckpointTests(unittest.TestCase):
    def test_accepts_both_supported_action_name_contracts(self) -> None:
        for names in (
            MODULE.MOBILE_PI05_RESIDUAL_ACTION_NAMES,
            MODULE.MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
        ):
            self.assertEqual(MODULE._supported_action_names(list(names)), tuple(names))

        self.assertIsNone(MODULE._supported_action_names(["unknown_action"]))

    def test_shape_element_count(self) -> None:
        self.assertEqual(MODULE._shape_elements((2, 3, 4)), 24)
        self.assertEqual(MODULE._shape_elements(()), 1)

    def test_payload_never_claims_capability(self) -> None:
        payload = MODULE._payload(Path("checkpoint"), [], {"adapter_tensor_count": 1})

        self.assertEqual(payload["status"], "passed")
        self.assertIn("does not measure", payload["claim_boundary"])

    def test_expected_lora_hyperparameters_are_enforced(self) -> None:
        errors: list[str] = []
        MODULE._validate_adapter_hyperparameters(
            {"r": 16, "lora_alpha": 64},
            errors,
            expected_lora_rank=32,
            expected_lora_alpha=32,
        )

        self.assertEqual(errors, ["lora_rank_mismatch", "lora_alpha_mismatch"])

    def test_unspecified_lora_hyperparameters_are_not_constrained(self) -> None:
        errors: list[str] = []
        MODULE._validate_adapter_hyperparameters(
            {"r": 16, "lora_alpha": 32},
            errors,
            expected_lora_rank=None,
            expected_lora_alpha=None,
        )

        self.assertEqual(errors, [])

    def test_full_projection_modules_are_part_of_static_audit(self) -> None:
        self.assertEqual(
            MODULE.PI05_FULL_ACTION_PROJECTION_MODULES,
            ("action_in_proj", "action_out_proj"),
        )

    def test_full_projection_requirement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory)
            required_files = (
                "adapter_model.safetensors",
                "train_config.json",
                "policy_preprocessor.json",
                "policy_postprocessor.json",
                "policy_preprocessor_step_3_normalizer_processor.safetensors",
                "policy_postprocessor_step_0_unnormalizer_processor.safetensors",
            )
            for name in required_files:
                (checkpoint / name).write_bytes(b"placeholder")
            (checkpoint / "adapter_config.json").write_text(
                json.dumps(
                    {
                        "base_model_name_or_path": "/base",
                        "modules_to_save": ["state_proj", "mode_head"],
                        "peft_type": "LORA",
                        "r": 16,
                        "lora_alpha": 32,
                    }
                ),
                encoding="utf-8",
            )
            (checkpoint / "config.json").write_text(
                json.dumps(
                    {
                        "input_features": {
                            "observation.state": {
                                "shape": [len(MODULE.MOBILE_PI05_STATE_NAMES)]
                            }
                        },
                        "output_features": {
                            "action": {
                                "shape": [
                                    len(MODULE.MOBILE_PI05_ABSOLUTE_ACTION_NAMES)
                                ]
                            }
                        },
                        "action_feature_names": list(
                            MODULE.MOBILE_PI05_ABSOLUTE_ACTION_NAMES
                        ),
                        "normalization_mapping": {
                            "STATE": "QUANTILES",
                            "ACTION": "QUANTILES",
                        },
                        "use_relative_actions": False,
                        "type": "pi05",
                        "use_peft": True,
                        "pretrained_path": "/base",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                MODULE, "_safetensor_inventory", return_value=([], {})
            ):
                payload = MODULE.audit_checkpoint(
                    checkpoint, require_full_action_projections=True
                )

        self.assertIn("missing_full_action_projections", payload["errors"])


if __name__ == "__main__":
    unittest.main()
