"""ComfyUI adapter for the ROCm-aware Pixel Snapper core."""

from __future__ import annotations

import torch

from .pixel_snapper_core import SnapConfig, snap_images


class PixelSnapperNode:
    """Snap an image batch while preserving each frame's output dimensions."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "IMAGE tensor batch. Output remains on the selected "
                            "PyTorch device, including AMD ROCm/HIP."
                        )
                    },
                ),
                "k_colors": (
                    "INT",
                    {
                        "default": 16,
                        "min": 1,
                        "max": 512,
                        "tooltip": "Palette size for K-Means quantization",
                    },
                ),
                "k_seed": (
                    "INT",
                    {
                        "default": 42,
                        "min": 0,
                        "max": 2**31 - 1,
                        "tooltip": "Random seed for K-Means++ initialization",
                    },
                ),
            },
            "optional": {
                "algorithm": (
                    ["optimized", "legacy_exact"],
                    {
                        "default": "optimized",
                        "tooltip": (
                            "optimized uses the redesigned parallel grid; legacy_exact "
                            "preserves the former NumPy palette, walker, dimensions, "
                            "and pixels while accelerating heavy stages on the GPU"
                        ),
                    },
                ),
                "output_scale": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 16,
                        "tooltip": (
                            "Integer nearest-neighbour scale applied after grid snapping"
                        ),
                    },
                ),
                "max_kmeans_iterations": (
                    "INT",
                    {
                        "default": 15,
                        "min": 1,
                        "max": 200,
                        "tooltip": "Maximum K-Means refinement iterations",
                    },
                ),
                "peak_threshold_multiplier": (
                    "FLOAT",
                    {
                        "default": 0.2,
                        "min": 0.0,
                        "max": 5.0,
                        "step": 0.01,
                        "tooltip": "Fraction of the strongest gradient retained as an edge",
                    },
                ),
                "peak_distance_filter": (
                    "INT",
                    {
                        "default": 4,
                        "min": 1,
                        "max": 512,
                        "tooltip": "Radius used for parallel non-maximum suppression",
                    },
                ),
                "walker_search_window_ratio": (
                    "FLOAT",
                    {
                        "default": 0.35,
                        "min": 0.01,
                        "max": 5.0,
                        "step": 0.01,
                        "tooltip": "Cut search radius relative to the estimated cell width",
                    },
                ),
                "walker_min_search_window": (
                    "FLOAT",
                    {
                        "default": 2.0,
                        "min": 0.1,
                        "max": 32.0,
                        "step": 0.1,
                        "tooltip": "Minimum cut search radius in source pixels",
                    },
                ),
                "walker_strength_threshold": (
                    "FLOAT",
                    {
                        "default": 0.5,
                        "min": 0.0,
                        "max": 5.0,
                        "step": 0.01,
                        "tooltip": (
                            "Edge strength relative to the profile mean before uniform fallback"
                        ),
                    },
                ),
                "min_cuts_per_axis": (
                    "INT",
                    {
                        "default": 4,
                        "min": 2,
                        "max": 512,
                        "tooltip": "Minimum cut count per axis, including endpoints",
                    },
                ),
                "fallback_target_segments": (
                    "INT",
                    {
                        "default": 64,
                        "min": 1,
                        "max": 2048,
                        "tooltip": "Grid cell target when no stable periodic edge is found",
                    },
                ),
                "max_step_ratio": (
                    "FLOAT",
                    {
                        "default": 1.8,
                        "min": 1.0,
                        "max": 5.0,
                        "step": 0.05,
                        "tooltip": "Maximum X/Y step ratio before using the smaller step",
                    },
                ),
                "pixel_size": (
                    "FLOAT",
                    {
                        "default": 0.0,
                        "min": 0.0,
                        "max": 10000.0,
                        "step": 0.1,
                        "tooltip": "Source pixel size override; zero enables auto-detection",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "snap"
    CATEGORY = "image/transform"

    def snap(
        self,
        image: torch.Tensor,
        k_colors: int,
        k_seed: int,
        algorithm: str = "optimized",
        output_scale: int = 1,
        max_kmeans_iterations: int = 15,
        peak_threshold_multiplier: float = 0.2,
        peak_distance_filter: int = 4,
        walker_search_window_ratio: float = 0.35,
        walker_min_search_window: float = 2.0,
        walker_strength_threshold: float = 0.5,
        min_cuts_per_axis: int = 4,
        fallback_target_segments: int = 64,
        max_step_ratio: float = 1.8,
        pixel_size: float = 0.0,
    ):
        config = SnapConfig(
            algorithm=algorithm,
            k_colors=k_colors,
            pixel_size_override=pixel_size,
            k_seed=k_seed,
            max_kmeans_iterations=max_kmeans_iterations,
            peak_threshold_multiplier=peak_threshold_multiplier,
            peak_distance_filter=peak_distance_filter,
            walker_search_window_ratio=walker_search_window_ratio,
            walker_min_search_window=walker_min_search_window,
            walker_strength_threshold=walker_strength_threshold,
            min_cuts_per_axis=min_cuts_per_axis,
            fallback_target_segments=fallback_target_segments,
            max_step_ratio=max_step_ratio,
            output_scale=output_scale,
        )
        return (snap_images(image, config),)


NODE_CLASS_MAPPINGS = {"PixelSnapper": PixelSnapperNode}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PixelSnapper": "Sprite Fusion Pixel Snapper (ROCm / Exact)"
}

__all__ = [
    "PixelSnapperNode",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
