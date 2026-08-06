from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PolicyResult(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class ToolIntent:
    tool: str
    action: str
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    external_side_effect: bool = False
    destructive: bool = False
    contains_untrusted_instructions: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    result: PolicyResult
    reasons: tuple[str, ...]


class ActionPolicy:
    """Fail-closed policy for model-proposed tool activity."""

    denied_tools = {
        "credential_export",
        "browser_profile_upload",
        "unscoped_shell",
        "disable_audit",
    }
    approval_actions = {
        "publish",
        "send",
        "run_shell",
        "overwrite",
        "delete",
        "sign",
        "connect_account",
    }

    def decide(self, intent: ToolIntent) -> PolicyDecision:
        reasons: list[str] = []
        if intent.tool in self.denied_tools:
            reasons.append("tool is outside the bounded competition surface")
        if intent.destructive:
            reasons.append("destructive action is disabled")
        if intent.contains_untrusted_instructions and (
            intent.external_side_effect or intent.writes
        ):
            reasons.append("untrusted content cannot authorize a side effect")
        if reasons:
            return PolicyDecision(PolicyResult.DENY, tuple(reasons))

        if intent.external_side_effect or intent.action in self.approval_actions:
            return PolicyDecision(
                PolicyResult.REQUIRE_APPROVAL,
                ("consequential action requires explicit human approval",),
            )

        if intent.writes:
            return PolicyDecision(
                PolicyResult.REQUIRE_APPROVAL,
                ("write scope must be confirmed before execution",),
            )

        return PolicyDecision(PolicyResult.ALLOW, ("read-only bounded action",))
