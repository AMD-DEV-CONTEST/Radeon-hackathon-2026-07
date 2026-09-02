"""Deployable learned grasp policy — drop-in replacement for HeuristicGraspPolicy.

Trained on AMD Radeon GPU, Spearman r=0.964, MAE=0.039.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from pathlib import Path

from radeon_home.models import GraspCandidate, ScoredGrasp


class GraspMLP(nn.Module):
    """Small MLP scoring model (128→64→32→1), trained on heuristic output."""
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(6, 128), nn.ReLU(),
            nn.Linear(128, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


class LearnedGraspPolicy:
    """Learned grasp scorer — same interface as HeuristicGraspPolicy.

    Loads a checkpoint trained on AMD Radeon GPU and scores candidates
    using GPU-accelerated inference.
    """

    def __init__(self, checkpoint_path: str | None = None):
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._device = device

        self._model = GraspMLP().to(device)
        self._model.eval()

        self._x_mean = torch.zeros(6)
        self._x_std = torch.ones(6)
        self._y_mean = torch.tensor(0.0)
        self._y_std = torch.tensor(1.0)
        self._spearman_r = 0.0
        self._loaded = False

        if checkpoint_path:
            self.load(checkpoint_path)

    def load(self, path: str) -> None:
        ckpt = torch.load(path, map_location=self._device, weights_only=False)
        self._model.load_state_dict(ckpt["model_state_dict"])
        self._x_mean = ckpt["x_mean"].detach().clone().to(self._device)
        self._x_std = ckpt["x_std"].detach().clone().to(self._device)
        self._y_mean = ckpt["y_mean"].detach().clone().to(self._device)
        self._y_std = ckpt["y_std"].detach().clone().to(self._device)
        self._spearman_r = ckpt.get("spearman_r", 0.0)
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def spearman_r(self) -> float:
        return self._spearman_r

    def _featurize(self, c: GraspCandidate) -> list[float]:
        return [
            c.offset_x_m, c.offset_y_m,
            c.yaw_deg / 30.0,
            c.approach_height_m,
            c.obstacle_clearance_m,
            float(c.previous_failures) / 3.0,
        ]

    def score(self, candidate: GraspCandidate) -> ScoredGrasp:
        feat = torch.tensor([self._featurize(candidate)], dtype=torch.float32, device=self._device)
        feat_norm = (feat - self._x_mean) / self._x_std
        with torch.inference_mode():
            pred_norm = self._model(feat_norm)
            score = float((pred_norm * self._y_std + self._y_mean).item())
        return ScoredGrasp(
            candidate=candidate,
            score=round(score, 6),
            reasons=(f"learned_policy(spearman_r={self._spearman_r:.3f})",),
        )

    def rank(self, candidates: list[GraspCandidate]) -> list[ScoredGrasp]:
        if not candidates:
            return []
        feats = torch.tensor(
            [self._featurize(c) for c in candidates],
            dtype=torch.float32, device=self._device,
        )
        feats_norm = (feats - self._x_mean) / self._x_std
        with torch.inference_mode():
            preds_norm = self._model(feats_norm)
            scores = (preds_norm * self._y_std + self._y_mean).cpu().tolist()

        scored = [
            ScoredGrasp(
                candidate=candidates[i],
                score=round(float(scores[i]), 6),
                reasons=(f"learned_policy(spearman_r={self._spearman_r:.3f})",),
            )
            for i in range(len(candidates))
        ]
        return sorted(scored, key=lambda s: s.score, reverse=True)
