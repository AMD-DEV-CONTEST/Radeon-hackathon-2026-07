from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MouthFrame:
    sequence: int
    received_at_ms: int
    image: np.ndarray
    debug_image: np.ndarray | None = None
    debug_mouth_box: object | None = None
    debug_landmarks: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if self.image.shape != (96, 96):
            raise ValueError("mouth frame image must have shape (96, 96)")
        if self.image.dtype != np.uint8:
            raise ValueError("mouth frame image must use uint8")
        if self.debug_image is not None:
            if self.debug_image.ndim != 3 or self.debug_image.shape[2] != 3:
                raise ValueError("debug image must have RGB shape (height, width, 3)")
            if self.debug_image.dtype != np.uint8:
                raise ValueError("debug image must use uint8")
