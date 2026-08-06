import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Tools that are safe to execute without user interaction.
SAFE_AUTO_APPROVE_TOOLS: frozenset = frozenset({
    "file_read",
    "file_search",
    "file_list",
    "calendar_query",
})

# Tools that must ALWAYS require explicit approval — overrides cannot bypass this.
DANGEROUS_TOOLS: frozenset = frozenset({
    "file_write",
    "email_draft",
    "email_search",
    "calendar_create_event",
    "web_search",
})

# A minimal default config used when no privacy_config is provided.
_DEFAULT_PRIVACY_CONFIG: Dict = {
    "demo_mode": False,
}


class PermissionController:
    """Approval gate for tool execution.

    Safe tools (SAFE_AUTO_APPROVE_TOOLS) are auto-approved.
    Dangerous tools (DANGEROUS_TOOLS) always require explicit approval;
    per-tool overrides via set_auto_approve() cannot bypass this.
    Unknown tools default to requiring approval.
    """

    def __init__(self, privacy_config: Optional[Dict] = None):
        """Initializes the PermissionController.

        Args:
            privacy_config: Optional configuration dictionary. Defaults to a
                safe, non-demo-mode config when not provided.
        """
        self.config: Dict = privacy_config if privacy_config is not None else dict(_DEFAULT_PRIVACY_CONFIG)
        self._history: list = []  # [{tool, approved, timestamp, auto, params, reason}]
        self._auto_approve_overrides: Dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def requires_approval(self, tool_name: str) -> bool:
        """Return True if the tool needs explicit user approval.

        Dangerous tools always require approval regardless of overrides.
        Safe tools never require approval.
        Unknown tools default to requiring approval.

        Args:
            tool_name: The name of the tool to check.

        Returns:
            True if the tool needs user approval, False otherwise.
        """
        # Dangerous tools are always gated — no override can bypass this.
        if tool_name in DANGEROUS_TOOLS:
            return True

        # Safe tools are always auto-approved (unless explicitly demoted, which we don't support).
        if tool_name in SAFE_AUTO_APPROVE_TOOLS:
            return False

        # Per-tool override for *non-dangerous* unknown tools.
        if tool_name in self._auto_approve_overrides:
            return not self._auto_approve_overrides[tool_name]

        # Unknown tool → require approval by default.
        return True

    def gate(
        self,
        action: str,
        params: Optional[Dict] = None,
        target: str = "",
        reason: str = "",
    ) -> bool:
        """Structural permission gate invoked from inside a tool body.

        This moves the consent check that used to live in
        ``ToolRegistry.execute`` into the tool itself, so an LM has no
        prompt-level path around it. Thin wrapper over ``request_approval``.

        Args:
            action: The tool name being gated (e.g. ``"file_write"``).
            params: The parameters the tool was called with, recorded verbatim.
            target: Optional human-readable target (e.g. a file path). Added
                to ``params`` under the ``"target"`` key when not already
                present.
            reason: Why the tool is being called.

        Returns:
            True if approved, False otherwise.
        """
        request_params: Dict = dict(params or {})
        if target and "target" not in request_params:
            request_params["target"] = target
        return self.request_approval(action, request_params, reason=reason)

    def request_approval(self, tool_name: str, params: dict, reason: str = "") -> bool:
        """Request permission to execute a tool and record the decision.

        Args:
            tool_name: The tool being requested.
            params: Parameters for the tool.
            reason: Why the tool is needed.

        Returns:
            True if approved, False otherwise.
        """
        timestamp = time.time()
        needs_approval = self.requires_approval(tool_name)

        if not needs_approval:
            self._history.append({
                "tool": tool_name,
                "approved": True,
                "timestamp": timestamp,
                "auto": True,
                "params": params,
                "reason": reason,
            })
            logger.info("Auto-approved execution of tool: %s", tool_name)
            return True

        # Tools that need approval: check demo_mode.
        # Dangerous tools are recorded as non-auto even in demo mode.
        demo_mode = self.config.get("demo_mode", False)
        is_approved = bool(demo_mode)

        self._history.append({
            "tool": tool_name,
            "approved": is_approved,
            "timestamp": timestamp,
            "auto": False,
            "params": params,
            "reason": reason,
        })

        if is_approved:
            logger.info("Approved execution of tool (demo mode): %s", tool_name)
        else:
            logger.info("Pending/denied approval for tool: %s", tool_name)

        return is_approved

    def set_auto_approve(self, tool_name: str, enabled: bool) -> None:
        """Override the auto-approve setting for a specific *non-dangerous* tool.

        Dangerous tools (DANGEROUS_TOOLS) cannot be auto-approved by this method;
        the call is silently ignored for them and a warning is logged.

        Args:
            tool_name: The tool name.
            enabled: Whether to auto-approve.
        """
        if tool_name in DANGEROUS_TOOLS:
            logger.warning(
                "set_auto_approve('%s', True) ignored: dangerous tools cannot be auto-approved.",
                tool_name,
            )
            return
        self._auto_approve_overrides[tool_name] = enabled
        logger.info("Set auto-approve override for %s to %s", tool_name, enabled)

    def get_history(self) -> list:
        """Return a copy of the permission request history.

        Returns:
            A list of history entry dicts.
        """
        return list(self._history)

    def get_pending_count(self) -> int:
        """Count the number of pending (unapproved) requests.

        Returns:
            The count of pending requests.
        """
        return sum(1 for item in self._history if not item.get("approved", False))
