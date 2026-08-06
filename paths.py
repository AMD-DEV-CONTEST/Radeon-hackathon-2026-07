"""Single source of truth for Radeon-VLA-SO101's on-disk layout.

All project code lives under ``radeon-vla-so101/``. Bundled robot assets land in
``assets/`` (populated by ``scripts/setup_so101_assets.py``), recorded LeRobot
datasets in ``datasets/``, and generated artifacts (videos, benchmark results,
eval frames) in ``outputs/``. Import these constants instead of recomputing paths
from ``__file__`` so the layout lives in exactly one place.
"""

from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent  # .../radeon-vla-so101
REPO_ROOT = PKG_DIR  # this sub-project is self-contained

# Bundled / fetched inputs.
ASSETS_DIR = PKG_DIR / "assets"
SO101_DIR = ASSETS_DIR / "robots" / "so101"
DATASETS_DIR = PKG_DIR / "datasets"

# Generated artifacts (gitignored).
OUTPUTS_DIR = PKG_DIR / "outputs"
DEMO_DIR = PKG_DIR / "demo"
BENCHMARK_DIR = PKG_DIR / "benchmark"
EVAL_VIDEOS_DIR = OUTPUTS_DIR / "eval_videos"
FRAMES_DIR = OUTPUTS_DIR / "demo_frames"
TRAIN_DIR = OUTPUTS_DIR / "train"
