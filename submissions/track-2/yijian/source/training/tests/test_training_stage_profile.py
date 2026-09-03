# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import build_training_stage_profile as profile  # noqa: E402


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_legacy_smoke_is_normalized_only_with_half_epoch_evidence(tmp_path: Path) -> None:
    metrics = tmp_path / "metrics.json"
    hardware = tmp_path / "hardware.json"
    _write(metrics, {"trainExamples": 8, "epoch": .5, "peakReservedGiB": 36.553})
    _write(hardware, {"modelRevision": profile.REVISION})
    result = profile.build("smoke", metrics, hardware)
    assert result["passed"] is True
    assert result["optimizerSteps"] == 4


def test_profile_rejects_failed_micro(tmp_path: Path) -> None:
    metrics = tmp_path / "metrics.json"
    hardware = tmp_path / "hardware.json"
    _write(metrics, {"passed": False, "optimizerSteps": 30, "peakReservedGiB": 40})
    _write(hardware, {"modelRevision": profile.REVISION})
    with pytest.raises(profile.ProfileError, match="have not passed"):
        profile.build("micro", metrics, hardware)
