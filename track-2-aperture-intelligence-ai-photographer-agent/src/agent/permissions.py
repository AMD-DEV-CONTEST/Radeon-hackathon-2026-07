"""Explicit local permission policy for every Agent tool invocation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionRule:
    allowed: bool
    reason: str


class PermissionDenied(PermissionError):
    def __init__(self, message: str, audit: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.audit = audit


DEFAULT_RULES = {
    "read_uploaded_image": PermissionRule(
        True,
        "The user explicitly supplied this image for the current request.",
    ),
    "gpu_inference": PermissionRule(
        True,
        "Local AMD Radeon GPU inference is required for the requested task.",
    ),
    "write_temporary_result": PermissionRule(
        True,
        "A temporary local result is required and is deleted by the web handler.",
    ),
    "external_network": PermissionRule(
        False,
        "Core inference must remain fully local; external network access is denied.",
    ),
    "persistent_storage": PermissionRule(
        False,
        "Uploaded images and prompts are not persisted by default.",
    ),
    "generated_replacement_image": PermissionRule(
        False,
        "The product returns a contour coaching card, not a generated replacement.",
    ),
}


class PermissionPolicy:
    """Evaluate tool permissions and return a machine-readable audit trail."""

    def __init__(
        self,
        rules: dict[str, PermissionRule] | None = None,
    ) -> None:
        self.rules = dict(rules or DEFAULT_RULES)

    def authorize(
        self,
        tool_name: str,
        permissions: tuple[str, ...],
    ) -> list[dict[str, str]]:
        audit: list[dict[str, str]] = []
        denied: list[str] = []
        for permission in permissions:
            rule = self.rules.get(
                permission,
                PermissionRule(False, "Permission is not declared by the local policy."),
            )
            decision = "allow" if rule.allowed else "deny"
            audit.append(
                {
                    "tool": tool_name,
                    "permission": permission,
                    "decision": decision,
                    "reason": rule.reason,
                }
            )
            if not rule.allowed:
                denied.append(permission)
        if denied:
            raise PermissionDenied(
                f"Tool '{tool_name}' was denied permissions: {', '.join(denied)}",
                audit,
            )
        return audit

    def public_summary(self) -> dict[str, bool]:
        return {
            permission: rule.allowed
            for permission, rule in self.rules.items()
        }
