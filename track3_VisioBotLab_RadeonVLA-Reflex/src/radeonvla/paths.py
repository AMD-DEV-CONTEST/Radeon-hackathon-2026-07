"""Filesystem layout for the self-contained project directory."""

from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PKG_DIR.parent.parent

ASSETS_DIR = PROJECT_ROOT / "assets"
DATASETS_DIR = PROJECT_ROOT / "datasets"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
CHECKPOINTS_DIR = PROJECT_ROOT / "checkpoints"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
CONFIGS_DIR = PROJECT_ROOT / "configs"
DOCS_DIR = PROJECT_ROOT / "docs"
REPORTS_DIR = PROJECT_ROOT / "reports"

EVAL_RESULTS_DIR = OUTPUTS_DIR / "eval_results"
EVAL_VIDEOS_DIR = OUTPUTS_DIR / "eval_videos"
TRAIN_DIR = OUTPUTS_DIR / "train"
FRAMES_DIR = OUTPUTS_DIR / "frames"
BENCHMARK_DIR = OUTPUTS_DIR / "benchmark"

YCB_DIR = ASSETS_DIR / "ycb"
ROBOT_DIR = ASSETS_DIR / "robots" / "franka"
