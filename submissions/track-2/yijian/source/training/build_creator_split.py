# -*- coding: utf-8 -*-
"""Deterministically assign a complete 16x4 creator release to 48/8/8."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import expert_corpus
import gold_review_workflow as workflow


def themes(unit: dict[str, Any]) -> set[str]:
    return {
        expert_corpus.CREATOR_THEME_ALIASES.get(str(value), str(value))
        for value in ((unit.get("pedagogy") or {}).get("competencies") or [])
    } & expert_corpus.REQUIRED_CREATOR_THEMES


def split_stats(groups: dict[str, list[dict]], videos: set[str]) -> tuple[Counter, Counter]:
    target_counts: Counter[str] = Counter()
    theme_counts: Counter[str] = Counter()
    for video in videos:
        for unit in groups[video]:
            target_counts[str((unit.get("board") or {}).get("targetKind") or "")] += 1
            theme_counts.update(themes(unit))
    return target_counts, theme_counts


def build_assignments(
    units: list[dict[str, Any]], *, release_sha256: str,
    new_video_ids: set[str] | None = None,
) -> dict[str, Any]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for unit in units:
        workflow.require(unit.get("trainingEligible") is True, "切分只接受已签发金标")
        video = str((unit.get("source") or {}).get("videoId") or "")
        workflow.require(video, f"{unit.get('id')}: 缺少videoId")
        groups[video].append(unit)
    workflow.require(len(units) == 64, f"必须恰好64条，实际{len(units)}")
    workflow.require(
        len(groups) == 16 and all(len(rows) == 4 for rows in groups.values()),
        "必须恰好16个视频且每个视频4条",
    )
    all_videos = set(groups)
    new_videos = set(new_video_ids or ())
    workflow.require(new_videos <= all_videos, "new-video不在金标release中")
    candidates = []
    for dev_tuple in itertools.combinations(sorted(all_videos), 2):
        dev = set(dev_tuple)
        if new_videos and not dev & new_videos:
            continue
        remaining = all_videos - dev
        for test_tuple in itertools.combinations(sorted(remaining), 2):
            test = set(test_tuple)
            if new_videos and not test & new_videos:
                continue
            train = remaining - test
            train_targets, train_themes = split_stats(groups, train)
            dev_targets, _ = split_stats(groups, dev)
            test_targets, _ = split_stats(groups, test)
            if any(train_targets[name] < 8 for name in ("actual", "best", "comparison")):
                continue
            if any(train_themes[name] < 2 for name in expert_corpus.REQUIRED_CREATOR_THEMES):
                continue
            if sum(value > 0 for value in dev_targets.values()) < 2:
                continue
            if sum(value > 0 for value in test_targets.values()) < 2:
                continue
            key_text = "|".join([
                release_sha256,
                "train=" + ",".join(sorted(train)),
                "dev=" + ",".join(sorted(dev)),
                "test=" + ",".join(sorted(test)),
            ])
            candidates.append((hashlib.sha256(key_text.encode()).hexdigest(), train, dev, test))
    workflow.require(candidates, "没有满足主题与目标配额的12/2/2视频切分")
    _, train, dev, test = min(candidates, key=lambda row: row[0])
    split_by_video = {
        **{video: "train" for video in train},
        **{video: "dev" for video in dev},
        **{video: "test" for video in test},
    }
    assignments = [
        {"unitId": unit["id"], "split": split_by_video[unit["source"]["videoId"]]}
        for unit in sorted(units, key=lambda row: str(row.get("id") or ""))
    ]
    return {
        "schemaVersion": expert_corpus.SPLIT_MANIFEST_SCHEMA,
        "releaseSha256": release_sha256,
        "policy": {
            "unitCounts": {"train": 48, "dev": 8, "test": 8},
            "videoCounts": {"train": 12, "dev": 2, "test": 2},
            "deterministicTieBreak": "sha256(releaseHash+sorted video assignments)",
            "newVideosRequiredInDevAndTest": bool(new_videos),
        },
        "assignments": assignments,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--units", type=Path, required=True)
    parser.add_argument("--new-video", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    units_path = args.units.resolve()
    release_sha = hashlib.sha256(units_path.read_bytes()).hexdigest()
    value = build_assignments(
        workflow.read_jsonl(units_path), release_sha256=release_sha,
        new_video_ids=set(args.new_video),
    )
    workflow.write_json(args.output.resolve(), value)
    print(json.dumps({"assignments": len(value["assignments"]), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
