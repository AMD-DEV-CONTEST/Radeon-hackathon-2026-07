# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import build_micro_selection as selector  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _row(index: int, source: str, task: str, target: str = "actual") -> dict:
    return {
        "messages": [
            {"role": "user", "content": f"question-{index}"},
            {"role": "assistant", "content": f"answer-{index}"},
        ],
        "metadata": {
            "split": "train",
            "sourceCaseId": f"case-{index:03d}",
            "sourceType": source,
            "taskType": task,
            "questionTarget": target,
        },
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    required = [
        _row(0, "creator_authorized", "answer", "actual"),
        _row(1, "creator_authorized", "planner", "best"),
        _row(2, "creator_authorized", "followup", "comparison"),
        _row(3, "public_domain", "planner"),
        _row(4, "project_original", "answer"),
        _row(5, "project_original", "followup"),
        _row(6, "project_original", "memory_privacy"),
        _row(7, "project_original", "memory_privacy"),
    ]
    filler = [
        _row(index, "project_original", "answer")
        for index in range(8, 720)
    ]
    train = tmp_path / "agent_sft_train.jsonl"
    dev = tmp_path / "agent_sft_dev.jsonl"
    manifest = tmp_path / "manifest.json"
    _write_jsonl(train, required + filler)
    _write_jsonl(dev, [_row(800, "creator_authorized", "answer")])
    manifest.write_text(
        json.dumps({
            "schemaVersion": "yijian-agent-sft-v1",
            "passed": True,
            "outputs": {
                train.name: selector.file_hash(train),
                dev.name: selector.file_hash(dev),
            },
        }),
        encoding="utf-8",
    )
    return train, manifest, dev


def test_micro_selection_is_exact_distinct_and_never_reads_sealed(tmp_path: Path) -> None:
    train, manifest, dev = _fixture(tmp_path)
    selected, audit = selector.build(train, manifest, dev)
    assert len(selected) == 8
    assert len({row["metadata"]["sourceCaseId"] for row in selected}) == 8
    assert audit["taskCounts"] == {
        "answer": 2,
        "planner": 2,
        "followup": 2,
        "memory_privacy": 2,
    }
    assert audit["sourceCounts"] == {
        "creator_authorized": 3,
        "public_domain": 1,
        "project_original": 4,
    }
    assert audit["sealedTestAccessed"] is False
    creator_targets = {
        row["metadata"]["questionTarget"]
        for row in selected
        if row["metadata"]["sourceType"] == "creator_authorized"
    }
    assert creator_targets == {"actual", "best", "comparison"}


def test_micro_selection_rejects_parent_hash_change(tmp_path: Path) -> None:
    train, manifest, dev = _fixture(tmp_path)
    dev.write_text(dev.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(selector.SelectionError, match="hash mismatch"):
        selector.build(train, manifest, dev)


def test_micro_selection_rejects_non_train_rows(tmp_path: Path) -> None:
    train, manifest, dev = _fixture(tmp_path)
    rows = selector.read_jsonl(train)
    rows[-1]["metadata"]["split"] = "test"
    _write_jsonl(train, rows)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["outputs"][train.name] = selector.file_hash(train)
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(selector.SelectionError, match="train-only"):
        selector.build(train, manifest, dev)


def test_micro_selection_accepts_the_v2_question_first_manifest(tmp_path: Path) -> None:
    train, manifest, dev = _fixture(tmp_path)
    rows = selector.read_jsonl(train)
    next(row for row in rows if row["metadata"]["sourceType"] == "project_original" and row["metadata"]["taskType"] == "answer")["metadata"]["projectOriginalAugmentation"] = "conceptual-routing-remediation-v2"
    _write_jsonl(train, rows)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["schemaVersion"] = "yijian-agent-sft-v2"
    value["outputs"][train.name] = selector.file_hash(train)
    manifest.write_text(json.dumps(value), encoding="utf-8")
    selected, audit = selector.build(train, manifest, dev)
    assert len(selected) == 8
    assert audit["sealedTestAccessed"] is False
    assert any(record["label"] == "project-concept-routing-answer" for record in audit["records"])


def test_micro_selection_accepts_v3_concept_binding(tmp_path: Path) -> None:
    train, manifest, dev = _fixture(tmp_path)
    rows = selector.read_jsonl(train)
    next(
        row for row in rows
        if row["metadata"]["sourceType"] == "project_original"
        and row["metadata"]["taskType"] == "answer"
    )["metadata"]["projectOriginalAugmentation"] = "conceptual-routing-remediation-v3"
    _write_jsonl(train, rows)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["schemaVersion"] = "yijian-agent-sft-v3"
    value["outputs"][train.name] = selector.file_hash(train)
    manifest.write_text(json.dumps(value), encoding="utf-8")
    selected, audit = selector.build(train, manifest, dev)
    assert len(selected) == 8
    assert any(record["label"] == "project-concept-routing-answer" for record in audit["records"])
