"""Conservative, auditable planning for a new balanced expert-data shard."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .config import ParcelProfileConfig
from .episode_plan import CollectionRequest
from .metrics import wilson_interval


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProfileHistory:
    """Observed expert outcomes used only to estimate a fresh collection budget."""

    profile_id: str
    attempted: int
    successes: int

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempted if self.attempted else 0.0

    @property
    def success_rate_ci95(self) -> tuple[float, float]:
        return wilson_interval(self.successes, self.attempted)


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
    if not records:
        raise ValueError(f"audit manifest has no episode records: {path}")
    return records


def file_sha256(path: str | Path) -> str:
    """Return a content hash for a plan input that must remain immutable."""
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _history_by_profile(
    records: list[dict[str, Any]],
    training_profile_ids: tuple[str, ...],
) -> dict[str, ProfileHistory]:
    attempts: Counter[str] = Counter()
    successes: Counter[str] = Counter()
    training_set = set(training_profile_ids)
    for record in records:
        sample = record.get("sample")
        if not isinstance(sample, dict) or not sample.get("profile_id"):
            raise ValueError("audit record is missing sample.profile_id")
        profile_id = str(sample["profile_id"])
        if profile_id not in training_set:
            raise ValueError(
                "audit record profile is absent from the current training catalog: "
                f"{profile_id}"
            )
        success = record.get("success")
        if not isinstance(success, bool):
            raise ValueError("audit record success must be a boolean")
        attempts[profile_id] += 1
        if success:
            successes[profile_id] += 1
    return {
        profile_id: ProfileHistory(
            profile_id=profile_id,
            attempted=attempts[profile_id],
            successes=successes[profile_id],
        )
        for profile_id in training_profile_ids
    }


def _validate_parameters(
    *,
    target_successes_per_profile: int,
    planning_rate_floor: float,
    oversampling_factor: float,
    readiness_success_rate_lower_bound: float,
    start_episode: int,
) -> None:
    if target_successes_per_profile < 1:
        raise ValueError("target_successes_per_profile must be positive")
    if not 0 < planning_rate_floor <= 1:
        raise ValueError("planning_rate_floor must be in (0, 1]")
    if oversampling_factor < 1:
        raise ValueError("oversampling_factor must be at least 1")
    if not 0 <= readiness_success_rate_lower_bound <= 1:
        raise ValueError("readiness_success_rate_lower_bound must be in [0, 1]")
    if start_episode < 0:
        raise ValueError("start_episode cannot be negative")


def build_balanced_collection_plan(
    *,
    profiles: tuple[ParcelProfileConfig, ...],
    audit_manifest: str | Path,
    config_path: str | Path,
    target_successes_per_profile: int = 30,
    planning_rate_floor: float = 0.10,
    oversampling_factor: float = 1.25,
    readiness_success_rate_lower_bound: float = 0.35,
    start_episode: int = 0,
) -> dict[str, Any]:
    """Create a plan for a new, independently balanced RGB-D collection.

    Historical data estimates effort only. It is deliberately not credited toward
    the fresh per-profile target because the current LeRobot writer cannot append
    into a completed dataset without changing episode ordering and provenance.
    """
    _validate_parameters(
        target_successes_per_profile=target_successes_per_profile,
        planning_rate_floor=planning_rate_floor,
        oversampling_factor=oversampling_factor,
        readiness_success_rate_lower_bound=readiness_success_rate_lower_bound,
        start_episode=start_episode,
    )
    audit_path = Path(audit_manifest)
    records = _read_jsonl(audit_path)
    training_profiles = tuple(profile for profile in profiles if not profile.evaluation_only)
    if not training_profiles:
        raise ValueError("a balanced collection plan requires training profiles")
    training_ids = tuple(profile.profile_id for profile in training_profiles)
    history_by_profile = _history_by_profile(records, training_ids)

    entries: list[dict[str, Any]] = []
    for profile_id in training_ids:
        history = history_by_profile[profile_id]
        ci_low, ci_high = history.success_rate_ci95
        planning_rate = max(planning_rate_floor, ci_low)
        requested_episodes = math.ceil(
            target_successes_per_profile / planning_rate * oversampling_factor
        )
        ready = ci_low >= readiness_success_rate_lower_bound
        entries.append(
            {
                "profile_id": profile_id,
                "history": {
                    **asdict(history),
                    "observed_success_rate": history.success_rate,
                    "wilson_success_rate_ci95_low": ci_low,
                    "wilson_success_rate_ci95_high": ci_high,
                },
                "planning_success_rate": planning_rate,
                "target_successes_in_new_dataset": target_successes_per_profile,
                "requested_episodes": requested_episodes,
                "start_episode": start_episode,
                "status": "ready" if ready else "requires_expert_diagnostic",
                "status_reason": (
                    "Wilson lower confidence bound meets the collection readiness gate."
                    if ready
                    else (
                        "Wilson lower confidence bound is below the collection readiness gate; "
                        "improve or diagnose expert control before bulk collection."
                    )
                ),
            }
        )

    blocked_profiles = [
        entry["profile_id"]
        for entry in entries
        if entry["status"] != "ready"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "new independently balanced RGB-D expert-data collection",
        "audit_source": {
            "path": str(audit_path),
            "sha256": file_sha256(audit_path),
            "records": len(records),
        },
        "catalog": {
            "config_path": str(config_path),
            "config_sha256": file_sha256(config_path),
            "training_profile_ids": list(training_ids),
        },
        "parameters": {
            "target_successes_per_profile": target_successes_per_profile,
            "planning_rate_floor": planning_rate_floor,
            "oversampling_factor": oversampling_factor,
            "readiness_success_rate_lower_bound": readiness_success_rate_lower_bound,
            "start_episode": start_episode,
        },
        "entries": entries,
        "summary": {
            "training_profiles": len(entries),
            "target_successes_in_new_dataset": target_successes_per_profile * len(entries),
            "requested_episodes": sum(int(entry["requested_episodes"]) for entry in entries),
            "blocked_profiles": blocked_profiles,
            "ready_for_full_collection": not blocked_profiles,
        },
    }


def load_collection_requests(
    path: str | Path,
    *,
    allow_unready: bool = False,
    expected_training_profile_ids: tuple[str, ...] | None = None,
    expected_config_path: str | Path | None = None,
) -> tuple[CollectionRequest, ...]:
    """Load a frozen plan and reject bulk collection with unresolved hard profiles."""
    plan_path = Path(path)
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid collection plan JSON: {plan_path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported collection plan schema: {plan_path}")
    catalog = payload.get("catalog")
    if expected_training_profile_ids is not None:
        if not isinstance(catalog, dict):
            raise ValueError("collection plan is missing its catalog contract")
        planned_ids = catalog.get("training_profile_ids")
        if planned_ids != list(expected_training_profile_ids):
            raise ValueError("collection plan training catalog does not match the active config")
    if expected_config_path is not None:
        if not isinstance(catalog, dict) or not isinstance(catalog.get("config_sha256"), str):
            raise ValueError("collection plan is missing its configuration fingerprint")
        if catalog["config_sha256"] != file_sha256(expected_config_path):
            raise ValueError("collection plan configuration fingerprint does not match the active config")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("collection plan must contain a non-empty entries array")

    blocked: list[str] = []
    requests: list[CollectionRequest] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("collection plan entries must be objects")
        profile_id = entry.get("profile_id")
        requested_episodes = entry.get("requested_episodes")
        start_episode = entry.get("start_episode")
        if (
            not isinstance(profile_id, str)
            or not isinstance(requested_episodes, int)
            or isinstance(requested_episodes, bool)
            or not isinstance(start_episode, int)
            or isinstance(start_episode, bool)
        ):
            raise ValueError("collection plan entry has invalid request fields")
        try:
            request = CollectionRequest(
                profile_id=profile_id,
                episodes=requested_episodes,
                start_episode=start_episode,
            )
        except ValueError as exc:
            raise ValueError("collection plan entry has invalid request fields") from exc
        request.validate()
        if entry.get("status") != "ready":
            blocked.append(request.profile_id)
        requests.append(request)
    request_ids = [request.profile_id for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("collection plan profile ids must be unique")
    if blocked and not allow_unready:
        raise ValueError(
            "collection plan contains profiles that require expert diagnostics: "
            f"{', '.join(blocked)}. Regenerate the plan after improvement, or pass "
            "--allow-unready-collection only for an explicitly labeled diagnostic run."
        )
    return tuple(requests)
