"""
Action Safety Governor (L5) — runs before every browser/desktop/mobile action.
Fail-closed: evaluation errors deny the action.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agents.base_agent import (
    ActionType,
    AgentAction,
    AgentObservation,
    CorpusType,
    EnvType,
    VisualTaskSpec,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision values
# ---------------------------------------------------------------------------


class SafetyDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_AUDIT = "ALLOW_WITH_AUDIT"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    BLOCK = "BLOCK"
    SANDBOX_ONLY = "SANDBOX_ONLY"


class ActionRisk(str, Enum):
    MINIMAL = "MINIMAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    ABSOLUTE = "ABSOLUTE"


# ---------------------------------------------------------------------------
# Policy types
# ---------------------------------------------------------------------------


@dataclass
class ActionPolicy:
    action_type: ActionType
    risk: ActionRisk
    default_decision: SafetyDecisionValue
    requires_sandbox: bool = False
    notes: str = ""


@dataclass
class ConfirmationRequirement:
    action_type: ActionType
    reason: str


@dataclass
class SafetyDecision:
    value: SafetyDecisionValue
    action: AgentAction
    risk: ActionRisk
    reason: str = ""
    requires_sandbox: bool = False
    corpus_type_on_block: CorpusType = CorpusType.SAFETY_REFUSAL
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        return self.value == SafetyDecisionValue.BLOCK

    @property
    def needs_confirmation(self) -> bool:
        return self.value == SafetyDecisionValue.REQUIRE_CONFIRMATION

    @property
    def needs_audit(self) -> bool:
        return self.value in (
            SafetyDecisionValue.ALLOW_WITH_AUDIT,
            SafetyDecisionValue.REQUIRE_CONFIRMATION,
            SafetyDecisionValue.BLOCK,
        )


# ---------------------------------------------------------------------------
# Static policy table
# ---------------------------------------------------------------------------

_ACTION_POLICY: dict[ActionType, ActionPolicy] = {
    # Observation — minimal risk
    ActionType.READ_SCREEN: ActionPolicy(
        ActionType.READ_SCREEN, ActionRisk.MINIMAL, SafetyDecisionValue.ALLOW
    ),
    ActionType.READ_DOM: ActionPolicy(
        ActionType.READ_DOM, ActionRisk.MINIMAL, SafetyDecisionValue.ALLOW
    ),
    ActionType.READ_ACCESSIBILITY_TREE: ActionPolicy(
        ActionType.READ_ACCESSIBILITY_TREE, ActionRisk.MINIMAL, SafetyDecisionValue.ALLOW
    ),
    # Pointer / keyboard — low risk
    ActionType.CLICK: ActionPolicy(
        ActionType.CLICK, ActionRisk.LOW, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    ActionType.TYPE: ActionPolicy(
        ActionType.TYPE, ActionRisk.LOW, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    ActionType.PRESS_KEY: ActionPolicy(
        ActionType.PRESS_KEY, ActionRisk.LOW, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    ActionType.SCROLL: ActionPolicy(
        ActionType.SCROLL, ActionRisk.MINIMAL, SafetyDecisionValue.ALLOW
    ),
    ActionType.DRAG: ActionPolicy(
        ActionType.DRAG, ActionRisk.LOW, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    # Touch — low risk
    ActionType.TAP: ActionPolicy(
        ActionType.TAP, ActionRisk.LOW, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    ActionType.SWIPE: ActionPolicy(
        ActionType.SWIPE, ActionRisk.LOW, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    # System / window — medium risk
    ActionType.OPEN_APP: ActionPolicy(
        ActionType.OPEN_APP, ActionRisk.MEDIUM, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    ActionType.SWITCH_WINDOW: ActionPolicy(
        ActionType.SWITCH_WINDOW, ActionRisk.MEDIUM, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    ActionType.RUN_COMMAND: ActionPolicy(
        ActionType.RUN_COMMAND, ActionRisk.MEDIUM, SafetyDecisionValue.ALLOW_WITH_AUDIT
    ),
    # File / code — high risk
    ActionType.EDIT_FILE: ActionPolicy(
        ActionType.EDIT_FILE, ActionRisk.HIGH, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.APPLY_PATCH: ActionPolicy(
        ActionType.APPLY_PATCH, ActionRisk.HIGH, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.UPLOAD_FILE: ActionPolicy(
        ActionType.UPLOAD_FILE, ActionRisk.HIGH, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.DOWNLOAD_FILE: ActionPolicy(
        ActionType.DOWNLOAD_FILE, ActionRisk.HIGH, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    # High-consequence — confirmation required
    ActionType.SUBMIT_FORM: ActionPolicy(
        ActionType.SUBMIT_FORM, ActionRisk.CRITICAL, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.SEND_MESSAGE: ActionPolicy(
        ActionType.SEND_MESSAGE, ActionRisk.CRITICAL, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.INSTALL_SOFTWARE: ActionPolicy(
        ActionType.INSTALL_SOFTWARE, ActionRisk.CRITICAL, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.GRANT_PERMISSION: ActionPolicy(
        ActionType.GRANT_PERMISSION, ActionRisk.CRITICAL, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.ENTER_CREDENTIAL: ActionPolicy(
        ActionType.ENTER_CREDENTIAL, ActionRisk.CRITICAL, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.MAKE_PURCHASE: ActionPolicy(
        ActionType.MAKE_PURCHASE, ActionRisk.CRITICAL, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.DELETE_DATA: ActionPolicy(
        ActionType.DELETE_DATA, ActionRisk.CRITICAL, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
    ActionType.DEPLOY_OR_PUBLISH: ActionPolicy(
        ActionType.DEPLOY_OR_PUBLISH, ActionRisk.CRITICAL, SafetyDecisionValue.REQUIRE_CONFIRMATION
    ),
}

# Actions that are confirmation-required regardless of context
_MANDATORY_CONFIRMATION: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_MESSAGE,
        ActionType.SUBMIT_FORM,
        ActionType.MAKE_PURCHASE,
        ActionType.DELETE_DATA,
        ActionType.UPLOAD_FILE,
        ActionType.DOWNLOAD_FILE,
        ActionType.ENTER_CREDENTIAL,
        ActionType.INSTALL_SOFTWARE,
        ActionType.GRANT_PERMISSION,
        ActionType.DEPLOY_OR_PUBLISH,
    }
)

# Environments that require sandbox
_SANDBOX_REQUIRED_ENVS: frozenset[EnvType] = frozenset(
    {
        EnvType.DESKTOP,
        EnvType.MOBILE,
    }
)


# ---------------------------------------------------------------------------
# Absolute-block intent patterns
# ---------------------------------------------------------------------------

_ABSOLUTE_BLOCK_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "credential_theft",
        re.compile(
            r"(steal|harvest|dump|exfiltrat|capture).{0,40}(credential|password|token|secret|api.key|cookie)",
            re.I,
        ),
    ),
    (
        "covert_surveillance",
        re.compile(
            r"(monitor|watch|record|track|spy).{0,40}(without.{0,20}(consent|knowledge|permission|telling))",
            re.I,
        ),
    ),
    (
        "doxxing",
        re.compile(
            r"(aggregat|collect|find|expose).{0,40}(home.?address|personal.?info|real.?name|identity).{0,40}(target|stalk|harass)",
            re.I,
        ),
    ),
    (
        "harassment_automation",
        re.compile(
            r"(automat|bulk|flood|bomb).{0,40}(message|contact|text|call|email).{0,40}(harass|target|spam|annoy)",
            re.I,
        ),
    ),
    (
        "spam_automation",
        re.compile(
            r"(bulk|mass|unsolicited).{0,40}(email|sms|message|notification).{0,40}(send|blast|broadcast)",
            re.I,
        ),
    ),
    (
        "bulk_message_automation",
        re.compile(
            r"automat\w*.{0,30}(bulk|mass|unsolicited).{0,40}(message|email|sms|notification)", re.I
        ),
    ),
    (
        "dark_pattern",
        re.compile(
            r"(fake.urgency|hidden.unsubscribe|pre.checked|misdirection|confuse.user).{0,40}(deploy|generate|build|implement)",
            re.I,
        ),
    ),
    (
        "nonconsensual_tracking",
        re.compile(
            r"(track|locate|gps|monitor).{0,40}(without.{0,20}(consent|knowledge|telling|knowing))",
            re.I,
        ),
    ),
    (
        "malware_persistence",
        re.compile(
            r"(persist|survive.reboot|autostart|startup).{0,40}(registry|hkcu|hklm|crontab|launchd|rc\\.local)",
            re.I,
        ),
    ),
    (
        "reverse_shell",
        re.compile(
            r"(reverse.shell|bind.shell|nc.{0,5}-e|bash.{0,5}-i.{0,10}>&|connect.back)", re.I
        ),
    ),
    (
        "data_exfiltration",
        re.compile(
            r"(exfiltrat|send.to.server|upload.covert|beacon).{0,40}(without.{0,20}(consent|knowledge|permission))",
            re.I,
        ),
    ),
]


# ---------------------------------------------------------------------------
# ActionSafetyGovernor
# ---------------------------------------------------------------------------


class ActionSafetyGovernor:
    """
    Evaluates every planned action before execution.
    Call evaluate_action() at the controller layer — never skip it.
    """

    def evaluate_action(
        self,
        task: VisualTaskSpec,
        observation: AgentObservation,
        action: AgentAction,
    ) -> SafetyDecision:
        try:
            return self._evaluate(task, observation, action)
        except Exception as exc:
            log.error("[safety_governor] evaluation error (fail-closed): %s", exc)
            return SafetyDecision(
                value=SafetyDecisionValue.BLOCK,
                action=action,
                risk=ActionRisk.ABSOLUTE,
                reason=f"Safety governor error (fail-closed): {exc}",
            )

    def _evaluate(
        self,
        task: VisualTaskSpec,
        observation: AgentObservation,
        action: AgentAction,
    ) -> SafetyDecision:
        # 1. Check absolute-block patterns in rationale + payload
        block_reason = self._check_absolute_patterns(action)
        if block_reason:
            log.warning(
                "[safety_governor] BLOCK absolute pattern matched: %s action_type=%s task=%s",
                block_reason,
                action.action_type,
                task.task_id,
            )
            return SafetyDecision(
                value=SafetyDecisionValue.BLOCK,
                action=action,
                risk=ActionRisk.ABSOLUTE,
                reason=block_reason,
            )

        # 2. Sandbox requirement check
        policy = _ACTION_POLICY.get(action.action_type)
        env = task.env_type
        if env in _SANDBOX_REQUIRED_ENVS:
            sandbox_ok = task.metadata.get("sandbox_active", False)
            if not sandbox_ok:
                return SafetyDecision(
                    value=SafetyDecisionValue.BLOCK,
                    action=action,
                    risk=ActionRisk.CRITICAL,
                    reason=f"Env {env.value} requires sandbox (VM/emulator). "
                    "Set task.metadata['sandbox_active']=True after confirming isolation.",
                    requires_sandbox=True,
                )

        # 3. Policy-table decision
        if policy is None:
            log.warning(
                "[safety_governor] unknown action_type %s — defaulting to REQUIRE_CONFIRMATION",
                action.action_type,
            )
            return SafetyDecision(
                value=SafetyDecisionValue.REQUIRE_CONFIRMATION,
                action=action,
                risk=ActionRisk.HIGH,
                reason=f"Unknown action type {action.action_type} — confirmation required by default",
            )

        # 4. Mandatory confirmation override
        if action.action_type in _MANDATORY_CONFIRMATION:
            return SafetyDecision(
                value=SafetyDecisionValue.REQUIRE_CONFIRMATION,
                action=action,
                risk=policy.risk,
                reason=f"{action.action_type.value} requires explicit human confirmation",
            )

        # 5. Return policy default
        return SafetyDecision(
            value=policy.default_decision,
            action=action,
            risk=policy.risk,
            reason="Policy default",
        )

    def _check_absolute_patterns(self, action: AgentAction) -> str:
        text = " ".join(
            filter(
                None,
                [
                    action.rationale,
                    action.payload or "",
                    action.target or "",
                ],
            )
        )
        for category, pattern in _ABSOLUTE_BLOCK_PATTERNS:
            if pattern.search(text):
                return f"Absolute-block pattern matched: {category}"
        return ""

    # ------------------------------------------------------------------
    # Cloud vision gate
    # ------------------------------------------------------------------

    def check_cloud_vision_allowed(
        self, screenshot_path: str, cloak_active: bool
    ) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        Cloud vision calls require Visual Cloak PII redaction to be active.
        """
        if not cloak_active:
            return False, (
                "Visual Cloak (PII/secret redaction) must be active before sending screenshots "
                "to cloud vision APIs. Set cloak_active=True after running visual_cloak.redact()."
            )
        return True, "ok"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_governor: ActionSafetyGovernor | None = None


def get_governor() -> ActionSafetyGovernor:
    global _governor
    if _governor is None:
        _governor = ActionSafetyGovernor()
    return _governor
