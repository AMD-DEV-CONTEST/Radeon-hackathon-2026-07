"""Prepare a versioned private retrieval manifest outside the repository.

The source manifest may contain private paths. This script preserves those labels
without printing them and adds only generic, synthetic stress queries. The output
must remain outside Git and still requires owner review before it is called gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _category(row_id: str, row: dict[str, Any]) -> str:
    if row.get("should_clarify"):
        return "clarification"
    if row.get("intent") == "sensitive_record_scan":
        return "sensitive_routing"
    number = int(row_id[1:]) if row_id.startswith("q") and row_id[1:].isdigit() else 0
    if 1 <= number <= 7 or number in {25, 26, 27, 37, 39}:
        return "similar_documents"
    if number in {8, 9, 10, 18, 23, 24, 40}:
        return "format_version_role"
    if number in {11, 12, 13, 16, 17, 19, 20, 21, 22, 28, 29, 38}:
        return "cross_language_semantic"
    return "fuzzy_memory"


DERIVED_CASES = (
    ("h041", "q004", "我可能记错文件格式了，只记得里面比较过 FIFO、LRU 和最佳页面置换，找原始报告"),
    ("h042", "q005", "不记得是第几次实验了，内容是 SSTF、电梯调度和移动臂，帮我定位报告"),
    ("h043", "q013", "Locate the old project that combined a policy-value network with MCTS; I cannot remember the filename or format."),
    ("h044", "q016", "找那份介绍墩煌文化和古韵的演示资料，我可能把敦煌写错了"),
    ("h045", "q019", "以前做过 CPU 相关的第二次组成原理实验，格式可能记错了，不要期末资料"),
    ("h046", "q023", "找空白的计算机网络实验范本，不要已经填写过的学生报告"),
    ("h047", "q001", "那份包含线程、进程和文件读写的 OS 大作业可能不是 docx，找提交版"),
    ("h048", "q010", "定位第一次微机接口实验的旧报告；我只记得它是早期 Word 格式"),
)


NO_ANSWER_CASES = (
    ("n001", "找我 2099 年写的量子纠错实验报告，内容是 Shor code 和 surface code"),
    ("n002", "Locate my signed Kubernetes migration runbook for project MARS-GATEWAY-2098"),
    ("n003", "找 2097 年脑部 MRI 肿瘤分割课设报告，应该用了 U-Net"),
    ("n004", "Find my 2096 Blender fluid simulation production notes for project ORBIT-ZETA"),
    ("n005", "找 2095 年 Rust 编译器后端实验报告，项目代号 NEBULA-77"),
    ("n006", "Locate the signed satellite telemetry incident report AURORA-2094"),
    ("n007", "找 2093 年 FPGA 网络加速器课设，项目叫 XILINX-VOID-93"),
    ("n008", "Find my 2092 pharmacology lab report about CRISPR-LANTERN-92"),
    ("n009", "Locate my signed Kubernetes runbook for project MARS-GATEWAY"),
    ("n010", "找代号 NEBULA-OMEGA 的 Rust 编译器后端实验报告"),
    ("n011", "Find the CRISPR-LANTERN pharmacology report"),
    ("n012", "找关于海洋浮标故障的报告，项目编号 OCEAN-VOID-77"),
)


def build(source: Path) -> list[dict[str, Any]]:
    rows = _load(source)
    by_id = {str(row["id"]): row for row in rows}
    prepared: list[dict[str, Any]] = []
    for row in rows:
        prepared.append({
            **row,
            "category": _category(str(row["id"]), row),
            "label_status": "analyst_reviewed_existing",
            "expect_multiple": str(row["id"]) in {"q026", "q039", "q040"},
        })
    for row_id, source_id, query in DERIVED_CASES:
        source_row = by_id[source_id]
        prepared.append({
            "id": row_id,
            "query": query,
            "intent": source_row["intent"],
            "expected_files": list(source_row.get("expected_files", [])),
            "should_clarify": False,
            "category": "derived_hard_paraphrase",
            "label_status": "derived_from_existing_label",
        })
    for row_id, query in NO_ANSWER_CASES:
        prepared.append({
            "id": row_id,
            "query": query,
            "intent": "file_locator",
            "expected_files": [],
            "expect_no_match": True,
            "should_clarify": False,
            "category": "no_answer",
            "label_status": "synthetic_absence_candidate",
        })
    ids = [str(row["id"]) for row in prepared]
    if len(ids) != len(set(ids)):
        raise ValueError("Prepared manifest contains duplicate ids")
    return prepared


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = build(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(json.dumps({"rows": len(rows), "sha256": digest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
