"""
Module 1: Camera Wrapper
Genesis camera sensor interface.
"""
import numpy as np
from typing import Tuple


class CameraWrapper:
    def __init__(self, camera_entity):
        self.camera = camera_entity
        self.last_image = None

    def render(self) -> np.ndarray:
        result = self.camera.render()
        img = result[0]
        self.last_image = img
        return img

    def get_shape(self) -> Tuple[int, int, int]:
        img = self.render()
        return img.shape

    def render_and_save(self, path: str) -> np.ndarray:
        from PIL import Image
        img = self.render()
        Image.fromarray(img).save(path)
        return img
