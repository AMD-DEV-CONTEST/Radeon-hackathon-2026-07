#!/usr/bin/env python3
"""Publish the checked RadeonVLA-Reflex evaluation-video evidence bundle."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "a3124371940/radeonvla_reflex_evaluation_videos"
FRUITS = ("apple", "banana", "lemon", "orange", "plum")
DESTINATIONS = ("blue_left", "blue_right", "white_left", "white_right")
TASK_IDS = tuple(
    f"{fruit}_{destination}" for fruit in FRUITS for destination in DESTINATIONS
)

FILES = {
    "README.md": PROJECT_ROOT / "artifacts" / "EVALUATION_VIDEO_DATASET_CARD.md",
    "videos/policy_success_20k/banana_white_left_seed53001.mp4": PROJECT_ROOT
    / "website/public/videos/eval-20k-banana-white-left.mp4",
    "videos/policy_success_20k/lemon_blue_right_seed54006.mp4": PROJECT_ROOT
    / "website/public/videos/eval-20k-lemon-blue-right.mp4",
    "videos/policy_success_20k_world/banana_white_left_seed53001.mp4": PROJECT_ROOT
    / "website/public/videos/eval-20k-banana-white-left-world.mp4",
    "videos/policy_success_20k_world/lemon_blue_right_seed54006.mp4": PROJECT_ROOT
    / "website/public/videos/eval-20k-lemon-blue-right-world.mp4",
    "videos/data_collection/apple_blue_left_episode000.mp4": PROJECT_ROOT
    / "website/public/videos/dataset-apple-blue-left.mp4",
    "videos/data_collection/banana_white_right_episode047.mp4": PROJECT_ROOT
    / "website/public/videos/dataset-banana-white-right.mp4",
    "videos/data_collection/plum_white_left_episode158.mp4": PROJECT_ROOT
    / "website/public/videos/dataset-plum-white-left.mp4",
    "videos/walkthrough/radeonvla_reflex_3min.mp4": PROJECT_ROOT
    / "website/public/videos/radeonvla-reflex-3min.mp4",
    "videos/walkthrough/radeonvla_reflex_3min.vtt": PROJECT_ROOT
    / "website/public/videos/radeonvla-reflex-3min.vtt",
    "evidence/formal100/evaluation.json": PROJECT_ROOT / "artifacts/evaluation.json",
    "evidence/formal100/evaluation.csv": PROJECT_ROOT / "artifacts/evaluation.csv",
    "evidence/formal100/evaluation.schema.json": PROJECT_ROOT / "artifacts/evaluation.schema.json",
    "evidence/policy_success_20k/banana/evaluation.json": PROJECT_ROOT
    / "artifacts/evaluation_20k_banana_success.json",
    "evidence/policy_success_20k/banana/evaluation.csv": PROJECT_ROOT
    / "artifacts/evaluation_20k_banana_success.csv",
    "evidence/policy_success_20k/banana/evaluation.summary.md": PROJECT_ROOT
    / "artifacts/evaluation_20k_banana_success.summary.md",
    "evidence/policy_success_20k/lemon/replay_probe.json": PROJECT_ROOT
    / "artifacts/probe_20k_lemon_success.json",
    "evidence/world_success_examples.json": PROJECT_ROOT
    / "artifacts/world_success_examples.json",
}

FILES.update(
    {
        f"videos/task_success_world/{task_id}.mp4": PROJECT_ROOT
        / "website/public/videos/task-success-world"
        / f"{task_id}.mp4"
        for task_id in TASK_IDS
    }
)

DELETE_PATHS = [
    "videos/learned_success/apple_blue_left_seed50020.mp4",
    "videos/learned_success/lemon_blue_right_seed50022.mp4",
    "videos/learned_success/orange_white_right_seed50023.mp4",
    "videos/learned_success/plum_white_left_seed50024.mp4",
    "videos/reflex/interrupt_recovery_apple_seed61000.mp4",
    "videos/reflex/normal_vs_reflex_15s.mp4",
    "evidence/interrupt_recovery/evaluation.json",
    "evidence/interrupt_recovery/evaluation.csv",
    "evidence/interrupt_recovery/evaluation.summary.md",
    "evidence/policy_success_20k/lemon/evaluation.json",
    "evidence/policy_success_20k/lemon/evaluation.csv",
    "evidence/policy_success_20k/lemon/evaluation.summary.md",
]


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main() -> None:
    missing = [str(path) for path in FILES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing release inputs:\n" + "\n".join(missing))

    sums = "".join(f"{digest(path)}  {repo_path}\n" for repo_path, path in sorted(FILES.items()))
    api = HfApi()
    api.create_repo(REPO_ID, repo_type="dataset", private=False, exist_ok=True)
    existing = set(api.list_repo_files(REPO_ID, repo_type="dataset"))
    operations = [
        CommitOperationDelete(path_in_repo=repo_path)
        for repo_path in DELETE_PATHS
        if repo_path in existing
    ] + [
        CommitOperationAdd(path_in_repo=repo_path, path_or_fileobj=path)
        for repo_path, path in FILES.items()
    ]
    operations.append(
        CommitOperationAdd(path_in_repo="SHA256SUMS", path_or_fileobj=io.BytesIO(sums.encode("utf-8")))
    )

    commit = api.create_commit(
        repo_id=REPO_ID,
        repo_type="dataset",
        operations=operations,
        commit_message="Add world-camera success examples for all 20 tasks",
    )
    info = api.repo_info(REPO_ID, repo_type="dataset")
    print(f"repo=https://huggingface.co/datasets/{REPO_ID}")
    print(f"commit={commit.oid}")
    print(f"revision={info.sha}")
    print(f"files={len(api.list_repo_files(REPO_ID, repo_type='dataset', revision=info.sha))}")


if __name__ == "__main__":
    main()
