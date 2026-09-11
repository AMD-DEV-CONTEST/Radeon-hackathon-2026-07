import unittest
from types import SimpleNamespace

import torch

from parcel_sorter.pi05_mode_head_adapter import (
    PI05_MODE_HEAD_POOLING_LAST_LANGUAGE_TOKEN,
    PI05_MODE_HEAD_PROTOCOL,
    checkpoint_uses_pi05_mode_head,
    configure_pi05_mode_head_peft_defaults,
    pi05_mode_head_pooling_from_protocol,
    pi05_mode_head_protocol,
    pi05_mode_head_logits,
    pool_pi05_contextualized_prefix,
)


class PI05ModeHeadAdapterTests(unittest.TestCase):
    def test_peft_saves_fused_mode_head_fully(self) -> None:
        configured = configure_pi05_mode_head_peft_defaults(
            {"target_modules": "(action_in_proj|action_out_proj)", "modules_to_save": []}
        )

        self.assertEqual(configured["modules_to_save"], ["mode_head"])
        self.assertTrue(checkpoint_uses_pi05_mode_head(configured))

    def test_preserves_other_fully_saved_modules(self) -> None:
        configured = configure_pi05_mode_head_peft_defaults(
            {"modules_to_save": ["state_proj"]}
        )

        self.assertEqual(configured["modules_to_save"], ["state_proj", "mode_head"])

    def test_mode_head_uses_contextualized_prefix_not_raw_embeddings(self) -> None:
        class FakeBackbone:
            def __init__(self) -> None:
                weight = torch.zeros(1, dtype=torch.bfloat16)
                q_proj = SimpleNamespace(weight=weight)
                attention = SimpleNamespace(q_proj=q_proj)
                layer = SimpleNamespace(self_attn=attention)
                language_model = SimpleNamespace(
                    layers=[layer], config=SimpleNamespace()
                )
                paligemma_model = SimpleNamespace(language_model=language_model)
                self.paligemma = SimpleNamespace(model=paligemma_model)
                self.called = False

            def forward(self, *, inputs_embeds, **_kwargs):
                self.called = True
                contextualized = torch.full_like(inputs_embeds[0], 2.0)
                return (contextualized, None), None

        class FakeModel:
            def __init__(self) -> None:
                self.paligemma_with_expert = FakeBackbone()
                self.mode_head = torch.nn.Linear(4, 3, bias=False)
                with torch.no_grad():
                    self.mode_head.weight.zero_()
                    self.mode_head.weight[:, :3] = torch.eye(3)

            def embed_prefix(self, *_args):
                return (
                    torch.zeros(1, 2, 4),
                    torch.ones(1, 2, dtype=torch.bool),
                    torch.zeros(1, 2, dtype=torch.bool),
                )

        model = FakeModel()
        logits = pi05_mode_head_logits(
            model,
            images=[],
            image_masks=[],
            tokens=torch.zeros(1, 1, dtype=torch.long),
            masks=torch.ones(1, 1, dtype=torch.bool),
        )

        self.assertTrue(model.paligemma_with_expert.called)
        torch.testing.assert_close(logits, torch.full((1, 3), 2.0))
        self.assertTrue(PI05_MODE_HEAD_PROTOCOL.endswith("v2"))

    def test_last_language_token_pooling_ignores_images_padding_and_state(self) -> None:
        contextualized = torch.arange(2 * 8 * 3, dtype=torch.float32).reshape(2, 8, 3)
        prefix_masks = torch.ones(2, 8, dtype=torch.bool)
        language_masks = torch.tensor([[True, True, False], [True, True, True]])

        pooled = pool_pi05_contextualized_prefix(
            contextualized,
            prefix_masks,
            language_masks,
            state_token_present=True,
            pooling=PI05_MODE_HEAD_POOLING_LAST_LANGUAGE_TOKEN,
        )

        torch.testing.assert_close(pooled[0], contextualized[0, 5])
        torch.testing.assert_close(pooled[1], contextualized[1, 6])

    def test_mode_head_pooling_protocol_round_trip(self) -> None:
        protocol = pi05_mode_head_protocol(PI05_MODE_HEAD_POOLING_LAST_LANGUAGE_TOKEN)

        self.assertTrue(protocol.endswith("v3"))
        self.assertEqual(
            pi05_mode_head_pooling_from_protocol(protocol),
            PI05_MODE_HEAD_POOLING_LAST_LANGUAGE_TOKEN,
        )


if __name__ == "__main__":
    unittest.main()
