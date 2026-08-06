from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.comfyui_bindings import (
    ComfyBindingError,
    FrozenComfyWorkflowBinder,
    canonical_sha256,
)


ROOT = Path(__file__).resolve().parents[1]


class FrozenComfyWorkflowBinderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binder = FrozenComfyWorkflowBinder(ROOT)

    def test_all_four_wrappers_have_frozen_validated_bindings(self) -> None:
        self.assertEqual(
            self.binder.workflow_ids,
            (
                "ace-step-1.5-text-to-audio",
                "ltx-2.3-text-to-video",
                "qwen-image-2512",
                "wan2.2-text-to-video",
            ),
        )

    def test_image_binding_changes_only_declared_creative_controls(self) -> None:
        bound = self.binder.bind(
            "qwen-image-2512",
            {
                "prompt": "Cinematic earned-media key visual with an unmistakable product proof moment",
                "seed": 42,
                "width": 2048,
                "height": 1152,
            },
        )
        self.assertEqual(bound.workflow["263:249"]["inputs"]["text"], bound.resolved_values["prompt"])
        self.assertEqual(bound.workflow["263:252"]["inputs"]["width"], 2048)
        self.assertEqual(bound.workflow["263:252"]["inputs"]["height"], 1152)
        self.assertEqual(bound.workflow["263:253"]["inputs"]["seed"], 42)
        self.assertEqual(
            bound.workflow["263:248"]["inputs"]["unet_name"],
            "qwen_image_2512_fp8_e4m3fn.safetensors",
        )
        self.assertEqual(bound.values_sha256, canonical_sha256(bound.resolved_values))
        self.assertEqual(bound.bound_workflow_sha256, canonical_sha256(bound.workflow))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "bound.json"
            bound.save(target)
            self.assertEqual(json.loads(target.read_text()), bound.workflow)

    def test_audio_binding_resolves_defaults_but_requires_creative_and_seed_inputs(self) -> None:
        bound = self.binder.bind(
            "ace-step-1.5-text-to-audio",
            {
                "tags": "cinematic alt-pop, intimate vocal, explosive final hook",
                "lyrics": "No budget, no borrowed fame; one proof changed the game.",
                "planner_seed": 11,
                "sampler_seed": 12,
            },
        )
        self.assertEqual(bound.workflow["21:110"]["inputs"]["value"], 30.0)
        self.assertEqual(bound.workflow["21:94"]["inputs"]["bpm"], 120)
        self.assertEqual(bound.workflow["21:94"]["inputs"]["language"], "en")
        self.assertEqual(bound.workflow["21:3"]["inputs"]["seed"], 12)
        with self.assertRaisesRegex(ComfyBindingError, "required binding missing"):
            self.binder.bind(
                "ace-step-1.5-text-to-audio",
                {"tags": "cinematic original music", "lyrics": "Proof"},
            )

    def test_unknown_model_overrides_and_invalid_ranges_fail_closed(self) -> None:
        base = {
            "prompt": "A cinematic public proof event staged for organic sharing and participation",
            "seed": 42,
        }
        with self.assertRaisesRegex(ComfyBindingError, "unknown binding"):
            self.binder.bind(
                "qwen-image-2512",
                {**base, "unet_name": "untrusted.safetensors"},
            )
        with self.assertRaisesRegex(ComfyBindingError, "must satisfy"):
            self.binder.bind("qwen-image-2512", {**base, "width": 1025})
        with self.assertRaisesRegex(ComfyBindingError, "must be an integer"):
            self.binder.bind("qwen-image-2512", {**base, "seed": True})

    def test_wan_frame_shape_rule_is_explicit(self) -> None:
        values = {
            "prompt": "A continuous cinematic product reveal with stable identity and physical motion",
            "seed_high_noise": 1,
            "seed_low_noise": 2,
            "length_frames": 81,
        }
        self.binder.bind("wan2.2-text-to-video", values)
        with self.assertRaisesRegex(ComfyBindingError, "must satisfy"):
            self.binder.bind(
                "wan2.2-text-to-video", {**values, "length_frames": 80}
            )


if __name__ == "__main__":
    unittest.main()
