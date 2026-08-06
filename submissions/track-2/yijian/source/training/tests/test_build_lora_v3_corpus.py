# -*- coding: utf-8 -*-

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import build_lora_v3_corpus as corpus  # noqa: E402


# This oracle is intentionally owned by the test rather than imported from the
# production builder.  It covers Chinese-adjacent coordinates and excludes
# alphanumeric SHA/id fragments.
COORDINATE_ORACLE = re.compile(
    r"(?<![A-Za-z0-9])([A-HJ-T](?:1[0-9]|[1-9]))(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _messages(task: str, case_index: int, source: str) -> list[dict]:
    if task == "planner":
        return [
            {"role": "system", "content": "生成合法工具计划"},
            {"role": "user", "content": f"任务{case_index}"},
            {"role": "assistant", "content": '{"steps":["rules","katago"]}'},
        ]
    if task == "memory_privacy":
        return [
            {"role": "system", "content": "记忆默认关闭"},
            {"role": "user", "content": f"不要保存原文{case_index}"},
            {"role": "assistant", "content": '{"write":false}'},
        ]
    actual = "B2" if case_index == 0 else "J10"
    best = "B2" if case_index == 0 else "Q16"
    evidence = {
        "sourceType": source,
        "board": {
            "actualMove": actual,
            "bestMove": best,
            "turn": case_index + 1,
        },
        "katago": {
            "bestMove": best,
            "candidates": [
                {"move": best, "pv": [best, "H10", "K9"]},
                {"move": actual, "pv": [actual, "L10"]},
            ],
        },
        "rules": {"actualMove": actual, "legal": True},
        "questionTarget": "actual",
        "questionTargetMove": actual,
        "evidenceRef": "fd646ec034f9:24278858e86e:55a00b640d91",
    }
    answer = (
        "白B2与AI首选B2是同一点，仍要区分实战与引擎角色。"
        if case_index == 0
        else "白J10只是尝试，黑H10可收紧网形；K9与L10是后续变化，AI首选Q16。"
    )
    if source == "public_domain":
        assistant = json.dumps({
            "purpose": answer,
            "tradeoff": "证据不足处不外推。",
            "nextFocus": "要继续核对变化吗？",
        }, ensure_ascii=False)
    else:
        assistant = json.dumps({
            "answer": answer,
            "followUps": ["要继续核对变化吗？"],
        }, ensure_ascii=False)
    messages = [
        {"role": "system", "content": "旧协议"},
        {
            "role": "user",
            "content": "证据：" + json.dumps(evidence, ensure_ascii=False) + f"\n问题：白{actual}怎么样？",
        },
        {"role": "assistant", "content": assistant},
    ]
    if task == "followup":
        messages.extend([
            {"role": "user", "content": f"那黑H10的作用呢？"},
            {"role": "assistant", "content": json.dumps({
                "answer": "黑H10用于收紧外围，但不据此断言绝对死亡。",
                "followUps": [],
            }, ensure_ascii=False)},
        ])
    return messages


def _rows() -> list[dict]:
    composition = {
        ("creator_authorized", "answer"): 48,
        ("creator_authorized", "planner"): 48,
        ("creator_authorized", "followup"): 48,
        ("project_original", "answer"): 144,
        ("project_original", "planner"): 104,
        ("project_original", "followup"): 96,
        ("project_original", "memory_privacy"): 72,
        ("public_domain", "answer"): 96,
        ("public_domain", "planner"): 64,
    }
    case_mod = {
        "creator_authorized": 48,
        "project_original": 96,
        "public_domain": 64,
    }
    rows: list[dict] = []
    per_source_task: dict[tuple[str, str], int] = {}
    for (source, task), count in composition.items():
        for index in range(count):
            case_index = index % case_mod[source]
            per_source_task[(source, task)] = index
            rows.append({
                "messages": _messages(task, index, source),
                "metadata": {
                    "schemaVersion": "yijian-agent-source-case-v1",
                    "sourceCaseId": f"{source}-{case_index:03d}",
                    "sourceType": source,
                    "taskType": task,
                    "questionTarget": ("actual", "best", "comparison")[case_index % 3],
                    "split": "train",
                },
            })
    assert len(rows) == 720
    return rows


def _fixture(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    train = _rows()
    dev = []
    for row in train[:24]:
        value = copy.deepcopy(row)
        value["metadata"]["split"] = "dev"
        dev.append(value)
    _write_jsonl(source / "agent_sft_train.jsonl", train)
    _write_jsonl(source / "agent_sft_dev.jsonl", dev)
    # Deliberately do not create agent_sft_test.jsonl.  A successful build
    # proves that sealed content was not opened.
    (source / "manifest.json").write_text(json.dumps({
        "schemaVersion": "yijian-agent-sft-v1",
        "passed": True,
        "outputs": {
            "agent_sft_train.jsonl": corpus.sha256(source / "agent_sft_train.jsonl"),
            "agent_sft_dev.jsonl": corpus.sha256(source / "agent_sft_dev.jsonl"),
            "agent_sft_test.jsonl": "a" * 64,
        },
    }), encoding="utf-8")
    return source


def test_v3_rebuild_is_coordinate_free_role_aware_and_never_reads_sealed(tmp_path: Path) -> None:
    source = _fixture(tmp_path)
    output = tmp_path / "output"
    manifest = corpus.build(source, output)
    rows = corpus.read_jsonl(output / "agent_sft_train.jsonl")

    assert manifest["schemaVersion"] == "yijian-agent-sft-v3"
    assert manifest["counts"] == {"train": 720, "dev": 24, "sealed": 24}
    assert manifest["sourceCaseCounts"] == {
        "creator_authorized": 48,
        "project_original": 96,
        "public_domain": 64,
    }
    assert manifest["gates"]["sealedTestAccessed"] is False
    assert not (output / "agent_sft_test.jsonl").exists()
    for row in rows:
        for message in row["messages"]:
            assert not COORDINATE_ORACLE.search(message["content"])

    same = next(
        row for row in rows
        if row["metadata"].get("actualBestSamePoint")
        and row["metadata"]["taskType"] == "answer"
        and not row["metadata"].get("augmentationId")
    )
    user = same["messages"][1]["content"]
    assert '"actualMove":"S"' in user
    assert '"bestMove":"J"' in user
    assert '"samePoint":true' in user

    distinct = next(
        row for row in rows
        if row["metadata"]["sourceCaseId"] == "creator_authorized-001"
        and row["metadata"]["taskType"] == "answer"
        and not row["metadata"].get("augmentationId")
    )
    assistant = json.loads(distinct["messages"][-1]["content"])["answer"]
    assert "S" in assistant and "J" in assistant
    assert "变化点甲" in assistant and "变化点乙" in assistant
    assert "fd646ec034f9" in distinct["messages"][1]["content"]


def test_v3_rejects_parent_train_hash_change(tmp_path: Path) -> None:
    source = _fixture(tmp_path)
    train = source / "agent_sft_train.jsonl"
    train.write_text(train.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="parent artifact hash mismatch"):
        corpus.build(source, tmp_path / "output")


def test_coordinate_oracle_catches_chinese_adjacent_but_not_hashes() -> None:
    assert COORDINATE_ORACLE.findall("白J10后黑M9，再看K9") == ["J10", "M9", "K9"]
    assert not COORDINATE_ORACLE.search("fd646ec034f9:24278858e86e:55a00b640d91")
