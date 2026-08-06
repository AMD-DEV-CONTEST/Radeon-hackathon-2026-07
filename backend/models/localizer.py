"""Localization and explainability using RAD-DINO attention maps.

Produces visual evidence heatmaps for each predicted finding by extracting the
CLS-to-patch attention from the last layer of RAD-DINO. This is well-suited to
the DINOv2 architecture because the class token is trained to aggregate
information from all patch tokens.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image


@dataclass
class LocalizationResult:
    label: str
    mask: np.ndarray  # uint8 grayscale, same size as input image
    heatmap: Optional[np.ndarray] = None  # uint8 grayscale or None
    bbox: Optional[list[int]] = None


class XRayLocalizer:
    def __init__(self, device: str = "cpu"):
        self.device = device

    def localize(
        self,
        image: Image.Image,
        classifier_model,
        findings: list,
        evidence_type: str = "attention",
    ) -> list[LocalizationResult]:
        """Generate localization heatmaps for predicted findings.

        classifier_model must expose get_attention_heatmap(image, label),
        get_gradcam_heatmap(image, label), and/or
        get_gradcam_heatmaps_for_findings(image, findings) returning uint8
        heatmaps aligned with the image.

        evidence_type: "attention" or "gradcam"
        """
        relevant_findings = [f for f in findings if f.confidence >= 0.05]

        if evidence_type == "gradcam" and hasattr(
            classifier_model, "get_gradcam_heatmaps_for_findings"
        ):
            # Use the efficient batch implementation: one forward pass for all classes.
            try:
                heatmap_pairs = classifier_model.get_gradcam_heatmaps_for_findings(
                    image, relevant_findings
                )
                return [
                    LocalizationResult(
                        label=label,
                        mask=self._heatmap_to_mask(heatmap),
                        heatmap=heatmap,
                        bbox=None,
                    )
                    for label, heatmap in heatmap_pairs
                ]
            except Exception:
                # Fall through to per-finding Grad-CAM.
                pass

        heatmap_fn = getattr(
            classifier_model,
            "get_gradcam_heatmap" if evidence_type == "gradcam" else "get_attention_heatmap",
            lambda image, label: np.zeros((image.size[1], image.size[0]), dtype=np.uint8),
        )

        results = []
        for finding in relevant_findings:
            try:
                heatmap = heatmap_fn(image, finding.label)
            except Exception:
                continue
            mask = self._heatmap_to_mask(heatmap)
            results.append(
                LocalizationResult(
                    label=finding.label,
                    mask=mask,
                    heatmap=heatmap,
                    bbox=None,
                )
            )
        return results

    def _heatmap_to_mask(self, heatmap: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Convert a soft heatmap to a binary mask."""
        mask = (heatmap.astype(np.float32) / 255.0) >= threshold
        return (mask * 255).astype(np.uint8)


def combine_masks(image_size: tuple[int, int], masks: list[LocalizationResult]) -> np.ndarray:
    """Combine individual label masks into an RGBA overlay keyed by label."""
    w, h = image_size
    combined = np.zeros((h, w, 4), dtype=np.uint8)  # RGBA
    colors = {
        "Cardiomegaly": (255, 80, 80, 120),
        "Pleural effusion": (80, 120, 255, 120),
        "Pneumonia": (255, 200, 80, 120),
        "Atelectasis": (120, 255, 120, 120),
        "Pneumothorax": (200, 80, 255, 120),
        "Consolidation": (255, 150, 150, 120),
        "Pulmonary edema": (80, 200, 255, 120),
        "No finding": (200, 200, 200, 120),
    }
    for m in masks:
        color = colors.get(m.label, (200, 200, 200, 120))
        alpha = m.mask.astype(np.float32) / 255.0
        for c in range(4):
            channel_value = color[c]
            combined[..., c] = np.clip(
                combined[..., c].astype(np.float32) + alpha * channel_value,
                0,
                255,
            ).astype(np.uint8)
    return combined
