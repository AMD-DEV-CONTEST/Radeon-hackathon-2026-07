"""Single source of truth for the demo's filesystem layout.

All code lives in the ``franka_fruit_pick`` package. Bundled inputs (``assets/``,
``datasets/``) and generated artifacts (``outputs/``) live at the repository root,
one level above this package. Import these directory constants instead of recomputing
paths from ``__file__`` so the layout lives in exactly one place.
"""

from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent  # .../franka_fruit_pick
REPO_ROOT = PKG_DIR.parent  # repository root

# Bundled inputs (shipped with the repo -- see README).
ASSETS_DIR = REPO_ROOT / "assets"
DATASETS_DIR = REPO_ROOT / "datasets"

# Generated artifacts (gitignored).
OUTPUTS_DIR = REPO_ROOT / "outputs"
EVAL_RESULTS_DIR = OUTPUTS_DIR / "eval_results"
EVAL_VIDEOS_DIR = OUTPUTS_DIR / "eval_videos"
FRAMES_DIR = OUTPUTS_DIR / "grasp_demo_frames"
