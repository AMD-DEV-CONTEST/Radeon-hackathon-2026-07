from __future__ import annotations

import unittest

import torch

from pixel_snapper_core import SnapConfig, snap_images


def four_color_grid(size: int = 32) -> torch.Tensor:
    image = torch.zeros((1, size, size, 3), dtype=torch.float32)
    half = size // 2
    image[:, :half, :half, 0] = 1.0
    image[:, :half, half:, 1] = 1.0
    image[:, half:, :half, 2] = 1.0
    image[:, half:, half:] = 1.0
    return image


class PixelSnapperCoreTests(unittest.TestCase):
    def test_algorithm_field_preserves_existing_positional_config_order(self) -> None:
        config = SnapConfig(7, 3.5, 99)

        self.assertEqual(config.k_colors, 7)
        self.assertEqual(config.pixel_size_override, 3.5)
        self.assertEqual(config.k_seed, 99)
        self.assertEqual(config.algorithm, "optimized")

    def test_fixed_grid_shape_palette_and_device(self) -> None:
        output = snap_images(
            four_color_grid(),
            SnapConfig(k_colors=4, pixel_size_override=8),
            device="cpu",
        )[0]

        self.assertEqual(output.shape, (1, 4, 4, 3))
        self.assertEqual(output.device.type, "cpu")
        colors = torch.unique(
            output.mul(255).round().to(torch.uint8).reshape(-1, 3), dim=0
        )
        self.assertEqual(colors.shape[0], 4)

    def test_channel_first_and_channel_last_are_equivalent(self) -> None:
        image = four_color_grid()
        config = SnapConfig(k_colors=4, pixel_size_override=4)

        channel_last = snap_images(image, config, device="cpu")[0]
        channel_first = snap_images(image.movedim(-1, 1), config, device="cpu")[0]

        torch.testing.assert_close(channel_first, channel_last, rtol=0, atol=0)

    def test_seeded_quantization_is_deterministic(self) -> None:
        generator = torch.Generator().manual_seed(73)
        image = torch.rand((1, 48, 64, 3), generator=generator)
        config = SnapConfig(
            k_colors=12,
            k_seed=9182,
            pixel_size_override=4,
            max_kmeans_iterations=8,
        )

        first = snap_images(image, config, device="cpu")[0]
        second = snap_images(image, config, device="cpu")[0]

        torch.testing.assert_close(first, second, rtol=0, atol=0)

    def test_processing_does_not_mutate_the_input_tensor(self) -> None:
        image = four_color_grid()
        original = image.clone()

        snap_images(
            image,
            SnapConfig(k_colors=4, pixel_size_override=4),
            device="cpu",
        )

        torch.testing.assert_close(image, original, rtol=0, atol=0)

    def test_one_x_preserves_dimensions_while_limiting_palette(self) -> None:
        generator = torch.Generator().manual_seed(127)
        image = torch.rand((1, 24, 40, 3), generator=generator)
        output = snap_images(
            image,
            SnapConfig(k_colors=7, pixel_size_override=1),
            device="cpu",
        )[0]

        self.assertEqual(output.shape, (1, 24, 40, 3))
        colors = torch.unique(
            output.mul(255).round().to(torch.uint8).reshape(-1, 3), dim=0
        )
        self.assertLessEqual(colors.shape[0], 7)

    def test_batch_returns_independent_variable_size_frames(self) -> None:
        first = four_color_grid()[0]
        second = first.flip(0)
        outputs = snap_images(
            torch.stack((first, second)),
            SnapConfig(k_colors=4, pixel_size_override=8),
            device="cpu",
        )

        self.assertEqual(len(outputs), 2)
        self.assertEqual(outputs[0].shape, (1, 4, 4, 3))
        self.assertFalse(torch.equal(outputs[0], outputs[1]))

    def test_integer_output_scale_uses_nearest_neighbour(self) -> None:
        output = snap_images(
            four_color_grid(),
            SnapConfig(k_colors=4, pixel_size_override=8, output_scale=3),
            device="cpu",
        )[0]

        self.assertEqual(output.shape, (1, 12, 12, 3))
        reduced = output[:, ::3, ::3]
        reference = snap_images(
            four_color_grid(),
            SnapConfig(k_colors=4, pixel_size_override=8),
            device="cpu",
        )[0]
        torch.testing.assert_close(reduced, reference, rtol=0, atol=0)

    @unittest.skipUnless(
        torch.cuda.is_available(), "requires an available PyTorch accelerator"
    )
    def test_accelerator_matches_cpu_for_an_exact_palette(self) -> None:
        config = SnapConfig(k_colors=4, pixel_size_override=8)
        cpu_output = snap_images(four_color_grid(), config, device="cpu")[0]
        accelerator_input = four_color_grid().to("cuda")
        accelerator_output = snap_images(accelerator_input, config)[0]

        self.assertEqual(accelerator_output.device.type, "cuda")
        torch.testing.assert_close(accelerator_output.cpu(), cpu_output, rtol=0, atol=0)

    def test_rgba_input_ignores_alpha_without_mutating_layout(self) -> None:
        rgb = four_color_grid()
        alpha = torch.rand((1, 32, 32, 1), generator=torch.Generator().manual_seed(8))
        rgba = torch.cat((rgb, alpha), dim=-1)
        config = SnapConfig(k_colors=4, pixel_size_override=8)

        rgb_output = snap_images(rgb, config, device="cpu")[0]
        rgba_output = snap_images(rgba, config, device="cpu")[0]

        torch.testing.assert_close(rgba_output, rgb_output, rtol=0, atol=0)
        self.assertEqual(rgba.shape, (1, 32, 32, 4))

    def test_invalid_shape_is_rejected_at_the_public_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "shape"):
            snap_images(torch.zeros((2, 2)), device="cpu")

    @unittest.skipUnless(
        torch.cuda.is_available() and torch.version.hip is not None,
        "requires a PyTorch ROCm runtime and an available AMD GPU",
    )
    def test_rocm_keeps_outputs_on_hip_device(self) -> None:
        output = snap_images(
            four_color_grid(128),
            SnapConfig(k_colors=4, pixel_size_override=8),
            device="cuda",
        )[0]

        self.assertEqual(output.device.type, "cuda")
        self.assertIsNotNone(torch.version.hip)


if __name__ == "__main__":
    unittest.main()
