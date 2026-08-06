"""RAD-DINO vision encoder for chest X-ray analysis.

Loads a pretrained RAD-DINO checkpoint and extracts:
- global [CLS] embedding for classification
- patch embeddings for localization / GradCAM
- last-layer attention weights for attention-based localization

Designed to run on CPU, CUDA, and ROCm (via torch.version.hip).
"""
import os
from typing import Optional, Tuple

import torch
import torch.nn as nn
from PIL import Image


DEFAULT_RADDINO_MODEL = "microsoft/rad-dino"


class RADDINOVisionEncoder:
    """Wrapper around a RAD-DINO-style vision transformer.

    The model is loaded with HuggingFace Transformers and kept in eval mode.
    Patch embeddings are returned in a spatial layout so downstream modules
    can build heatmaps aligned with the original image.
    """

    def __init__(self, device: str = "cpu", model_name: Optional[str] = None):
        self.device = device
        self.model_name = model_name or os.environ.get("RADDINO_MODEL", DEFAULT_RADDINO_MODEL)
        self.processor = None
        self.model: Optional[nn.Module] = None
        self._load_model()

    def _load_model(self) -> None:
        from transformers import AutoImageProcessor, AutoModel

        try:
            processor = AutoImageProcessor.from_pretrained(self.model_name)
            model = AutoModel.from_pretrained(self.model_name, trust_remote_code=True)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load RAD-DINO model '{self.model_name}'. "
                "Ensure you have an internet connection or the model is cached, "
                f"and that 'transformers' is installed. Original error: {exc}"
            ) from exc

        self.processor = processor
        self.model = model.eval().to(self.device)
        self.hidden_size: int = int(getattr(model.config, "hidden_size", 768))

    def _process_inputs(self, image: Image.Image) -> dict:
        if self.processor is None:
            raise RuntimeError("RAD-DINO processor is not loaded.")
        inputs = self.processor(images=image, return_tensors="pt")
        return {k: v.to(self.device) for k, v in inputs.items()}

    def _forward(
        self, image: Image.Image, return_attention: bool
    ) -> Tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor]]:
        if self.model is None:
            raise RuntimeError("RAD-DINO model is not loaded.")

        inputs = self._process_inputs(image)
        outputs = self.model(
            **inputs,
            output_hidden_states=False,
            output_attentions=return_attention,
            return_dict=True,
        )
        # RAD-DINO / DINOv2 returns last_hidden_state of shape [B, N_tokens, hidden]
        # Token 0 is [CLS], remaining tokens are patch tokens.
        last_hidden = outputs.last_hidden_state  # type: ignore[attr-defined]
        cls_embedding = last_hidden[:, 0, :]  # [B, hidden]

        B = last_hidden.shape[0]
        patch_tokens = last_hidden[:, 1:, :]  # [B, num_patches, hidden]
        num_patches = patch_tokens.shape[1]

        # DINOv2 base with patch size 14 => 518/14 = 37 patches per side.
        # Try to infer a square grid; if not square, fall back to 1-D.
        grid_size = int(num_patches ** 0.5)
        if grid_size * grid_size != num_patches:
            # Some processors may return non-square patch layouts; use 1xN shape.
            grid_size = 1
        H_p = W_p = grid_size
        patch_embeddings = patch_tokens.reshape(B, H_p, W_p, -1).permute(0, 3, 1, 2)

        attention: Optional[torch.Tensor] = None
        if return_attention:
            attentions = outputs.attentions  # type: ignore[attr-defined]
            if attentions is None or len(attentions) == 0:
                raise RuntimeError("Model did not return attention weights.")
            attention = attentions[-1]  # [B, heads, N_tokens, N_tokens]

        return cls_embedding, patch_embeddings, attention

    def extract_features(self, image: Image.Image) -> Tuple[torch.Tensor, torch.Tensor]:
        """Extract CLS and patch embeddings.

        Returns:
            cls_embedding: [1, hidden_size]
            patch_embeddings: [1, hidden_size, H_p, W_p]
        """
        cls_embedding, patch_embeddings, _ = self._forward(image, return_attention=False)
        return cls_embedding, patch_embeddings

    def extract_features_with_attention(
        self, image: Image.Image
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Extract CLS embedding, patch embeddings, and last-layer attention.

        Returns:
            cls_embedding: [1, hidden_size]
            patch_embeddings: [1, hidden_size, H_p, W_p]
            attention: [1, num_heads, N_tokens, N_tokens]
        """
        cls_embedding, patch_embeddings, attention = self._forward(image, return_attention=True)
        if attention is None:
            raise RuntimeError("Model did not return attention weights.")
        return cls_embedding, patch_embeddings, attention

    def __call__(self, image: Image.Image):
        return self.extract_features(image)
