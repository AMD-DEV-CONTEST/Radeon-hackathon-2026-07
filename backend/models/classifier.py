"""Chest X-ray finding classifier.

Supports two backends:
1. TorchXRayVision (default): uses pretrained DenseNet models trained on
   CheXpert/NIH/etc. This gives real predictions without training.
2. RAD-DINO + custom head: loads a RAD-DINO encoder plus a linear head
   checkpoint via CLASSIFIER_HEAD. This path is kept intact so a real
   RAD-DINO-based head can be swapped in later.

Environment variables:
  CLASSIFIER_HEAD: Path or HF repo id for the RAD-DINO classification head.
                   If unset, TorchXRayVision is used.
  RADDINO_MODEL: HuggingFace model id for the RAD-DINO vision encoder
                 (default: microsoft/rad-dino).
"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

from models.vision_encoder import RADDINOVisionEncoder

# Grad-CAM is only meaningful for convolutional classifiers.
# Imported lazily inside the TorchXRayVision backend to keep the dependency soft.
try:
    from models.gradcam import XRayGradCAM
except Exception:
    XRayGradCAM = None  # type: ignore

# Canonical findings used by the rest of the app.
FINDINGS = [
    "Cardiomegaly",
    "Pleural effusion",
    "Pneumonia",
    "Atelectasis",
    "Consolidation",
    "Pulmonary edema",
    "Pneumothorax",
    "No finding",
]


@dataclass
class FindingPrediction:
    label: str
    confidence: float
    region: Optional[list[int]] = None


class RADDINOHead(nn.Module):
    """Linear head on top of RAD-DINO [CLS] embedding."""

    def __init__(self, hidden_size: int, num_classes: int, dropout: float = 0.1):
        super().__init__()
        self.fc = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(hidden_size, num_classes),
        )

    def forward(self, cls_embedding: torch.Tensor) -> torch.Tensor:
        return self.fc(cls_embedding)


class ClassifierBackend(ABC):
    """Abstract backend for classification + attention-based localization."""

    findings_list: list[str]

    @abstractmethod
    def predict(self, image: Image.Image) -> list[FindingPrediction]:
        ...

    def get_attention_heatmap(self, image: Image.Image, label: str) -> np.ndarray:
        """Fallback: return an empty heatmap if the backend cannot localize."""
        h, w = image.size[1], image.size[0]
        return np.zeros((h, w), dtype=np.uint8)

    def get_gradcam_heatmap(self, image: Image.Image, label: str) -> np.ndarray:
        """Fallback: return an empty heatmap if the backend does not support Grad-CAM."""
        h, w = image.size[1], image.size[0]
        return np.zeros((h, w), dtype=np.uint8)

    def get_gradcam_heatmaps_for_findings(
        self, image: Image.Image, findings: list
    ) -> list[tuple[str, np.ndarray]]:
        """Fallback: compute Grad-CAM one-by-one for each finding."""
        results: list[tuple[str, np.ndarray]] = []
        for finding in findings:
            if finding.confidence < 0.05:
                continue
            results.append((finding.label, self.get_gradcam_heatmap(image, finding.label)))
        return results


def _attention_heatmap_from_raddino(
    encoder: RADDINOVisionEncoder, image: Image.Image, label: str
) -> np.ndarray:
    """Compute CLS-to-patch attention heatmap from a RAD-DINO encoder."""
    import torch.nn.functional as F

    with torch.no_grad():
        _, _, attention = encoder.extract_features_with_attention(image)
        last_attention = attention[0]  # [heads, N_tokens, N_tokens]
        cls_to_patches = last_attention[:, 0, 1:]  # [heads, num_patches]
        attention_map = cls_to_patches.mean(dim=0)  # [num_patches]

        num_patches = attention_map.shape[0]
        grid_size = int(num_patches ** 0.5)
        if grid_size * grid_size != num_patches:
            grid_size = 1
        attention_map = attention_map.reshape(1, 1, grid_size, grid_size)
        h, w = image.size[1], image.size[0]
        attention_map = F.interpolate(
            attention_map,
            size=(h, w),
            mode="bilinear",
            align_corners=False,
        )
        attention_map = attention_map.squeeze().cpu().numpy()
        attention_map = (attention_map - attention_map.min()) / (
            attention_map.max() - attention_map.min() + 1e-8
        )
        return (attention_map * 255).astype(np.uint8)


class RADDINOClassifierBackend(ClassifierBackend):
    """RAD-DINO encoder + custom linear head."""

    findings_list = FINDINGS

    def __init__(self, device: str = "cpu", head_path: Optional[str] = None):
        self.device = device
        self.encoder = RADDINOVisionEncoder(device=device)
        self.head = RADDINOHead(int(self.encoder.hidden_size), len(FINDINGS)).to(device)
        self.head.eval()
        self._load_head(head_path or os.environ.get("CLASSIFIER_HEAD"))

    def _load_head(self, head_path: Optional[str]) -> None:
        if head_path and os.path.isdir(head_path):
            try:
                state = torch.load(
                    os.path.join(head_path, "pytorch_model.bin"),
                    map_location=self.device,
                    weights_only=True,
                )
                self.head.load_state_dict(state, strict=False)
                print(f"Loaded classifier head from {head_path}")
                return
            except Exception:
                pass

        if head_path and os.path.isfile(head_path):
            try:
                state = torch.load(head_path, map_location=self.device, weights_only=True)
                if isinstance(state, dict) and "head" in state:
                    state = state["head"]
                self.head.load_state_dict(state, strict=False)
                print(f"Loaded classifier head from {head_path}")
                return
            except Exception:
                pass

        raise RuntimeError(
            "No pretrained classification head is available.\n"
            "A RAD-DINO encoder is loaded, but a head checkpoint is required "
            "to produce real finding predictions.\n\n"
            "Options:\n"
            "  1. Set CLASSIFIER_HEAD to a local .pt/.bin checkpoint or directory.\n"
            "  2. Fine-tune a head on a labelled chest X-ray dataset and save it.\n"
            "  3. Use TorchXRayVision (default) by unsetting CLASSIFIER_HEAD.\n\n"
            "To create a random head for testing only, run:\n"
            "  python scripts/init_classifier_head.py --output classifier_head.pt"
        )

    def predict(self, image: Image.Image) -> list[FindingPrediction]:
        with torch.no_grad():
            cls_embedding, _ = self.encoder.extract_features(image)
            logits = self.head(cls_embedding)
            probs = torch.sigmoid(logits).cpu().numpy().flatten()
        return self._probs_to_findings(probs.tolist())

    def get_attention_heatmap(self, image: Image.Image, label: str) -> np.ndarray:
        return _attention_heatmap_from_raddino(self.encoder, image, label)

    def get_gradcam_heatmap(self, image: Image.Image, label: str) -> np.ndarray:
        # RAD-DINO head is linear on [CLS]; Grad-CAM is not applicable.
        # Fall back to attention-based explanation.
        return self.get_attention_heatmap(image, label)

    def _probs_to_findings(self, probs: list[float]) -> list[FindingPrediction]:
        findings = [
            FindingPrediction(label=label, confidence=float(p), region=None)
            for label, p in zip(FINDINGS, probs)
        ]
        findings.sort(key=lambda x: x.confidence, reverse=True)
        return findings


class TorchXRayVisionClassifierBackend(ClassifierBackend):
    """Pretrained DenseNet classifier from torchxrayvision.

    Still loads RAD-DINO so the attention-based localizer remains
    RAD-DINO-driven for visual grounding.
    """

    findings_list = FINDINGS

    def __init__(self, device: str = "cpu", model_name: str = "densenet121-res224-chex"):
        self.device = device
        self.model_name = model_name
        self.encoder = RADDINOVisionEncoder(device=device)
        self.model = self._load_model(model_name)
        self.model.eval()
        self.model.to(device)
        self._label_map = self._build_label_map(self.model.pathologies)
        self._gradcam = None

    @property
    def gradcam(self):
        if self._gradcam is None and XRayGradCAM is not None:
            self._gradcam = XRayGradCAM(self.model, device=self.device)
        return self._gradcam

    def _load_model(self, model_name: str):
        import torchxrayvision as xrv

        try:
            model = xrv.models.DenseNet(weights=model_name)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load TorchXRayVision model '{model_name}'. "
                f"Ensure torchxrayvision is installed. Original error: {exc}"
            ) from exc
        return model

    def _build_label_map(self, pathologies: list[str]) -> dict[str, int]:
        """Map TorchXRayVision pathology names to canonical findings."""
        canonical_to_txv = {
            "Cardiomegaly": ["Cardiomegaly"],
            "Pleural effusion": ["Effusion", "Pleural Effusion"],
            "Pneumonia": ["Pneumonia"],
            "Atelectasis": ["Atelectasis"],
            "Consolidation": ["Consolidation"],
            "Pulmonary edema": ["Edema"],
            "Pneumothorax": ["Pneumothorax"],
        }
        mapping: dict[str, int] = {}
        for canonical, candidates in canonical_to_txv.items():
            for i, p in enumerate(pathologies):
                if p.strip() and p.strip().lower() in [c.lower() for c in candidates]:
                    mapping[canonical] = i
                    break
        return mapping

    def predict(self, image: Image.Image) -> list[FindingPrediction]:
        import torchxrayvision as xrv

        img_gray = image.convert("L").resize((224, 224))
        img_arr = np.array(img_gray).astype(np.float32)
        img_norm = xrv.utils.normalize(img_arr, 255)  # [-1024, 1024]
        img_norm = img_norm[None, :, :]  # [1, H, W]
        tensor = torch.from_numpy(img_norm).unsqueeze(0).float().to(self.device)

        with torch.no_grad():
            logits = self.model(tensor)
            probs = torch.sigmoid(logits).cpu().numpy().flatten()

        # Map known pathologies to canonical findings.
        canonical_probs: dict[str, float] = {}
        for canonical, idx in self._label_map.items():
            canonical_probs[canonical] = float(probs[idx])

        # "No finding" as the complement of the highest pathology probability.
        max_pathology = max(canonical_probs.values()) if canonical_probs else 0.0
        canonical_probs["No finding"] = max(0.0, 1.0 - max_pathology)

        findings = [
            FindingPrediction(label=label, confidence=canonical_probs.get(label, 0.0), region=None)
            for label in FINDINGS
        ]
        findings.sort(key=lambda x: x.confidence, reverse=True)
        return findings

    def get_attention_heatmap(self, image: Image.Image, label: str) -> np.ndarray:
        return _attention_heatmap_from_raddino(self.encoder, image, label)

    def get_gradcam_heatmap(self, image: Image.Image, label: str) -> np.ndarray:
        if self.gradcam is None:
            h, w = image.size[1], image.size[0]
            return np.zeros((h, w), dtype=np.uint8)
        return self.gradcam.heatmap(image, label, self.model.pathologies)

    def get_gradcam_heatmaps_for_findings(
        self, image: Image.Image, findings: list
    ) -> list[tuple[str, np.ndarray]]:
        if self.gradcam is None:
            return []
        return self.gradcam.heatmaps_for_findings(image, findings, self.model.pathologies)


class ChestXRayClassifier:
    """Dispatcher that selects the classification backend.

    - If CLASSIFIER_HEAD is set -> RAD-DINO + custom head.
    - Otherwise -> TorchXRayVision pretrained model.

    Both backends expose the same interface and use RAD-DINO for attention maps.
    """

    def __init__(self, device: str = "cpu", head_path: Optional[str] = None):
        self.device = device
        self.head_path = head_path or os.environ.get("CLASSIFIER_HEAD")
        if self.head_path:
            self.backend: ClassifierBackend = RADDINOClassifierBackend(
                device=device, head_path=self.head_path
            )
        else:
            self.backend: ClassifierBackend = TorchXRayVisionClassifierBackend(device=device)
        self.findings_list = self.backend.findings_list

    def predict(self, image: Image.Image) -> list[FindingPrediction]:
        return self.backend.predict(image)

    def get_attention_heatmap(self, image: Image.Image, label: str) -> np.ndarray:
        return self.backend.get_attention_heatmap(image, label)

    def get_gradcam_heatmap(self, image: Image.Image, label: str) -> np.ndarray:
        return self.backend.get_gradcam_heatmap(image, label)

    def get_gradcam_heatmaps_for_findings(
        self, image: Image.Image, findings: list
    ) -> list[tuple[str, np.ndarray]]:
        return self.backend.get_gradcam_heatmaps_for_findings(image, findings)
