"""Risk classifier - assesses risk level of actions."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


class RiskClassifier:
    """Classifies risk level of commands."""

    # Risk patterns: (pattern, risk_level, reason)
    RISK_PATTERNS: List[Tuple[re.Pattern[str], int, str]] = [
        # Level 5 - Critical
        (re.compile(r"\b(permanently delete|wipe|erase|format)\b"), 5, "permanent deletion"),
        (re.compile(r"\b(export|extract)\b.*\b(password|credential|key)\b"), 5, "credential export"),

        # Level 4 - High
        (re.compile(r"\b(delete|remove)\b.*\b(all|everything)\b"), 4, "bulk deletion"),
        (re.compile(r"\bempty\b.*\b(recycle bin|trash)\b"), 4, "empty trash"),
        (re.compile(r"\b(admin|administrator)\b"), 4, "admin operation"),
        (re.compile(r"\b(system|kernel)\b.*\b(modify|change|edit)\b"), 4, "system modification"),

        # Level 3 - Medium
        (re.compile(r"\b(login|sign in|log in)\b"), 3, "login operation"),
        (re.compile(r"\b(send|compose)\b.*\b(email|mail)\b"), 3, "send email"),
        (re.compile(r"\b(install|setup)\b"), 3, "install software"),
        (re.compile(r"\b(run|execute)\b.*\b(script|command)\b"), 3, "run script"),

        # Level 2 - Low-Medium
        (re.compile(r"\b(download|fetch)\b"), 2, "download file"),
        (re.compile(r"\b(rename|move)\b"), 2, "rename/move file"),
        (re.compile(r"\b(copy)\b"), 2, "copy file"),

        # Level 1 - Low
        (re.compile(r"\b(open|launch|start)\b.*\b(app|application|program)\b"), 1, "open app"),
        (re.compile(r"\b(open|visit|navigate)\b.*\b(website|url|site)\b"), 1, "open website"),

        # Level 0 - Safe
        (re.compile(r"\b(check|show|get|list)\b.*\b(status|info|files)\b"), 0, "read-only"),
        (re.compile(r"\b(search|find)\b"), 0, "search"),
    ]

    async def assess(self, text: str, intent: str) -> int:
        """Assess risk level of command.

        Returns risk level 0-5.
        """
        text_lower = text.lower()

        # Check patterns
        max_risk = 0
        for pattern, risk_level, reason in self.RISK_PATTERNS:
            if pattern.search(text_lower):
                max_risk = max(max_risk, risk_level)

        # Intent-based risk
        intent_risk = self._intent_risk(intent)
        max_risk = max(max_risk, intent_risk)

        return max_risk

    def _intent_risk(self, intent: str) -> int:
        """Get risk level based on intent."""
        intent_risks = {
            "system_status": 0,
            "disk_usage": 0,
            "ram_usage": 0,
            "list_files": 0,
            "search_web": 0,
            "browser_close": 0,
            "browser_session": 1,
            "screen_scan": 0,
            "screen_click": 1,
            "open_app": 1,
            "open_website": 1,
            "download_file": 2,
            "login": 3,
            "send_email": 3,
            "run_command": 3,
            "delete_files": 4,
        }
        return intent_risks.get(intent, 1)
