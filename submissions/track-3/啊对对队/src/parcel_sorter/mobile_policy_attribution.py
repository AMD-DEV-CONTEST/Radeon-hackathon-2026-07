"""Canonical action-authority attribution for mobile VLA rollouts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


HYBRID_VLA_AUTHORITY = "hybrid_expert_reference_plus_vla_residual"
ABSOLUTE_VLA_AUTHORITY = "absolute_vla_action_candidate"
UNKNOWN_VLA_AUTHORITY = "unknown"
PURE_VLA_CONTROL_CLASS = "pure_vla"
SHIELDED_VLA_CONTROL_CLASS = "shielded_vla"
HYBRID_VLA_CONTROL_CLASS = "hybrid_vla"
UNKNOWN_VLA_CONTROL_CLASS = "unknown"


@dataclass(frozen=True)
class MobilePolicyAttribution:
    policy_authority: str
    expert_reference_used: bool
    expert_reference_semantics: tuple[str, ...]
    authority_trace_values: tuple[str, ...]
    system_control_class: str
    task_routing_authorities: tuple[str, ...]
    task_action_correction_count: int
    internally_consistent: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_mobile_policy_attribution(
    trace: Iterable[Mapping[str, Any]],
) -> MobilePolicyAttribution:
    items = tuple(trace)
    authorities = tuple(
        sorted(
            {
                str(item.get("policy_authority"))
                for item in items
                if item.get("policy_authority")
            }
        )
    )
    reference_used = any(item.get("expert_reference_used") is True for item in items)
    semantics = tuple(
        sorted(
            {
                str(item.get("expert_reference_semantics"))
                for item in items
                if item.get("expert_reference_semantics")
            }
        )
    )
    task_routing_authorities = tuple(
        sorted(
            {
                str(item.get("task_routing_authority"))
                for item in items
                if item.get("task_routing_authority")
            }
        )
    )
    task_action_correction_count = sum(
        len(tuple(item.get("task_action_corrections") or ())) for item in items
    )
    if reference_used or HYBRID_VLA_AUTHORITY in authorities:
        authority = HYBRID_VLA_AUTHORITY
    elif authorities == (ABSOLUTE_VLA_AUTHORITY,):
        authority = ABSOLUTE_VLA_AUTHORITY
    else:
        authority = UNKNOWN_VLA_AUTHORITY
    if authority == HYBRID_VLA_AUTHORITY:
        system_control_class = HYBRID_VLA_CONTROL_CLASS
    elif authority == ABSOLUTE_VLA_AUTHORITY and (
        task_action_correction_count > 0
        or any(value != "vla_policy" for value in task_routing_authorities)
    ):
        system_control_class = SHIELDED_VLA_CONTROL_CLASS
    elif authority == ABSOLUTE_VLA_AUTHORITY and task_routing_authorities == (
        "vla_policy",
    ):
        system_control_class = PURE_VLA_CONTROL_CLASS
    else:
        system_control_class = UNKNOWN_VLA_CONTROL_CLASS
    consistent = bool(
        authority != UNKNOWN_VLA_AUTHORITY
        and not (
            authority == ABSOLUTE_VLA_AUTHORITY
            and reference_used
        )
        and not (
            authority == HYBRID_VLA_AUTHORITY
            and not (reference_used or HYBRID_VLA_AUTHORITY in authorities)
        )
    )
    return MobilePolicyAttribution(
        policy_authority=authority,
        expert_reference_used=reference_used,
        expert_reference_semantics=semantics,
        authority_trace_values=authorities,
        system_control_class=system_control_class,
        task_routing_authorities=task_routing_authorities,
        task_action_correction_count=task_action_correction_count,
        internally_consistent=consistent,
    )
