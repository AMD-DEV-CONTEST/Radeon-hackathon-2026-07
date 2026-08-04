from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from policyseal.domain.enums import Action


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    action: Action
    reason_code: str


def resolve_actions(
    actions: Iterable[Action],
    *,
    provable_intersection: Action | None = None,
) -> ConflictResolution:
    candidates = tuple(actions)
    if not candidates or any(not isinstance(action, Action) for action in candidates):
        return ConflictResolution(Action.REQUIRE_APPROVAL, "invalid_or_missing_action")

    if Action.BLOCK in candidates:
        return ConflictResolution(Action.BLOCK, "block_precedence")
    if Action.REQUIRE_APPROVAL in candidates:
        return ConflictResolution(Action.REQUIRE_APPROVAL, "approval_precedence")

    # Remove reveals no region content, so it is the provable intersection with any transform.
    if Action.REMOVE in candidates:
        return ConflictResolution(Action.REMOVE, "minimum_disclosure_remove")

    transforms = set(candidates) - {Action.KEEP}
    if not transforms:
        return ConflictResolution(Action.KEEP, "keep_only")
    if len(transforms) == 1:
        return ConflictResolution(next(iter(transforms)), "single_transform")
    if provable_intersection in {
        Action.MASK,
        Action.REMOVE,
        Action.FILTER,
        Action.GENERALIZE,
    }:
        return ConflictResolution(provable_intersection, "provable_transform_intersection")
    return ConflictResolution(Action.REQUIRE_APPROVAL, "incompatible_transforms")
