"""Fail-closed split construction for the verified parcel success dataset."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any


GRASP_MODES = ("top_suction", "side_suction", "cooperative_cradle")
DESIGN_CELLS_PER_MODE = 8
SUCCESSES_PER_MODE = 500
SPLIT_TARGETS_PER_MODE = {
    "train": 400,
    "development": 50,
    "confirmation": 50,
}
FORCE_LIMIT_N = 35.0


@dataclass(frozen=True)
class ParcelSuccessAssignment:
    dataset_episode_index: int
    episode_id: str
    source_identity: str
    grasp_mode: str
    design_cell: str
    split: str


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_key(seed: int, split_group: str, episode_id: str) -> str:
    value = f"{seed}:{split_group}:{episode_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _apportion(counts: dict[str, int], target: int) -> dict[str, int]:
    total = sum(counts.values())
    if total < 1 or not 0 <= target <= total:
        raise ValueError("invalid stratified split target")
    raw = {key: target * count / total for key, count in counts.items()}
    allocated = {key: math.floor(value) for key, value in raw.items()}
    remainder = target - sum(allocated.values())
    order = sorted(
        counts,
        key=lambda key: (-(raw[key] - allocated[key]), key),
    )
    for key in order[:remainder]:
        allocated[key] += 1
    return allocated


def _require_verified_success(result: dict[str, Any]) -> tuple[str, str, str]:
    episode_id = str(result.get("episode_id") or "")
    parameters = result.get("parameters")
    recovery_label = result.get("recovery_label")
    if not episode_id or not isinstance(parameters, dict):
        raise ValueError("successful result is missing episode identity or parameters")
    mode = str(parameters.get("grasp_mode") or "")
    cell = str(parameters.get("design_cell") or "")
    source_identity = str(parameters.get("source_identity") or "")
    valid_cells = {
        f"{mode}-cell-{index:02d}" for index in range(DESIGN_CELLS_PER_MODE)
    }
    if mode not in GRASP_MODES or cell not in valid_cells:
        raise ValueError(f"invalid mode/design-cell contract: {episode_id}")
    if not source_identity:
        raise ValueError(f"missing source identity: {episode_id}")
    if parameters.get("demonstration_provenance") != "deterministic_expert_candidate":
        raise ValueError(f"invalid demonstration provenance: {episode_id}")
    if parameters.get("split") != "collection_candidate":
        raise ValueError(f"unexpected preassigned split: {episode_id}")
    if result.get("return_code") != 0 or result.get("success") is not True:
        raise ValueError(f"non-success entered successful episode order: {episode_id}")
    if result.get("failure_stage") is not None:
        raise ValueError(f"successful result has a failure stage: {episode_id}")
    if result.get("dataset_saved") is not True or int(result.get("frames", 0)) <= 0:
        raise ValueError(f"successful result has no nonempty dataset: {episode_id}")
    if result.get("dataset_storage_format") != "video":
        raise ValueError(f"successful result is not video-backed: {episode_id}")
    if int(result.get("dataset_bytes", 0)) <= 0:
        raise ValueError(f"successful result has no stored bytes: {episode_id}")
    if not isinstance(recovery_label, dict) or recovery_label.get("verified_success") is not True:
        raise ValueError(f"successful result lacks independent verification: {episode_id}")
    for field in ("lift_success", "transport_success", "placed_before_release", "released"):
        if result.get(field) is not True:
            raise ValueError(f"successful result lacks {field}: {episode_id}")
    if result.get("place_force_safety_abort") is not False:
        raise ValueError(f"successful result hit the placement force interlock: {episode_id}")
    force_fields = ["max_suction_force_n", "max_contact_force_n"]
    if mode == "cooperative_cradle":
        force_fields.append("max_cradle_contact_force_n")
    for field in force_fields:
        value = result.get(field)
        if not isinstance(value, (int, float)) or not 0 <= float(value) < FORCE_LIMIT_N:
            raise ValueError(f"successful result violates {field}: {episode_id}")
    return mode, cell, source_identity


def build_mobile_success_split(
    *,
    collection_summary: str | Path,
    dataset_info: str | Path,
    output: str | Path,
    seed: int = 20260729,
) -> dict[str, Any]:
    """Validate 1,500 expert successes and freeze an exact 80/10/10 split."""

    summary_path = Path(collection_summary)
    info_path = Path(dataset_info)
    output_path = Path(output)
    summary = _read_json(summary_path)
    info = _read_json(info_path)
    if summary.get("status") != "passed":
        raise ValueError("collection summary is not in the passed terminal state")
    quota = summary.get("success_quota")
    if not isinstance(quota, dict) or quota.get("complete") is not True:
        raise ValueError("collection success quota is incomplete")
    expected_total = SUCCESSES_PER_MODE * len(GRASP_MODES)
    if int(quota.get("target_successes", -1)) != expected_total:
        raise ValueError("collection success quota does not target 1,500 episodes")
    if int(info.get("total_episodes", -1)) != expected_total:
        raise ValueError("LeRobot metadata does not contain exactly 1,500 episodes")
    if not info.get("video_path"):
        raise ValueError("LeRobot dataset is not video-backed")
    features = info.get("features")
    if not isinstance(features, dict):
        raise ValueError("LeRobot metadata lacks feature definitions")
    visual_features = {
        name: feature
        for name, feature in features.items()
        if name.startswith("observation.images.")
    }
    if len(visual_features) != 6 or any(
        not isinstance(feature, dict) or feature.get("dtype") != "video"
        for feature in visual_features.values()
    ):
        raise ValueError("LeRobot visual features are not six video streams")

    results = summary.get("results")
    successful_order = summary.get("successful_episode_order")
    if not isinstance(results, list) or not isinstance(successful_order, list):
        raise ValueError("collection summary lacks results or successful episode order")
    by_id: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict) or not result.get("episode_id"):
            raise ValueError("collection result is missing episode_id")
        episode_id = str(result["episode_id"])
        if episode_id in by_id:
            raise ValueError(f"duplicate collection episode: {episode_id}")
        by_id[episode_id] = result
    if len(successful_order) != expected_total or len(set(successful_order)) != expected_total:
        raise ValueError("successful episode order is not 1,500 unique episodes")
    filtered_order = [
        str(result["episode_id"])
        for result in results
        if result.get("success") is True
    ]
    if [str(value) for value in successful_order] != filtered_order:
        raise ValueError("successful episode order does not match collection results")

    grouped: dict[str, dict[str, list[ParcelSuccessAssignment]]] = defaultdict(
        lambda: defaultdict(list)
    )
    source_identities: set[str] = set()
    for dataset_index, episode_id_value in enumerate(successful_order):
        episode_id = str(episode_id_value)
        result = by_id.get(episode_id)
        if result is None:
            raise ValueError(f"successful episode is absent from results: {episode_id}")
        mode, cell, source_identity = _require_verified_success(result)
        if source_identity in source_identities:
            raise ValueError(f"duplicate successful source identity: {source_identity}")
        source_identities.add(source_identity)
        grouped[mode][cell].append(
            ParcelSuccessAssignment(
                dataset_episode_index=dataset_index,
                episode_id=episode_id,
                source_identity=source_identity,
                grasp_mode=mode,
                design_cell=cell,
                split="unassigned",
            )
        )

    assigned: list[ParcelSuccessAssignment] = []
    cell_counts: dict[str, dict[str, int]] = {}
    for mode in GRASP_MODES:
        mode_groups = grouped.get(mode, {})
        expected_cells = {f"{mode}-cell-{index:02d}" for index in range(DESIGN_CELLS_PER_MODE)}
        if set(mode_groups) != expected_cells:
            raise ValueError(f"{mode} does not cover all eight design cells")
        counts = {cell: len(records) for cell, records in mode_groups.items()}
        if sum(counts.values()) != SUCCESSES_PER_MODE or set(counts.values()) != {62, 63}:
            raise ValueError(f"{mode} does not match the frozen 500-success cell quota")
        development_counts = _apportion(counts, SPLIT_TARGETS_PER_MODE["development"])
        confirmation_counts = _apportion(counts, SPLIT_TARGETS_PER_MODE["confirmation"])
        for cell in sorted(mode_groups):
            ordered = sorted(
                mode_groups[cell],
                key=lambda item: _stable_key(seed, cell, item.episode_id),
            )
            development_count = development_counts[cell]
            confirmation_count = confirmation_counts[cell]
            train_count = len(ordered) - development_count - confirmation_count
            split_sequence = (
                ["train"] * train_count
                + ["development"] * development_count
                + ["confirmation"] * confirmation_count
            )
            cell_counts[cell] = dict(Counter(split_sequence))
            assigned.extend(
                ParcelSuccessAssignment(
                    dataset_episode_index=item.dataset_episode_index,
                    episode_id=item.episode_id,
                    source_identity=item.source_identity,
                    grasp_mode=item.grasp_mode,
                    design_cell=item.design_cell,
                    split=split_name,
                )
                for item, split_name in zip(ordered, split_sequence)
            )

    assignments = [
        asdict(item)
        for item in sorted(assigned, key=lambda item: item.dataset_episode_index)
    ]
    split_indices = {
        split_name: sorted(
            item["dataset_episode_index"]
            for item in assignments
            if item["split"] == split_name
        )
        for split_name in SPLIT_TARGETS_PER_MODE
    }
    counts = {name: len(indices) for name, indices in split_indices.items()}
    if counts != {"train": 1200, "development": 150, "confirmation": 150}:
        raise AssertionError(f"unexpected split counts: {counts}")
    if set(split_indices["train"]) & set(split_indices["development"]):
        raise AssertionError("train and development splits overlap")
    if (set(split_indices["train"]) | set(split_indices["development"])) & set(
        split_indices["confirmation"]
    ):
        raise AssertionError("confirmation split overlaps model-selection data")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "seed": seed,
        "source": {
            "collection_summary": str(summary_path.resolve()),
            "collection_summary_sha256": _sha256(summary_path),
            "dataset_info": str(info_path.resolve()),
            "dataset_info_sha256": _sha256(info_path),
            "collection_id": summary.get("collection_id"),
            "runtime_contract": summary.get("runtime_contract"),
        },
        "counts": {"total": expected_total, **counts},
        "mode_counts": {
            mode: dict(Counter(item["split"] for item in assignments if item["grasp_mode"] == mode))
            for mode in GRASP_MODES
        },
        "design_cell_counts": cell_counts,
        "sampling_contract": {
            "grasp_mode_probability": {mode: 1 / 3 for mode in GRASP_MODES},
            "design_cell_probability_within_mode": 1 / DESIGN_CELLS_PER_MODE,
            "stage_frame_cap_per_episode": 100,
            "external_replay_probability": 0.0,
        },
        "lerobot": {
            "train_episodes": split_indices["train"],
            "development_episodes": split_indices["development"],
            "confirmation_episodes": split_indices["confirmation"],
        },
        "assignments": assignments,
        "claim_boundary": (
            "All assignments are independent, complete, nonempty deterministic-expert "
            "successes. Confirmation remains untouched until checkpoint and runtime freeze."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
