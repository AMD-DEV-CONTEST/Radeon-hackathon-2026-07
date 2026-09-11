from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from typing import Iterable, Mapping


PROFILE_DISPLAY_NAMES = {
    "book_box": "book box",
    "electronics_box": "electronics box",
    "flat_mailer": "flat mailer",
    "large_narrow_carton": "large narrow carton",
    "long_carton": "long carton",
    "mailing_tube": "mailing tube",
    "medium_carton": "medium carton",
    "micro_box": "micro box",
    "near_limit_box": "near-limit box",
    "shoe_box_proxy": "shoe-box parcel",
    "small_carton": "small carton",
    "upright_canister": "upright canister",
}


def build_conditioned_task(profile_id: str, destination: str) -> str:
    if profile_id not in PROFILE_DISPLAY_NAMES:
        raise ValueError(f"unsupported parcel profile: {profile_id}")
    if destination not in {"left", "right"}:
        raise ValueError(f"unsupported destination: {destination}")
    return (
        f"Pick the {PROFILE_DISPLAY_NAMES[profile_id]} and place it in the "
        f"{destination} sorting bin."
    )


@dataclass(frozen=True)
class BalancedSourceEpisode:
    source_episode_index: int
    profile_id: str
    repeat_ordinal: int


def _stable_key(seed: int, profile_id: str, episode_index: int) -> str:
    payload = f"{seed}:{profile_id}:{episode_index}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def select_balanced_train_episodes(
    assignments: Iterable[Mapping[str, object]],
    *,
    target_per_profile: int,
    max_repeats: int,
    seed: int,
) -> list[BalancedSourceEpisode]:
    if target_per_profile < 1:
        raise ValueError("target_per_profile must be positive")
    if max_repeats < 1:
        raise ValueError("max_repeats must be positive")

    grouped: dict[str, list[int]] = defaultdict(list)
    for assignment in assignments:
        if assignment.get("split") != "train":
            continue
        profile_id = str(assignment["profile_id"])
        grouped[profile_id].append(int(assignment["dataset_episode_index"]))

    selected: list[BalancedSourceEpisode] = []
    for profile_id, episode_indices in sorted(grouped.items()):
        ordered = sorted(
            episode_indices,
            key=lambda episode_index: _stable_key(seed, profile_id, episode_index),
        )
        target = min(target_per_profile, len(ordered) * max_repeats)
        profile_selection: list[BalancedSourceEpisode] = []
        for repeat_ordinal in range(max_repeats):
            for episode_index in ordered:
                if len(profile_selection) >= target:
                    break
                profile_selection.append(
                    BalancedSourceEpisode(
                        source_episode_index=episode_index,
                        profile_id=profile_id,
                        repeat_ordinal=repeat_ordinal,
                    )
                )
            if len(profile_selection) >= target:
                break
        selected.extend(profile_selection)
    return selected
