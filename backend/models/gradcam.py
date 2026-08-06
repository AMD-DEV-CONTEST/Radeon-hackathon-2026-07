"""Grad-CAM explainability for chest X-ray classifiers.

Provides class-discriminative localization heatmaps by backpropagating the
gradient of a target finding through the convolutional feature maps of the
classifier.

Efficiency note: the batch method runs the model forward **once** and then
backpropagates each target class while retaining the graph, so Grad-CAM for
all predicted findings is computed with roughly the cost of one forward pass
plus one backward pass per class.
"""
from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


class GradCAMExtractor:
    """Extract Grad-CAM heatmaps for a given model and target layer.

    Usage:
        extractor = GradCAMExtractor(model, target_layer_name="features.norm5")
        heatmaps = extractor.compute_heatmaps(image_tensor, class_indices=[5, 3], image_size=(W, H))
    """

    def __init__(self, model: torch.nn.Module, target_layer_name: str):
        self.model = model
        self.target_layer_name = target_layer_name
        self.target_layer = self._find_layer(target_layer_name)
        self.activations: Optional[torch.Tensor] = None
        self.gradients: Optional[torch.Tensor] = None
        self._hooks: list = []
        self._register_hooks()

    def _find_layer(self, target_layer_name: str) -> torch.nn.Module:
        parts = target_layer_name.split(".")
        module = self.model
        for part in parts:
            module = module[int(part)] if part.isdigit() else getattr(module, part)
        return module

    def _register_hooks(self) -> None:
        def forward_hook(_module, _input, output):
            self.activations = output.detach()

        def backward_hook(_module, _grad_input, grad_output):
            self.gradients = grad_output[0].detach()

        self._hooks.append(self.target_layer.register_forward_hook(forward_hook))
        # register_backward_hook is deprecated and unreliable; use
        # register_full_backward_hook when available.
        if hasattr(self.target_layer, "register_full_backward_hook"):
            self._hooks.append(self.target_layer.register_full_backward_hook(backward_hook))
        else:
            self._hooks.append(self.target_layer.register_backward_hook(backward_hook))

    def remove_hooks(self) -> None:
        for hook in self._hooks:
            hook.remove()
        self._hooks.clear()

    def _cam_from_gradients(
        self,
        gradients: torch.Tensor,
        activations: torch.Tensor,
        image_size: Tuple[int, int],
    ) -> np.ndarray:
        """Compute a single Grad-CAM heatmap from captured gradients/activations."""
        weights = gradients.mean(dim=(1, 2), keepdim=True)  # [C, 1, 1]
        cam = (weights * activations).sum(dim=0)  # [H, W]
        cam = F.relu(cam)

        cam = cam - cam.min()
        if cam.max() > 0:
            cam = cam / cam.max()

        cam = cam.unsqueeze(0).unsqueeze(0)  # [1, 1, H, W]
        cam = F.interpolate(
            cam,
            size=(image_size[1], image_size[0]),
            mode="bilinear",
            align_corners=False,
        )
        cam = cam.squeeze().cpu().numpy()
        cam = np.clip(cam, 0, 1)
        return (cam * 255).astype(np.uint8)

    def compute_heatmaps(
        self,
        input_tensor: torch.Tensor,
        class_indices: list[int],
        image_size: Tuple[int, int],
    ) -> dict[int, np.ndarray]:
        """Compute Grad-CAM heatmaps for multiple classes with one forward pass.

        Args:
            input_tensor: preprocessed image tensor, [1, C, H, W]
            class_indices: list of target class indices
            image_size: (W, H) to resize each heatmap to

        Returns:
            dict mapping class index to uint8 grayscale heatmap
        """
        self.model.zero_grad()
        output = self.model(input_tensor)

        # We must have captured activations from the single forward pass.
        if self.activations is None:
            raise RuntimeError("Forward hook did not capture activations.")
        activations = self.activations[0]  # [C, H, W]

        heatmaps: dict[int, np.ndarray] = {}
        # Backward once per class while retaining the graph so the forward pass
        # is not re-executed.
        for i, class_idx in enumerate(class_indices):
            self.gradients = None
            retain = i < len(class_indices) - 1
            target_score = output[0, class_idx]
            target_score.backward(retain_graph=retain)

            if self.gradients is None:
                raise RuntimeError(f"Backward hook did not capture gradients for class {class_idx}.")

            heatmaps[class_idx] = self._cam_from_gradients(
                self.gradients[0], activations, image_size
            )

        return heatmaps

    def __call__(
        self,
        input_tensor: torch.Tensor,
        class_idx: int,
        image_size: Tuple[int, int],
    ) -> np.ndarray:
        """Compute Grad-CAM heatmap for a single class (convenience)."""
        return self.compute_heatmaps(input_tensor, [class_idx], image_size)[class_idx]


def _preprocess_for_torchxrayvision(image: Image.Image, device: str) -> torch.Tensor:
    """Convert a PIL image to the TorchXRayVision DenseNet input format."""
    import torchxrayvision as xrv

    img_gray = image.convert("L").resize((224, 224))
    img_arr = np.array(img_gray).astype(np.float32)
    img_norm = xrv.utils.normalize(img_arr, 255)
    img_norm = img_norm[None, :, :]
    return torch.from_numpy(img_norm).unsqueeze(0).float().to(device)


def _canonical_to_pathology_index(label: str, pathologies: list[str]) -> Optional[int]:
    """Map a canonical finding label to a TorchXRayVision pathology index."""
    normalized = label.lower().replace("pulmonary edema", "edema").replace("pleural effusion", "effusion")
    for i, p in enumerate(pathologies):
        if p.strip() and p.strip().lower() == normalized:
            return i
    return None


class XRayGradCAM:
    """Grad-CAM wrapper for the default TorchXRayVision DenseNet classifier."""

    def __init__(self, model: torch.nn.Module, device: str = "cpu"):
        self.device = device
        self.model = model
        # Last convolution in DenseNet121; feel free to tune for other backbones.
        self.extractor = GradCAMExtractor(model, target_layer_name="features.denseblock4.denselayer16.conv2")

    def heatmap(self, image: Image.Image, label: str, pathologies: list[str]) -> np.ndarray:
        """Return a Grad-CAM heatmap for a single pathology label."""
        class_idx = _canonical_to_pathology_index(label, pathologies)
        if class_idx is None:
            h, w = image.size[1], image.size[0]
            return np.zeros((h, w), dtype=np.uint8)

        input_tensor = _preprocess_for_torchxrayvision(image, self.device)
        return self.extractor(input_tensor, class_idx, image.size)

    def heatmaps_for_findings(
        self,
        image: Image.Image,
        findings: list,
        pathologies: list[str],
        confidence_threshold: float = 0.05,
    ) -> list[tuple[str, np.ndarray]]:
        """Compute Grad-CAM heatmaps for all findings above the threshold.

        Uses a single shared forward pass for efficiency.
        """
        relevant = [f for f in findings if f.confidence >= confidence_threshold]
        class_indices: list[int] = []
        labels: list[str] = []
        for finding in relevant:
            idx = _canonical_to_pathology_index(finding.label, pathologies)
            if idx is not None:
                class_indices.append(idx)
                labels.append(finding.label)

        if not class_indices:
            return []

        input_tensor = _preprocess_for_torchxrayvision(image, self.device)
        heatmaps_by_idx = self.extractor.compute_heatmaps(input_tensor, class_indices, image.size)

        results: list[tuple[str, np.ndarray]] = []
        for label, idx in zip(labels, class_indices):
            results.append((label, heatmaps_by_idx[idx]))
        return results

    def __del__(self):
        if hasattr(self, "extractor"):
            self.extractor.remove_hooks()
