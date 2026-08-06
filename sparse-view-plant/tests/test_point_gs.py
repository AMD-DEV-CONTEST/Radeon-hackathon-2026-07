"""Tests for the point-GS opacity ramp helpers."""

from __future__ import annotations

import numpy as np
import torch

from sparse_view_plant.point_gs import confidence_opacity_logits


def test_confidence_opacity_logits_default_matches_original() -> None:
    rng = np.random.default_rng(0)
    confidence = torch.from_numpy(rng.uniform(0.2, 0.9, 4096)).float()
    logits = confidence_opacity_logits(confidence)
    opacity = torch.sigmoid(logits)
    assert opacity.min() > 0.01
    assert opacity.max() < 0.99
    assert torch.quantile(opacity, 0.95) > 0.5


def test_confidence_opacity_logits_lower_max_thins_splats() -> None:
    rng = np.random.default_rng(0)
    confidence = torch.from_numpy(rng.uniform(0.2, 0.9, 4096)).float()
    full = torch.sigmoid(confidence_opacity_logits(confidence))
    thin = torch.sigmoid(confidence_opacity_logits(confidence, opacity_max=0.3))
    assert thin.max() < 0.31
    assert torch.quantile(thin, 0.95) < torch.quantile(full, 0.95)
