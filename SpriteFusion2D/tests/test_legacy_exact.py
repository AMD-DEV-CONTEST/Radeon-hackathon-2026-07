from __future__ import annotations

import subprocess
import sys
import types
import unittest
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

from pixel_snapper_core import SnapConfig, snap_images

LEGACY_COMMIT = "58f4c8be28b1378ceb229b284ced7c4c4ef74abb"
REPOSITORY = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def legacy_module() -> types.ModuleType:
    source = subprocess.check_output(
        ["git", "show", f"{LEGACY_COMMIT}:pixel_snapper_node.py"],
        cwd=REPOSITORY,
        text=True,
        encoding="utf-8",
    )
    module = types.ModuleType("pixel_snapper_legacy_oracle")
    sys.modules[module.__name__] = module
    exec(
        compile(source, f"{LEGACY_COMMIT}:pixel_snapper_node.py", "exec"),
        module.__dict__,
    )
    return module


def random_image(height: int, width: int, seed: int) -> torch.Tensor:
    generator = torch.Generator().manual_seed(seed)
    return torch.randint(
        0,
        256,
        (height, width, 3),
        dtype=torch.uint8,
        generator=generator,
    )


def periodic_image(height: int = 48, width: int = 64) -> torch.Tensor:
    rows = torch.arange(height).view(-1, 1)
    columns = torch.arange(width).view(1, -1)
    cells = torch.div(rows, 4, rounding_mode="floor") + torch.div(
        columns, 4, rounding_mode="floor"
    )
    image = torch.zeros((height, width, 3), dtype=torch.uint8)
    image[cells.remainder(2) == 0] = torch.tensor([28, 42, 68], dtype=torch.uint8)
    image[cells.remainder(2) == 1] = torch.tensor([216, 152, 76], dtype=torch.uint8)
    return image


def reference_output(
    image: torch.Tensor,
    *,
    k_colors: int,
    pixel_size: float,
    iterations: int,
    seed: int,
    output_scale: int = 1,
) -> np.ndarray:
    legacy = legacy_module()
    config = legacy.Config(
        k_colors=k_colors,
        pixel_size_override=pixel_size,
        k_seed=seed,
        max_kmeans_iterations=iterations,
    )
    output = legacy.process_image_array(image.numpy(), config)
    return legacy.upscale_nearest(output, output_scale)


def exact_output(
    image: torch.Tensor,
    *,
    device: str,
    k_colors: int,
    pixel_size: float,
    iterations: int,
    seed: int,
    output_scale: int = 1,
) -> torch.Tensor:
    config = SnapConfig(
        algorithm="legacy_exact",
        k_colors=k_colors,
        pixel_size_override=pixel_size,
        k_seed=seed,
        max_kmeans_iterations=iterations,
        output_scale=output_scale,
    )
    source = image.to(torch.float32).div(255.0).unsqueeze(0)
    return snap_images(source, config, device=device)[0]


class LegacyExactTests(unittest.TestCase):
    def assert_matches_reference(
        self,
        image: torch.Tensor,
        *,
        device: str,
        k_colors: int,
        pixel_size: float,
        iterations: int,
        seed: int,
        output_scale: int = 1,
    ) -> None:
        expected = reference_output(
            image,
            k_colors=k_colors,
            pixel_size=pixel_size,
            iterations=iterations,
            seed=seed,
            output_scale=output_scale,
        )
        actual = exact_output(
            image,
            device=device,
            k_colors=k_colors,
            pixel_size=pixel_size,
            iterations=iterations,
            seed=seed,
            output_scale=output_scale,
        )
        actual_u8 = actual[0].mul(255).round().to(torch.uint8).cpu().numpy()
        np.testing.assert_array_equal(actual_u8, expected)
        self.assertEqual(actual.device.type, torch.device(device).type)

    def test_seeded_random_image_matches_legacy_commit_exactly(self) -> None:
        self.assert_matches_reference(
            random_image(36, 44, 1977),
            device="cpu",
            k_colors=9,
            pixel_size=4,
            iterations=7,
            seed=991,
        )

    def test_float32_public_input_conversion_matches_legacy_commit(self) -> None:
        generator = torch.Generator().manual_seed(6021)
        source = torch.rand((1, 37, 43, 3), generator=generator)
        legacy = legacy_module()
        legacy_rgb = legacy.tensor_to_numpy_batch(source)[0]
        legacy_config = legacy.Config(
            k_colors=8,
            pixel_size_override=4,
            k_seed=113,
            max_kmeans_iterations=6,
        )
        expected = legacy.process_image_array(legacy_rgb, legacy_config)

        actual = snap_images(
            source,
            SnapConfig(
                k_colors=8,
                pixel_size_override=4,
                k_seed=113,
                max_kmeans_iterations=6,
                algorithm="legacy_exact",
            ),
            device="cpu",
        )[0]
        actual_u8 = actual[0].mul(255).round().to(torch.uint8).numpy()

        np.testing.assert_array_equal(actual_u8, expected)

    def test_automatic_grid_matches_legacy_commit_exactly(self) -> None:
        self.assert_matches_reference(
            periodic_image(),
            device="cpu",
            k_colors=6,
            pixel_size=0,
            iterations=6,
            seed=42,
        )

    def test_nearest_scale_matches_legacy_commit_exactly(self) -> None:
        self.assert_matches_reference(
            random_image(32, 40, 81),
            device="cpu",
            k_colors=7,
            pixel_size=4,
            iterations=5,
            seed=19,
            output_scale=3,
        )

    @unittest.skipUnless(
        torch.cuda.is_available(), "requires an available PyTorch accelerator"
    )
    def test_accelerator_matches_legacy_commit_exactly(self) -> None:
        self.assert_matches_reference(
            random_image(48, 64, 2026),
            device="cuda",
            k_colors=12,
            pixel_size=4,
            iterations=8,
            seed=73,
        )


if __name__ == "__main__":
    unittest.main()
