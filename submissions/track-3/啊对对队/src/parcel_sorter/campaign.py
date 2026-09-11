"""Versioned experiment contracts and category-level evaluation summaries.

The campaign file is deliberately independent of Genesis and LeRobot.  It can
therefore be validated before a remote GPU run and used as the source of truth
for every later training or closed-loop comparison.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Iterable


SCHEMA_VERSION = 1
PENDING_HASH = "PENDING"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MODALITIES = {"rgb", "rgb-d", "state", "rgb-state", "rgb-d-state"}
_ALLOWED_KINDS = {"expert", "policy", "vla", "controller"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_campaign(path: Path) -> dict[str, Any]:
    """Load and validate a campaign TOML file."""
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    validate_campaign(payload)
    return payload


def validate_campaign(payload: dict[str, Any]) -> None:
    """Reject campaigns that could produce incomparable or unsafe evidence."""
    if not isinstance(payload, dict):
        raise ValueError("campaign must be a TOML table")
    metadata = payload.get("metadata")
    platform = payload.get("platform")
    task = payload.get("task")
    dataset = payload.get("dataset")
    evaluation = payload.get("evaluation")
    experiments = payload.get("experiments")
    if not all(isinstance(item, dict) for item in (metadata, platform, task, dataset, evaluation)):
        raise ValueError("campaign requires metadata, platform, task, dataset, and evaluation tables")
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported campaign schema_version: {metadata.get('schema_version')!r}")
    if not str(metadata.get("campaign_id", "")).strip():
        raise ValueError("campaign_id is required")
    if platform.get("backend") != "rocm" or platform.get("device") != "cuda:0":
        raise ValueError("campaign must use the ROCm backend exposed as cuda:0")
    if platform.get("single_gpu") is not True:
        raise ValueError("campaign must explicitly require one GPU")
    force_limit = float(task.get("max_contact_force_n", 0.0))
    if force_limit != 35.0:
        raise ValueError("the campaign safety limit must remain exactly 35.0 N")
    if int(task.get("control_hz", 0)) < 1:
        raise ValueError("task.control_hz must be positive")
    if dataset.get("sampling_seed") is None or dataset.get("randomization_seed") is None:
        raise ValueError("dataset sampling_seed and randomization_seed are required")
    artifact_hash = str(dataset.get("catalog_sha256", ""))
    if not _SHA256_RE.fullmatch(artifact_hash):
        raise ValueError("dataset.catalog_sha256 must be a lowercase SHA-256 hash")

    episode_ids = evaluation.get("episode_ids")
    if not isinstance(episode_ids, list) or not episode_ids:
        raise ValueError("evaluation.episode_ids must be a non-empty explicit list")
    if any(not isinstance(index, int) or index < 0 for index in episode_ids):
        raise ValueError("evaluation.episode_ids must contain non-negative integers")
    if len(set(episode_ids)) != len(episode_ids):
        raise ValueError("evaluation.episode_ids must be unique")
    if evaluation.get("split") not in {"heldout", "fixed_regression", "validation"}:
        raise ValueError("evaluation.split must identify a fixed evaluation purpose")
    profile_ids = evaluation.get("profile_ids")
    local_episode_ids = evaluation.get("local_episode_ids")
    if profile_ids is not None or local_episode_ids is not None:
        if (
            not isinstance(profile_ids, list)
            or not profile_ids
            or any(
                not isinstance(profile_id, str) or not profile_id
                for profile_id in profile_ids
            )
            or len(set(profile_ids)) != len(profile_ids)
        ):
            raise ValueError("evaluation.profile_ids must contain unique non-empty strings")
        if (
            not isinstance(local_episode_ids, list)
            or not local_episode_ids
            or any(not isinstance(index, int) or index < 0 for index in local_episode_ids)
            or len(set(local_episode_ids)) != len(local_episode_ids)
        ):
            raise ValueError("evaluation.local_episode_ids must contain unique non-negative integers")
        if len(episode_ids) != len(profile_ids) * len(local_episode_ids):
            raise ValueError(
                "evaluation.episode_ids must cover every profile/local episode pair"
            )

    if not isinstance(experiments, list) or not experiments:
        raise ValueError("campaign must declare at least one experiment")
    ids: set[str] = set()
    for experiment in experiments:
        if not isinstance(experiment, dict):
            raise ValueError("each experiment must be a table")
        experiment_id = str(experiment.get("id", ""))
        if not experiment_id or experiment_id in ids:
            raise ValueError("experiment ids must be non-empty and unique")
        ids.add(experiment_id)
        if experiment.get("kind") not in _ALLOWED_KINDS:
            raise ValueError(f"unsupported experiment kind: {experiment.get('kind')!r}")
        modality = str(experiment.get("modality", ""))
        if modality not in _ALLOWED_MODALITIES:
            raise ValueError(f"unsupported experiment modality: {modality!r}")
        seeds = experiment.get("seeds")
        if not isinstance(seeds, list) or not seeds or any(not isinstance(seed, int) for seed in seeds):
            raise ValueError(f"{experiment_id} must declare integer seeds")
        if len(set(seeds)) != len(seeds):
            raise ValueError(f"{experiment_id} seeds must be unique")
        steps = int(experiment.get("training_steps", 0))
        if steps < 0:
            raise ValueError(f"{experiment_id}.training_steps cannot be negative")
        if experiment.get("train_on_radeon") is not True or experiment.get("infer_on_radeon") is not True:
            raise ValueError(f"{experiment_id} must run training and inference on Radeon")
        license_name = str(experiment.get("license", "")).strip()
        if not license_name or experiment.get("open_source") is not True:
            raise ValueError(f"{experiment_id} must declare an open-source license")
        acceptance = experiment.get("acceptance")
        if not isinstance(acceptance, dict):
            raise ValueError(f"{experiment_id} must declare acceptance gates")
        for key in ("success_rate_min", "force_abort_rate_max", "drop_rate_max", "throughput_ratio_min"):
            value = float(acceptance.get(key, -1.0))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{experiment_id}.acceptance.{key} must be in [0, 1]")


def catalog_profile_metadata(path: Path) -> dict[str, dict[str, str]]:
    """Read only the profile labels needed for aggregate reporting."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    profiles = raw.get("parcel_profiles", [])
    if not isinstance(profiles, list):
        raise ValueError("catalog parcel_profiles must be an array of tables")
    metadata: dict[str, dict[str, str]] = {}
    for profile in profiles:
        if not isinstance(profile, dict) or not profile.get("profile_id"):
            raise ValueError("catalog profile is missing profile_id")
        profile_id = str(profile["profile_id"])
        metadata[profile_id] = {
            "shape": str(profile.get("shape", "unknown")),
            "orientation_mode": str(profile.get("orientation_mode", "unknown")),
            "handling_class": str(profile.get("handling_class", "unknown")),
        }
    return metadata


def _shape_family(sample: dict[str, Any], profile: dict[str, str] | None) -> str:
    shape = str(sample.get("shape") or (profile or {}).get("shape", "unknown"))
    orientation = str(sample.get("orientation_mode") or (profile or {}).get("orientation_mode", ""))
    if shape == "box":
        return "box"
    if shape == "cylinder" and orientation == "upright":
        return "upright_cylinder"
    if shape == "cylinder" and orientation == "horizontal":
        return "horizontal_cylinder"
    return f"{shape}:{orientation}" if orientation else shape


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def aggregate_by_category(
    episodes: Iterable[dict[str, Any]],
    profile_metadata: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Aggregate closed-loop results by physical shape and handling class.

    The function accepts the existing JSON episode schema and intentionally
    keeps category counts visible, so a strong aggregate cannot hide a failed
    cylinder or an unsupported end-effector class.
    """
    profile_metadata = profile_metadata or {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        if not isinstance(episode, dict):
            raise ValueError("episode records must be objects")
        sample = episode.get("sample")
        result = episode.get("result")
        if not isinstance(sample, dict) or not isinstance(result, dict):
            raise ValueError("episode must contain sample and result objects")
        profile = profile_metadata.get(str(sample.get("profile_id")))
        family = _shape_family(sample, profile)
        handling = str(sample.get("handling_class") or (profile or {}).get("handling_class", "unknown"))
        groups[(family, handling)].append(episode)

    rows: dict[str, Any] = {}
    for (family, handling), records in sorted(groups.items()):
        attempts = len(records)
        successes = sum(bool(record["result"].get("success")) for record in records)
        drops = sum(bool(record["result"].get("dropped")) for record in records)
        force_aborts = sum(
            float(record["result"].get("max_contact_force_n", 0.0)) > 35.0
            for record in records
        )
        key = f"{family}|{handling}"
        rows[key] = {
            "shape_family": family,
            "handling_class": handling,
            "attempts": attempts,
            "successes": successes,
            "success_rate": successes / attempts,
            "drop_rate": drops / attempts,
            "force_abort_rate": force_aborts / attempts,
            "mean_max_contact_force_n": _mean(
                float(record["result"].get("max_contact_force_n", 0.0)) for record in records
            ),
        }
    return {"schema_version": 1, "groups": rows}


def campaign_fingerprint(payload: dict[str, Any]) -> str:
    """Return a stable fingerprint for logs and evidence manifests."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
