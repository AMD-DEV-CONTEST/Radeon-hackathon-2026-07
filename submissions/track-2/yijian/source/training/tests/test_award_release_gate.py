# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import award_release_gate as gate  # noqa: E402


def test_release_requires_every_competition_gate(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
    adapter_hash = gate.tree_hash(adapter)
    result = gate.build_release(
        agent={
            "passed": True,
            "counts": {"train": 720},
            "taskCounts": gate.EXPECTED_TASK_COUNTS,
        },
        smoke={"passed": True, "optimizerSteps": 4, "peakReservedGiB": 36.5},
        micro={
            "passed": True,
            "optimizerSteps": 30,
            "peakReservedGiB": 40,
            "learningProof": {"lossDropped": True, "relativeLossDrop": .08},
        },
        full={
            "passed": True,
            "completedEpochs": 2,
            "optimizerSteps": 90,
            "peakReservedGiB": 41,
            "devLearningProof": {"lossDropped": True},
            "devTaskLearningProof": {
                "improvedTaskCount": 2,
                "tasks": {
                    "answer": {"regressedMoreThanTenPercent": False},
                    "planner": {"regressedMoreThanTenPercent": False},
                    "followup": {"regressedMoreThanTenPercent": False},
                },
            },
        },
        evaluation={"passed": True},
        blind={"passed": True},
        sealed={
            "passed": True,
            "accessedAfterAdapterFreeze": True,
            "cases": 8,
            "severeContradictions": 0,
            "meanTeachingQuality": 4.2,
        },
        coexist={
            "passed": True,
            "passingProfiles": ["0.72"],
            "profileReports": [{
                "passed": True,
                "cycles": 30,
                "oomCount": 0,
                "combined": {"p95Seconds": 10.5},
            }],
        },
        public_snapshot={
            "passed": True,
            "secretFindings": 0,
            "privateDataFindings": 0,
        },
        freeze={
            "frozen": True,
            "baseRevision": gate.EXPECTED_REVISION,
            "adapterTreeSha256": adapter_hash,
        },
        adapter_dir=adapter,
    )
    assert result["passed"] is True
    assert all(result["gates"].values())


def test_release_rejects_weak_micro_and_pre_freeze_sealed(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
    adapter_hash = gate.tree_hash(adapter)
    good = {
        "agent": {"passed": True, "counts": {"train": 720}, "taskCounts": gate.EXPECTED_TASK_COUNTS},
        "smoke": {"passed": True, "optimizerSteps": 4, "peakReservedGiB": 36},
        "micro": {"passed": True, "optimizerSteps": 30, "peakReservedGiB": 40, "learningProof": {"lossDropped": True, "relativeLossDrop": .01}},
        "full": {"passed": True, "completedEpochs": 2, "optimizerSteps": 90, "peakReservedGiB": 40, "devLearningProof": {"lossDropped": True}, "devTaskLearningProof": {"improvedTaskCount": 2, "tasks": {"a": {"regressedMoreThanTenPercent": False}}}},
        "evaluation": {"passed": True}, "blind": {"passed": True},
        "sealed": {"passed": True, "accessedAfterAdapterFreeze": False, "cases": 8, "severeContradictions": 0, "meanTeachingQuality": 5},
        "coexist": {"passed": True, "passingProfiles": ["0.72"], "profileReports": [{"passed": True, "cycles": 30, "oomCount": 0, "combined": {"p95Seconds": 10}}]},
        "public_snapshot": {"passed": True, "secretFindings": 0, "privateDataFindings": 0},
        "freeze": {"frozen": True, "baseRevision": gate.EXPECTED_REVISION, "adapterTreeSha256": adapter_hash},
        "adapter_dir": adapter,
    }
    result = gate.build_release(**good)
    assert result["passed"] is False
    assert result["gates"]["microThirtyStepsAndFivePercent"] is False
    assert result["gates"]["sealedOnceAfterFreeze"] is False


def test_adapter_tree_hash_uses_portable_utf8_relative_path_order(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "README.md").write_bytes(b"upper")
    (adapter / "adapter_config.json").write_bytes(b"lower")

    digest = hashlib.sha256()
    for name in ("README.md", "adapter_config.json"):
        relative = name.encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(hashlib.sha256((adapter / name).read_bytes()).digest())

    assert gate.tree_hash(adapter) == digest.hexdigest()
