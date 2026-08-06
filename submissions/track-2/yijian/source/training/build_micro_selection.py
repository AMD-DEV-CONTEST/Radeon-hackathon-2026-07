# -*- coding: utf-8 -*-
"""Build the deterministic eight-row learning-proof set from train only."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable


class SelectionError(ValueError):
    pass


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def stable_pick(
    rows: list[dict[str, Any]], manifest_sha: str, label: str,
    predicate: Callable[[dict[str, Any]], bool], used_cases: set[str],
) -> dict[str, Any]:
    candidates = [
        row for row in rows
        if predicate(row) and str((row.get("metadata") or {}).get("sourceCaseId") or "") not in used_cases
    ]
    if not candidates:
        raise SelectionError(f"no candidate for {label}")
    candidates.sort(key=lambda row: hashlib.sha256(
        f"{manifest_sha}|{label}|{row['metadata']['sourceCaseId']}".encode("utf-8")
    ).hexdigest())
    selected = candidates[0]
    used_cases.add(selected["metadata"]["sourceCaseId"])
    return selected


def build(train_path: Path, parent_manifest_path: Path, dev_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parent = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    if parent.get("schemaVersion") not in {
        "yijian-agent-sft-v1", "yijian-agent-sft-v2", "yijian-agent-sft-v3"
    } or parent.get("passed") is not True:
        raise SelectionError("parent SFT manifest has not passed")
    expected = parent.get("outputs") or {}
    if expected.get(train_path.name) != file_hash(train_path) or expected.get(dev_path.name) != file_hash(dev_path):
        raise SelectionError("parent artifact hash mismatch")
    rows = read_jsonl(train_path)
    if len(rows) != 720 or any((row.get("metadata") or {}).get("split") != "train" for row in rows):
        raise SelectionError("micro selection requires exactly 720 train-only rows")
    manifest_sha = file_hash(parent_manifest_path)
    is_question_first = parent.get("schemaVersion") in {
        "yijian-agent-sft-v2", "yijian-agent-sft-v3"
    }
    used: set[str] = set()
    specs: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("creator-answer-actual", lambda r: r["metadata"].get("sourceType") == "creator_authorized" and r["metadata"].get("taskType") == "answer" and r["metadata"].get("questionTarget") == "actual"),
        ("creator-planner-best", lambda r: r["metadata"].get("sourceType") == "creator_authorized" and r["metadata"].get("taskType") == "planner" and r["metadata"].get("questionTarget") == "best"),
        ("creator-followup-comparison", lambda r: r["metadata"].get("sourceType") == "creator_authorized" and r["metadata"].get("taskType") == "followup" and r["metadata"].get("questionTarget") == "comparison"),
        ("public-planner", lambda r: r["metadata"].get("sourceType") == "public_domain" and r["metadata"].get("taskType") == "planner"),
        (
            "project-concept-routing-answer" if is_question_first else "project-answer",
            lambda r: r["metadata"].get("sourceType") == "project_original"
            and r["metadata"].get("taskType") == "answer"
            and (
                not is_question_first
                or r["metadata"].get("projectOriginalAugmentation")
                in {
                    "conceptual-routing-remediation-v2",
                    "conceptual-routing-remediation-v3",
                }
            ),
        ),
        ("project-followup", lambda r: r["metadata"].get("sourceType") == "project_original" and r["metadata"].get("taskType") == "followup"),
        ("project-memory-a", lambda r: r["metadata"].get("sourceType") == "project_original" and r["metadata"].get("taskType") == "memory_privacy"),
        ("project-memory-b", lambda r: r["metadata"].get("sourceType") == "project_original" and r["metadata"].get("taskType") == "memory_privacy"),
    ]
    selected = [stable_pick(rows, manifest_sha, label, predicate, used) for label, predicate in specs]
    task_counts = Counter(row["metadata"]["taskType"] for row in selected)
    source_counts = Counter(row["metadata"]["sourceType"] for row in selected)
    if task_counts != {"answer": 2, "planner": 2, "followup": 2, "memory_privacy": 2}:
        raise SelectionError(f"micro task coverage mismatch: {task_counts}")
    if source_counts != {"creator_authorized": 3, "project_original": 4, "public_domain": 1}:
        raise SelectionError(f"micro source coverage mismatch: {source_counts}")
    return selected, {
        "schemaVersion": "yijian-micro-selection-v1",
        "passed": True,
        "parentManifestSha256": manifest_sha,
        "parentTrainSha256": file_hash(train_path),
        "devSha256": file_hash(dev_path),
        "sealedTestAccessed": False,
        "selectionPolicy": (
            "stable sha256; eight distinct source cases; 2 rows per task; "
            "question-first schemas include one conceptual-routing answer"
            if is_question_first
            else "stable sha256; eight distinct source cases; 2 rows per task"
        ),
        "taskCounts": dict(task_counts),
        "sourceCounts": dict(source_counts),
        "records": [
            {
                "label": label,
                "sourceCaseId": row["metadata"]["sourceCaseId"],
                "sourceType": row["metadata"]["sourceType"],
                "taskType": row["metadata"]["taskType"],
                "questionTarget": row["metadata"].get("questionTarget"),
            }
            for (label, _), row in zip(specs, selected)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--dev", type=Path, required=True)
    parser.add_argument("--parent-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    selected, selection = build(args.train.resolve(), args.parent_manifest.resolve(), args.dev.resolve())
    output = args.output_dir.resolve()
    micro_path = output / "micro_train_8.jsonl"
    selection_path = output / "micro-selection.json"
    write_jsonl(micro_path, selected)
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    parent_schema = json.loads(args.parent_manifest.read_text(encoding="utf-8")).get("schemaVersion")
    micro_manifest = {
        "schemaVersion": parent_schema,
        "passed": True,
        "purpose": "eight-sample-thirty-step-learning-proof-only",
        "counts": {"train": 8, "dev": 24},
        "sealedTestAccessed": False,
        "parentManifestSha256": selection["parentManifestSha256"],
        "selectionSha256": file_hash(selection_path),
        "outputs": {
            micro_path.name: file_hash(micro_path),
            args.dev.name: file_hash(args.dev.resolve()),
        },
    }
    if parent_schema == "yijian-agent-sft-v3":
        micro_manifest["artifacts"] = {
            "train": {
                "role": "train", "filename": micro_path.name,
                "sha256": file_hash(micro_path), "rows": 8,
            },
            "dev": {
                "role": "dev", "filename": args.dev.name,
                "sha256": file_hash(args.dev.resolve()), "rows": 24,
            },
            "sealed": {
                "role": "sealed", "sha256": (
                    json.loads(args.parent_manifest.read_text(encoding="utf-8"))
                    .get("artifacts", {}).get("sealed", {}).get("sha256")
                ),
                "rows": 24, "accessed": False,
            },
        }
    manifest_path = output / "micro-manifest.json"
    manifest_path.write_text(json.dumps(micro_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**selection, "microManifestSha256": file_hash(manifest_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
