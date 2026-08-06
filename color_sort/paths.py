"""Single source of truth for the color_sort pipeline's filesystem layout.

All pipeline code lives in the ``color_sort`` package. Generated artifacts
(outputs/) live at the repository root, one level above this package.
Import these directory constants instead of recomputing paths.
"""

from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent  # .../color_sort
REPO_ROOT = PKG_DIR.parent  # repository root

# Generated artifacts (gitignored).
OUTPUTS_DIR = REPO_ROOT / "outputs"
DATASETS_DIR = REPO_ROOT / "datasets"
EVAL_RESULTS_DIR = OUTPUTS_DIR / "eval_results"
EVAL_VIDEOS_DIR = OUTPUTS_DIR / "eval_videos"
FRAMES_DIR = OUTPUTS_DIR / "color_sort_frames"