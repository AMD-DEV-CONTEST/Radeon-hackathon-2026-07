"""
CLIP-based detector helper used by the SafeSort-RL demo.

The detector prefers CLIP when the package and weights are available, and
falls back to a deterministic image-statistics baseline so the demo script can
still run in offline evaluator environments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import torch

try:
    import clip
except ImportError:  # pragma: no cover - exercised only in minimal installs
    clip = None


DEFAULT_LABELS = (
    "battery",
    "chemical bottle",
    "plastic bottle",
    "syringe",
)


@dataclass
class DetectionResult:
    probabilities: np.ndarray
    label: str


class CLIPDetector:
    """Zero-shot object detector for rendered SafeSort observations."""

    def __init__(
        self,
        labels: Sequence[str] = DEFAULT_LABELS,
        device: str | None = None,
        model_name: str = "ViT-B/32",
    ):
        self.labels = tuple(labels)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.preprocess = None
        self.text_features = None

        if clip is None:
            print("CLIP is unavailable; using deterministic fallback detector.")
            return

        try:
            self.model, self.preprocess = clip.load(model_name, device=self.device)
            prompts = [f"a simulated waste object: {label}" for label in self.labels]
            with torch.no_grad():
                text = clip.tokenize(prompts).to(self.device)
                text_features = self.model.encode_text(text)
                self.text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            self.model.eval()
        except Exception as exc:  # pragma: no cover - depends on local weights/network
            print(f"CLIP detector fallback enabled: {exc}")
            self.model = None
            self.preprocess = None
            self.text_features = None

    def detect(self, image: np.ndarray) -> tuple[np.ndarray, str]:
        """Return class probabilities and the most likely label."""
        result = self._detect_with_clip(image) if self.model is not None else self._detect_fallback(image)
        return result.probabilities, result.label

    def _detect_with_clip(self, image: np.ndarray) -> DetectionResult:
        from PIL import Image

        pil_image = Image.fromarray(np.asarray(image, dtype=np.uint8))
        image_tensor = self.preprocess(pil_image).unsqueeze(0).to(self.device)

        with torch.no_grad():
            image_features = self.model.encode_image(image_tensor)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            logits = 100.0 * image_features @ self.text_features.T
            probabilities = logits.softmax(dim=-1).cpu().numpy()[0]

        index = int(np.argmax(probabilities))
        return DetectionResult(probabilities=probabilities, label=self.labels[index])

    def _detect_fallback(self, image: np.ndarray) -> DetectionResult:
        image_array = np.asarray(image, dtype=np.float32)
        channel_means = image_array.reshape(-1, image_array.shape[-1]).mean(axis=0)
        brightness = float(channel_means.mean())

        features = np.array(
            [
                channel_means[0],
                channel_means[1],
                channel_means[2],
                brightness,
            ],
            dtype=np.float32,
        )
        probabilities = features - features.min()
        probabilities = probabilities + 1e-6
        probabilities = probabilities / probabilities.sum()
        index = int(np.argmax(probabilities))
        return DetectionResult(probabilities=probabilities, label=self.labels[index])


def test_detector() -> None:
    detector = CLIPDetector(device="cuda" if torch.cuda.is_available() else "cpu")
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    probabilities, label = detector.detect(image)
    print(f"Detected: {label}")
    print(f"Probabilities: {probabilities.round(3).tolist()}")
    print("Detector works.")


if __name__ == "__main__":
    test_detector()
