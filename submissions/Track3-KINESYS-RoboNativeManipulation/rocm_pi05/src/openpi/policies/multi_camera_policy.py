"""Generic, camera-count-agnostic policy inputs/outputs.

Unlike the per-robot ``LiberoInputs`` / ``DroidInputs`` / ``AlohaInputs`` classes (which hardcode a
fixed 3-key image dict), ``MultiCameraInputs`` builds the model-facing ``image`` / ``image_mask``
dicts from an explicit, ordered ``camera_names`` tuple. Any number of cameras (1-8+) and any
free-form names are supported. Camera identity is dict-insertion order only (there is no learned
per-camera parameter), so the SAME ``camera_names`` order must be used at training and inference.
"""

import dataclasses

import einops
import numpy as np

from openpi import transforms
from openpi.models import model as _model


def make_multi_camera_example(camera_names: tuple[str, ...]) -> dict:
    """Random inference-time example. The client must send an ``images`` dict keyed by camera name."""
    return {
        "images": {name: np.random.randint(256, size=(224, 224, 3), dtype=np.uint8) for name in camera_names},
        "state": np.random.rand(8),
        "prompt": "do something",
    }


def _parse_image(image) -> np.ndarray:
    image = np.asarray(image)
    if np.issubdtype(image.dtype, np.floating):
        image = (255 * image).astype(np.uint8)
    if image.shape[0] == 3:
        image = einops.rearrange(image, "c h w -> h w c")
    return image


@dataclasses.dataclass(frozen=True)
class MultiCameraInputs(transforms.DataTransformFn):
    """Camera-count-agnostic, free-named inputs.

    Expects ``data["images"]`` to be a ``dict[name -> image]`` (produced by the repack at train time
    and supplied directly by the inference client). Builds the model-facing ``image`` / ``image_mask``
    dicts in the EXACT order of ``camera_names``. A declared-but-missing camera is zero-padded with
    ``image_mask=False`` (pi0/pi05), matching the existing per-policy padding convention.
    """

    camera_names: tuple[str, ...]
    model_type: _model.ModelType

    def __call__(self, data: dict) -> dict:
        in_images = data["images"]
        images: dict[str, np.ndarray] = {}
        image_masks: dict[str, np.bool_] = {}
        ref = None
        for name in self.camera_names:
            if name in in_images:
                img = _parse_image(in_images[name])
                images[name] = img
                image_masks[name] = np.True_
                if ref is None:
                    ref = img
            else:
                # Declared but missing camera -> zero-pad + mask off.
                if ref is None:
                    ref = _parse_image(next(iter(in_images.values())))
                images[name] = np.zeros_like(ref)
                image_masks[name] = np.True_ if self.model_type == _model.ModelType.PI0_FAST else np.False_

        inputs: dict = {"image": images, "image_mask": image_masks, "state": np.asarray(data["state"])}
        if "actions" in data:
            inputs["actions"] = np.asarray(data["actions"])
        if "prompt" in data:
            inputs["prompt"] = data["prompt"]
        return inputs


@dataclasses.dataclass(frozen=True)
class MultiCameraOutputs(transforms.DataTransformFn):
    """Slices model actions back to this robot's action dim (used at inference only)."""

    action_dim: int

    def __call__(self, data: dict) -> dict:
        return {"actions": np.asarray(data["actions"])[..., : self.action_dim]}
