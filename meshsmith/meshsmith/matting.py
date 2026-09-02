"""Background removal ahead of shape generation. Hunyuan3D expects a clean
RGBA subject; u2net via rembg (ONNX, CPU) is small, fast, and vendor-neutral.
"""
from __future__ import annotations

from PIL import Image


class Matting:
    def __init__(self):
        self._session = None

    def load(self):
        if self._session is None:
            from rembg import new_session

            self._session = new_session("u2net")

    def cut_out(self, image: Image.Image) -> Image.Image:
        """Return RGBA with background removed. If the image already has real
        transparency, trust it and skip the model."""
        img = image.convert("RGBA")
        alpha_min = img.split()[-1].getextrema()[0]
        if alpha_min < 255:
            return img
        self.load()
        from rembg import remove

        return remove(img, session=self._session).convert("RGBA")
