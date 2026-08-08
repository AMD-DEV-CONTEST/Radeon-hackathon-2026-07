"""Permission engine - decides if approval is needed."""

from __future__ import annotations

from typing import Dict, List, Set


class PermissionEngine:
    """Permission engine for action approval."""

    # Actions that never need approval (risk 0-1)
    AUTO_APPROVE: Set[str] = {
        "system.status",
        "system.disk_usage",
        "system.ram_usage",
        "system.processes",
        "system.network_status",
        "file.list",
        "file.scan",
        "file.read",
        "browser.search",
        "browser.read",
        "screen.scan",
    }

    # Actions that always need approval (risk 3+)
    REQUIRE_APPROVAL: Set[str] = {
        "file.delete_permanent",
        "file.quarantine",  # Bulk operations
        "system.kill_process",
        "system.run_command",
        "browser.download",
        "auth.password_login",
        "auth.passkey_login",
    }

    # Protected paths that always need approval
    PROTECTED_PATHS: List[str] = [
        "C:\\Windows",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
        "AppData",
        ".ssh",
        ".env",
    ]

    def requires_approval(
        self, risk_level: int, intent: str, tool: str = None, target: str = None
    ) -> bool:
        """Check if action requires approval."""
        # Risk-based
        if risk_level >= 3:
            return True

        # Tool-based
        if tool and tool in self.REQUIRE_APPROVAL:
            return True

        # Path-based
        if target and self._is_protected_path(target):
            return True

        return False

    def _is_protected_path(self, path: str) -> bool:
        """Check if path is protected."""
        path_lower = path.lower()
        for protected in self.PROTECTED_PATHS:
            if protected.lower() in path_lower:
                return True
        return False
