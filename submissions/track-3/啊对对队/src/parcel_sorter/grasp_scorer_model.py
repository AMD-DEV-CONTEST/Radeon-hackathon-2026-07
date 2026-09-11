from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .grasp_scoring import GRASP_FEATURE_NAMES, validate_feature_names


def build_grasp_scorer_network(torch: Any, hidden_width: int) -> Any:
    if hidden_width < 1:
        raise ValueError("hidden_width must be positive")
    return torch.nn.Sequential(
        torch.nn.Linear(len(GRASP_FEATURE_NAMES), hidden_width),
        torch.nn.SiLU(),
        torch.nn.Linear(hidden_width, hidden_width),
        torch.nn.SiLU(),
        torch.nn.Linear(hidden_width, 4),
    )


class StructuredGraspScorer:
    """Load and run the small safety-first scorer without changing control."""

    def __init__(self, checkpoint: str | Path, device: str = "cuda") -> None:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("PyTorch is required for grasp scorer inference") from exc
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("AMD ROCm device is unavailable through torch.cuda")
        payload = torch.load(Path(checkpoint), map_location="cpu", weights_only=True)
        if int(payload.get("schema_version", -1)) != 1:
            raise ValueError("unsupported grasp scorer checkpoint schema")
        validate_feature_names(payload["feature_names"])
        self.torch = torch
        self.device = torch.device(device)
        self.feature_names = tuple(payload["feature_names"])
        self.feature_mean = payload["feature_mean"].to(
            device=self.device, dtype=torch.float32
        )
        self.feature_scale = payload["feature_scale"].to(
            device=self.device, dtype=torch.float32
        )
        if self.feature_mean.shape != (len(GRASP_FEATURE_NAMES),):
            raise ValueError("invalid grasp scorer feature mean shape")
        if self.feature_scale.shape != (len(GRASP_FEATURE_NAMES),):
            raise ValueError("invalid grasp scorer feature scale shape")
        if not bool(torch.isfinite(self.feature_mean).all()):
            raise ValueError("grasp scorer feature mean must be finite")
        if not bool(torch.isfinite(self.feature_scale).all()) or not bool(
            (self.feature_scale > 0).all()
        ):
            raise ValueError("grasp scorer feature scale must be finite and positive")
        self.model = build_grasp_scorer_network(torch, int(payload["hidden_width"]))
        self.model.load_state_dict(payload["model_state_dict"], strict=True)
        self.model.to(self.device).eval()

    def predict(
        self,
        features: Sequence[Sequence[float]],
        metadata: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if not features or len(features) != len(metadata):
            raise ValueError("features and metadata must contain the same nonzero rows")
        values = tuple(tuple(float(value) for value in row) for row in features)
        if any(len(row) != len(GRASP_FEATURE_NAMES) for row in values):
            raise ValueError("grasp scorer feature row has the wrong width")
        if any(not math.isfinite(value) for row in values for value in row):
            raise ValueError("grasp scorer features must be finite")
        tensor = self.torch.tensor(
            values, dtype=self.torch.float32, device=self.device
        )
        with self.torch.inference_mode():
            raw = self.model((tensor - self.feature_mean) / self.feature_scale)
            unsafe = self.torch.sigmoid(raw[:, 0])
            success = self.torch.sigmoid(raw[:, 1])
            force = self.torch.expm1(raw[:, 2]).clamp_min(0)
            duration = self.torch.expm1(raw[:, 3]).clamp_min(0)
            if self.device.type == "cuda":
                self.torch.cuda.synchronize()
        return [
            {
                "candidate_id": str(row["candidate_id"]),
                "static_rank": int(row["static_rank"]),
                "unsafe_probability": float(unsafe[index].cpu()),
                "success_probability": float(success[index].cpu()),
                "predicted_force_n": float(force[index].cpu()),
                "predicted_duration_seconds": float(duration[index].cpu()),
            }
            for index, row in enumerate(metadata)
        ]
