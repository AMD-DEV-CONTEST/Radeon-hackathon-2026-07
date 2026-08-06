"""Camera observation adapter for a Genesis camera."""

from __future__ import annotations

from typing import Any

import numpy as np


class Camera:
    def __init__(self, camera: Any) -> None:
        self.camera = camera

    def observation(self) -> np.ndarray:
        """Return the RGB frame from Genesis' multi-output render call."""
        rgb, *_ = self.camera.render()
        if hasattr(rgb, "detach") and hasattr(rgb, "cpu"):
            rgb = rgb.detach().cpu()
        # Render backends may return a vertically flipped view with a negative
        # stride.  PyTorch cannot construct a tensor from that layout.
        return np.ascontiguousarray(np.asarray(rgb))
