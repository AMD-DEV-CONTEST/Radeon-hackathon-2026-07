from __future__ import annotations

import gc
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class SemanticScore:
    passed: bool
    model_ref: str
    positive_probability: float
    strongest_negative_probability: float
    margin: float
    labels: tuple[str, ...]
    probabilities: tuple[float, ...]
    limitations: tuple[str, ...]


class SemanticScorer(Protocol):
    def score(self, *, image_path: str, product_name: str) -> SemanticScore: ...


class HuggingFaceSigLIP2Scorer:
    """Lazy, local SigLIP2 image-text scorer for a fifth visual-semantic gate."""

    def __init__(
        self,
        model_id: str = "google/siglip2-base-patch16-224",
        *,
        revision: str | None = None,
        local_files_only: bool = False,
        device: str = "cuda",
        minimum_positive_probability: float = 0.34,
        minimum_margin: float = 0.05,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.local_files_only = local_files_only
        self.device = device
        self.minimum_positive_probability = minimum_positive_probability
        self.minimum_margin = minimum_margin
        self._model = None
        self._processor = None

    @property
    def model_ref(self) -> str:
        return (
            f"{self.model_id}@{self.revision}"
            if self.revision is not None
            else self.model_id
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModel, AutoProcessor

        self._processor = AutoProcessor.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
        )
        self._model = AutoModel.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
        ).to(self.device)
        self._model.eval()

    def load(self) -> None:
        self._load()

    def score(self, *, image_path: str, product_name: str) -> SemanticScore:
        import torch

        self._load()
        assert self._model is not None and self._processor is not None
        labels = (
            f"a clean campaign advertisement with one clear {product_name} product",
            f"an advertisement with duplicated {product_name} products",
            f"an advertisement with a distorted or obscured {product_name} product",
            f"an empty advertisement without the {product_name} product",
        )
        with Image.open(Path(image_path)) as source_image:
            image = source_image.convert("RGB")
        inputs = self._processor(
            text=list(labels),
            images=image,
            padding="max_length",
            max_length=64,
            return_tensors="pt",
        ).to(self.device)
        with torch.inference_mode():
            logits = self._model(**inputs).logits_per_image[0]
            probabilities_tensor = torch.softmax(logits.float(), dim=-1)
        probabilities = tuple(float(value) for value in probabilities_tensor.cpu())
        if not all(math.isfinite(value) for value in probabilities):
            raise RuntimeError("SigLIP2 returned non-finite probabilities")
        positive = probabilities[0]
        strongest_negative = max(probabilities[1:])
        margin = positive - strongest_negative
        passed = (
            positive >= self.minimum_positive_probability
            and margin >= self.minimum_margin
        )
        return SemanticScore(
            passed=passed,
            model_ref=self.model_ref,
            positive_probability=round(positive, 6),
            strongest_negative_probability=round(strongest_negative, 6),
            margin=round(margin, 6),
            labels=labels,
            probabilities=tuple(round(value, 6) for value in probabilities),
            limitations=(
                "Zero-shot relative score; not a calibrated human preference metric.",
                "Thresholds must be validated on the frozen Radeon visual set.",
                "Mechanical source hashes and protected pixels remain authoritative.",
            ),
        )

    def release(self) -> None:
        self._model = None
        self._processor = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
