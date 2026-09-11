import unittest

import torch

from parcel_sorter.pi05_state_token_adapter import (
    checkpoint_uses_pi05_state_token,
    configure_pi05_state_token_peft_defaults,
    prepare_pi05_state_token_input,
)


class PI05StateTokenAdapterTests(unittest.TestCase):
    def test_preparation_zeros_hidden_mode_and_pads_state(self) -> None:
        state = torch.arange(160, dtype=torch.float32).reshape(2, 80)

        prepared = prepare_pi05_state_token_input(state, max_state_dim=96)

        self.assertEqual(tuple(prepared.shape), (2, 96))
        self.assertTrue(torch.equal(prepared[:, 52:55], torch.zeros(2, 3)))
        self.assertTrue(torch.equal(prepared[:, 74:80], torch.zeros(2, 6)))
        self.assertTrue(torch.equal(prepared[:, 80:], torch.zeros(2, 16)))
        self.assertTrue(torch.equal(prepared[:, :52], state[:, :52]))

    def test_rejects_wrong_state_width(self) -> None:
        with self.assertRaises(ValueError):
            prepare_pi05_state_token_input(torch.zeros(1, 79), max_state_dim=96)

    def test_peft_saves_projection_fully(self) -> None:
        defaults = {
            "target_modules": "(state_proj|action_in_proj|action_out_proj)",
            "modules_to_save": [],
        }

        configured = configure_pi05_state_token_peft_defaults(defaults)

        self.assertNotIn("state_proj|", configured["target_modules"])
        self.assertEqual(configured["modules_to_save"], ["state_proj"])
        self.assertTrue(checkpoint_uses_pi05_state_token(configured))


if __name__ == "__main__":
    unittest.main()
