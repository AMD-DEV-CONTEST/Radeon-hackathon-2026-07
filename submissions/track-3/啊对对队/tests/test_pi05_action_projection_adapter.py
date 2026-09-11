import unittest

from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_MODULES,
    checkpoint_uses_full_pi05_action_projections,
    configure_pi05_full_action_projection_peft_defaults,
)


class PI05ActionProjectionAdapterTests(unittest.TestCase):
    def test_moves_action_io_from_lora_targets_to_full_modules(self) -> None:
        configured = configure_pi05_full_action_projection_peft_defaults(
            {
                "target_modules": (
                    "(gemma_expert|action_in_proj|action_out_proj|"
                    "action_time_mlp_in|action_time_mlp_out)"
                ),
                "modules_to_save": ["state_proj", "mode_head"],
            }
        )

        for module in PI05_FULL_ACTION_PROJECTION_MODULES:
            self.assertNotIn(module, configured["target_modules"])
            self.assertIn(module, configured["modules_to_save"])
        self.assertIn("action_time_mlp_in", configured["target_modules"])
        self.assertTrue(checkpoint_uses_full_pi05_action_projections(configured))

    def test_requires_both_projections(self) -> None:
        self.assertFalse(
            checkpoint_uses_full_pi05_action_projections(
                {"modules_to_save": ["action_in_proj"]}
            )
        )


if __name__ == "__main__":
    unittest.main()
