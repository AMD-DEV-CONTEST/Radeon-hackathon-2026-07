"""The two frozen gripper designs this project's entire results/ directory is
built on: the searched winner and the stock-equivalent baseline.

Both are copied verbatim from `franka_fruit_pick/codesign/run_attribution.py`
(the source of truth — these values are duplicated here, not imported, so this
file can be read standalone as the project's single canonical reference for
"what design produced this number," without needing the full package on the
import path). If the two ever drift, `run_attribution.py` is correct; open an
issue.

Neither design was touched by any experiment after being frozen — every table
in `results/` (confirmation-eval, attribution, generalization, ROCm, cross-
simulator, FruitArchive, contact-geometry) evaluates these exact five numbers
per design, never a re-tuned variant.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GripperParams:
    n_fingers: int
    finger_length: float  # m
    curvature_deg: float  # total finger bend, base segment -> tip segment
    aperture: float  # m, max total fingertip-to-fingertip opening
    compliance: float  # 0 = rigid, 1 = soft


# Stock-equivalent: 2-finger, straight, rigid — the reference every headline
# number is measured against.
BASELINE_PARAMS = GripperParams(
    n_fingers=2, finger_length=0.0454, curvature_deg=0.0, aperture=0.08, compliance=0.0,
)

# The searched winner (population=5, generations=5 CMA-ES branches over
# n_fingers in {2, 3}, see search.py / run_attribution.py): 3-finger,
# near-straight, wide aperture, moderate compliance.
WINNER_PARAMS = GripperParams(
    n_fingers=3,
    finger_length=0.04617883576142882,
    curvature_deg=4.203232665740063,
    aperture=0.09122108937742585,
    compliance=0.2337742993191176,
)

# Headline result these two designs produced (confirmation-eval, n=30 paired
# trials, Genesis): winner 93.3% [78.7%, 98.2%] vs baseline 26.7% [14.2%,
# 44.4%] — see results/01_core_confirmation/findings.md for the full table
# and results/05_cross_simulator/ for the MuJoCo replication of the same pair.
