# -*- coding: utf-8 -*-
"""Fail closed when an SFT split contains non-Chinese or unaudited videos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


AUDIT_SCHEMA = "licensed-video-transcript-review-queue-v1"


class LanguageGateError(RuntimeError):
    """The training split is not covered by a complete language audit."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LanguageGateError(f"无法读取语言审计文件 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LanguageGateError("语言审计文件根节点必须是对象。")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise LanguageGateError(
                        f"{path}:{line_number} 的训练记录必须是对象。"
                    )
                rows.append(value)
    except LanguageGateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LanguageGateError(f"无法读取训练集 {path}: {exc}") from exc
    if not rows:
        raise LanguageGateError(f"训练集为空：{path}")
    return rows


def validate_audit(
    audit: dict[str, Any], expected_count: int
) -> tuple[set[str], set[str]]:
    if audit.get("schemaVersion") != AUDIT_SCHEMA:
        raise LanguageGateError("语言审计 schema 不受支持。")
    if audit.get("partial") is not False:
        raise LanguageGateError("语言审计仍是 partial，拒绝启动训练。")
    if audit.get("trainingEligible") is not False:
        raise LanguageGateError("语言审计越过了 machine-candidate 信任边界。")
    if audit.get("requiresHumanReview") is not True:
        raise LanguageGateError("语言审计缺少人工审核边界。")
    records = audit.get("records")
    if not isinstance(records, list) or len(records) != expected_count:
        raise LanguageGateError(
            f"语言审计必须恰好覆盖 {expected_count} 个视频。"
        )
    if audit.get("recordCount") != len(records):
        raise LanguageGateError("语言审计 recordCount 与 records 不一致。")

    eligible: set[str] = set()
    excluded: set[str] = set()
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise LanguageGateError("语言审计包含非对象记录。")
        video_id = str(record.get("videoId") or "")
        if not video_id or video_id in seen:
            raise LanguageGateError(f"语言审计 videoId 缺失或重复：{video_id!r}")
        seen.add(video_id)
        if record.get("languageEligible") is True:
            if record.get("recommendedAction") == "exclude_non_chinese":
                raise LanguageGateError(f"{video_id} 的语言结论互相矛盾。")
            eligible.add(video_id)
        else:
            if record.get("recommendedAction") != "exclude_non_chinese":
                raise LanguageGateError(f"{video_id} 未明确标记排除非中文。")
            excluded.add(video_id)

    declared = audit.get("excludedNonChineseVideoIds")
    if not isinstance(declared, list) or set(map(str, declared)) != excluded:
        raise LanguageGateError("excludedNonChineseVideoIds 与逐条语言结论不一致。")
    return eligible, excluded


def validate_split(
    rows: list[dict[str, Any]], eligible: set[str], label: str
) -> set[str]:
    used: set[str] = set()
    for index, row in enumerate(rows, 1):
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            raise LanguageGateError(f"{label} 第 {index} 条缺少 metadata。")
        video_id = str(metadata.get("videoId") or "")
        if not video_id:
            raise LanguageGateError(f"{label} 第 {index} 条缺少 videoId。")
        if video_id not in eligible:
            raise LanguageGateError(
                f"{label} 包含非中文或未完成语言审计的视频：{video_id}"
            )
        used.add(video_id)
    return used


def validate_files(
    *, audit_path: Path, train_path: Path, eval_path: Path, expected_count: int
) -> dict[str, Any]:
    eligible, excluded = validate_audit(read_json(audit_path), expected_count)
    train_ids = validate_split(read_jsonl(train_path), eligible, "训练集")
    eval_ids = validate_split(read_jsonl(eval_path), eligible, "评估集")
    if train_ids & eval_ids:
        overlap = sorted(train_ids & eval_ids)
        raise LanguageGateError(f"训练/评估视频未隔离：{overlap[:5]}")
    return {
        "validated": True,
        "languageGate": "complete_chinese_only_v1",
        "auditedVideos": expected_count,
        "eligibleChineseVideos": len(eligible),
        "excludedNonChineseVideos": len(excluded),
        "trainVideos": len(train_ids),
        "evalVideos": len(eval_ids),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=200)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        report = validate_files(
            audit_path=args.audit.resolve(),
            train_path=args.train.resolve(),
            eval_path=args.eval.resolve(),
            expected_count=args.expected_count,
        )
    except LanguageGateError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
