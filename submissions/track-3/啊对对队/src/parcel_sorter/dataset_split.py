"""Deterministic, profile-stratified LeRobot episode split construction."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EpisodeAssignment:
    """Map an original audit episode to its LeRobot episode index and split."""

    dataset_episode_index: int
    original_episode_index: int
    profile_id: str
    split: str


def _stable_key(seed: int, profile_id: str, episode_index: int) -> str:
    payload = f"{seed}:{profile_id}:{episode_index}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"expected an object at {path}:{line_number}")
        records.append(record)
    return records


def _profile_id(record: dict[str, Any]) -> str:
    sample = record.get("sample")
    if not isinstance(sample, dict) or not sample.get("profile_id"):
        raise ValueError("successful audit record is missing sample.profile_id")
    return str(sample["profile_id"])


def _allocate_counts(
    count: int,
    validation_fraction: float,
    heldout_fraction: float,
) -> tuple[int, int, int]:
    """Return train/validation/heldout counts while preserving a train sample."""
    if count < 1:
        raise ValueError("each profile needs at least one successful episode")
    if not 0 <= validation_fraction < 1 or not 0 <= heldout_fraction < 1:
        raise ValueError("split fractions must be in [0, 1)")
    if validation_fraction + heldout_fraction >= 1:
        raise ValueError("validation and held-out fractions must sum to less than 1")

    heldout = math.ceil(count * heldout_fraction) if count >= 3 else 0
    validation = math.ceil(count * validation_fraction) if count >= 3 else 0
    while count - heldout - validation < 1:
        if validation > 0:
            validation -= 1
        elif heldout > 0:
            heldout -= 1
        else:
            raise ValueError("split fractions leave no training episode")
    return count - heldout - validation, validation, heldout


def build_split_manifest(
    *,
    audit_manifest: str | Path,
    dataset_info: str | Path,
    collection_summary: str | Path,
    output: str | Path,
    seed: int = 20260725,
    validation_fraction: float = 0.10,
    heldout_fraction: float = 0.20,
) -> dict[str, Any]:
    """Build and persist a deterministic split from a completed collection.

    LeRobot stores successful episodes with compact indices (0..N-1), while the
    audit manifest stores the original deterministic episode IDs. Successful
    audit records are therefore paired with LeRobot indices in append order;
    the completed collection summary and metadata counts are checked first.
    """
    audit_path = Path(audit_manifest)
    info_path = Path(dataset_info)
    summary_path = Path(collection_summary)
    output_path = Path(output)
    if not summary_path.is_file():
        raise ValueError(f"collection is incomplete; summary is missing: {summary_path}")

    info = json.loads(info_path.read_text(encoding="utf-8"))
    total_episodes = int(info.get("total_episodes", -1))
    if total_episodes < 1:
        raise ValueError("dataset metadata must contain a positive total_episodes")
    if int(info.get("total_tasks", 1)) != 1:
        raise ValueError("split manifest schema v1 requires a single-task dataset")

    audit_records = _read_jsonl(audit_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_episodes = summary.get("episodes")
    if not isinstance(summary_episodes, list) or len(summary_episodes) != len(audit_records):
        raise ValueError("collection summary and audit manifest episode counts do not match")
    summary_ids = [int(record["episode_index"]) for record in summary_episodes]
    audit_ids = [int(record["episode_index"]) for record in audit_records]
    if summary_ids != audit_ids:
        raise ValueError("collection summary and audit manifest episode order do not match")
    successful = [record for record in audit_records if bool(record.get("success"))]
    if len(successful) != total_episodes:
        raise ValueError(
            "successful audit count does not match LeRobot metadata: "
            f"{len(successful)} != {total_episodes}"
        )

    original_ids = [int(record["episode_index"]) for record in successful]
    if len(original_ids) != len(set(original_ids)):
        raise ValueError("successful audit manifest contains duplicate episode IDs")

    grouped: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for dataset_index, (record, original_id) in enumerate(zip(successful, original_ids)):
        grouped[_profile_id(record)].append((dataset_index, original_id))

    assignment_by_dataset: dict[int, EpisodeAssignment] = {}
    profile_counts: dict[str, dict[str, int]] = {}
    for profile_id, records in sorted(grouped.items()):
        ordered = sorted(
            records,
            key=lambda item: _stable_key(seed, profile_id, item[1]),
        )
        train_count, validation_count, heldout_count = _allocate_counts(
            len(ordered), validation_fraction, heldout_fraction
        )
        profile_counts[profile_id] = {
            "total": len(ordered),
            "train": train_count,
            "validation": validation_count,
            "heldout": heldout_count,
        }
        for offset, (dataset_index, original_id) in enumerate(ordered):
            split = (
                "train"
                if offset < train_count
                else "validation"
                if offset < train_count + validation_count
                else "heldout"
            )
            assignment_by_dataset[dataset_index] = EpisodeAssignment(
                dataset_episode_index=dataset_index,
                original_episode_index=original_id,
                profile_id=profile_id,
                split=split,
            )

    assignments = [asdict(assignment_by_dataset[index]) for index in sorted(assignment_by_dataset)]
    train = sorted(item["dataset_episode_index"] for item in assignments if item["split"] == "train")
    validation = sorted(
        item["dataset_episode_index"] for item in assignments if item["split"] == "validation"
    )
    heldout = sorted(item["dataset_episode_index"] for item in assignments if item["split"] == "heldout")
    train_and_validation = train + validation
    eval_split = len(validation) / len(train_and_validation) if validation else 0.0

    payload: dict[str, Any] = {
        "schema_version": 1,
        "seed": seed,
        "source": {
            "audit_manifest": str(audit_path),
            "dataset_info": str(info_path),
            "collection_summary": str(summary_path),
        },
        "fractions": {
            "validation": validation_fraction,
            "heldout": heldout_fraction,
        },
        "counts": {
            "total": len(assignments),
            "train": len(train),
            "validation": len(validation),
            "heldout": len(heldout),
        },
        "profile_counts": profile_counts,
        "lerobot": {
            "episodes": train_and_validation,
            "eval_split": eval_split,
            "heldout_episodes": heldout,
        },
        "assignments": assignments,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_split_manifest(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    lerobot = payload.get("lerobot")
    if not isinstance(lerobot, dict) or not isinstance(lerobot.get("episodes"), list):
        raise ValueError("invalid split manifest: missing lerobot.episodes")
    if not isinstance(lerobot.get("eval_split"), (float, int)):
        raise ValueError("invalid split manifest: missing lerobot.eval_split")
    episodes = lerobot["episodes"]
    if not episodes or any(not isinstance(value, int) or value < 0 for value in episodes):
        raise ValueError("invalid split manifest: episodes must be non-negative integers")
    if len(episodes) != len(set(episodes)):
        raise ValueError("invalid split manifest: duplicate LeRobot episode indices")
    eval_split = float(lerobot["eval_split"])
    if not 0 <= eval_split < 1:
        raise ValueError("invalid split manifest: eval_split must be in [0, 1)")
    heldout = lerobot.get("heldout_episodes", [])
    if set(episodes) & set(heldout):
        raise ValueError("invalid split manifest: held-out episodes leak into training")
    return payload


def lerobot_episode_argument(path: str | Path) -> str:
    payload = load_split_manifest(path)
    return json.dumps(payload["lerobot"]["episodes"], separators=(",", ":"))


def lerobot_eval_split(path: str | Path) -> str:
    payload = load_split_manifest(path)
    return format(float(payload["lerobot"]["eval_split"]), ".12g")
