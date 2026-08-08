"""Goal Planner — converts an intent into a high-level goal.

A goal is a structured representation of what the user wants to achieve.
It includes:
  - objective: the main thing to accomplish
  - success_criteria: how we know we're done
  - constraints: things we must respect
  - scope: what is in/out of scope
  - priority: how urgent this is

Goals are higher-level than intents. An intent is "what kind of command
is this?" A goal is "what does success look like?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Goal:
    """A high-level goal derived from an intent."""
    objective: str
    success_criteria: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    scope_in: List[str] = field(default_factory=list)
    scope_out: List[str] = field(default_factory=list)
    priority: int = 5  # 1=highest, 10=lowest
    reversible: bool = True
    estimated_steps: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "success_criteria": self.success_criteria,
            "constraints": self.constraints,
            "scope_in": self.scope_in,
            "scope_out": self.scope_out,
            "priority": self.priority,
            "reversible": self.reversible,
            "estimated_steps": self.estimated_steps,
            "metadata": self.metadata,
        }


class GoalPlanner:
    """Converts intents into structured goals."""

    # Intent → goal template
    GOAL_TEMPLATES = {
        "open_website": {
            "objective": "Open the requested website in a browser",
            "success_criteria": [
                "Browser is running",
                "Target URL is loaded",
                "Page is interactive",
            ],
            "constraints": [
                "Use default browser if Playwright unavailable",
                "Do not auto-fill credentials",
            ],
            "scope_in": ["browser launch", "URL navigation"],
            "scope_out": ["login", "form submission"],
            "priority": 4,
            "reversible": True,
            "estimated_steps": 2,
        },
        "open_app": {
            "objective": "Open the requested application",
            "success_criteria": [
                "Application process is running",
                "Application window is visible",
            ],
            "constraints": [
                "Do not run as admin without approval",
                "Use installed application path",
            ],
            "scope_in": ["app launch"],
            "scope_out": ["app configuration", "data entry"],
            "priority": 4,
            "reversible": True,
            "estimated_steps": 1,
        },
        "search_web": {
            "objective": "Search the web for the given query",
            "success_criteria": [
                "Search engine is loaded",
                "Query is submitted",
                "Results are visible",
            ],
            "constraints": [
                "Use a reputable search engine",
                "Do not click ads",
            ],
            "scope_in": ["search submission", "result page"],
            "scope_out": ["clicking individual results"],
            "priority": 4,
            "reversible": True,
            "estimated_steps": 2,
        },
        "delete_files": {
            "objective": "Safely remove the specified files",
            "success_criteria": [
                "Files are moved to quarantine",
                "User can restore from quarantine",
                "Original paths are recorded",
            ],
            "constraints": [
                "Use quarantine, not permanent delete",
                "Require approval for bulk operations",
                "Never delete system files",
            ],
            "scope_in": ["file quarantine", "quarantine index update"],
            "scope_out": ["permanent deletion", "system folders"],
            "priority": 2,
            "reversible": True,
            "estimated_steps": 3,
        },
        "list_files": {
            "objective": "List files in the specified directory",
            "success_criteria": [
                "Directory contents are enumerated",
                "File metadata is returned",
            ],
            "constraints": [
                "Respect max depth and max files limits",
                "Do not follow symlinks",
            ],
            "scope_in": ["directory scan"],
            "scope_out": ["file modification"],
            "priority": 6,
            "reversible": True,
            "estimated_steps": 1,
        },
        "screen_click": {
            "objective": "Click the specified UI element",
            "success_criteria": [
                "Element is located",
                "Click is performed at correct coordinates",
            ],
            "constraints": [
                "Use UIA first, OCR second, detector third",
                "Confirm before clicking destructive controls",
            ],
            "scope_in": ["element location", "mouse click"],
            "scope_out": ["keyboard input", "form submission"],
            "priority": 5,
            "reversible": True,
            "estimated_steps": 2,
        },
        "login": {
            "objective": "Log into the specified site",
            "success_criteria": [
                "Login page is detected",
                "Credentials are filled",
                "Login succeeds",
            ],
            "constraints": [
                "Require vault unlock",
                "Redact credentials from logs",
                "Show target domain before approval",
            ],
            "scope_in": ["vault unlock", "credential fill", "form submit"],
            "scope_out": ["post-login navigation"],
            "priority": 3,
            "reversible": False,
            "estimated_steps": 4,
        },
        "download_file": {
            "objective": "Download the specified file",
            "success_criteria": [
                "File is downloaded to AI_Downloads",
                "File type is verified",
                "Hash is recorded",
            ],
            "constraints": [
                "Verify source domain",
                "Require approval for executables",
                "Never auto-run downloads",
            ],
            "scope_in": ["URL fetch", "file save", "hash check"],
            "scope_out": ["file execution"],
            "priority": 3,
            "reversible": True,
            "estimated_steps": 3,
        },
        "system_status": {
            "objective": "Report current system status",
            "success_criteria": [
                "CPU, RAM, disk, battery are reported",
                "Running processes are listed",
            ],
            "constraints": [
                "Read-only operations only",
            ],
            "scope_in": ["system metrics"],
            "scope_out": ["system modification"],
            "priority": 7,
            "reversible": True,
            "estimated_steps": 1,
        },
        "browser_session": {
            "objective": "Maintain an active browser session",
            "success_criteria": [
                "Browser is open",
                "System is kept awake",
                "Mouse is jiggled periodically",
            ],
            "constraints": [
                "Auto-approval only",
                "No destructive actions",
            ],
            "scope_in": ["browser launch", "awake state", "mouse jiggle"],
            "scope_out": ["file operations", "credential use"],
            "priority": 5,
            "reversible": True,
            "estimated_steps": 3,
        },
    }

    DEFAULT_GOAL = {
        "objective": "Execute the requested command",
        "success_criteria": ["Command completes without error"],
        "constraints": ["Respect risk and approval policies"],
        "scope_in": ["command execution"],
        "scope_out": ["unspecified side effects"],
        "priority": 5,
        "reversible": True,
        "estimated_steps": 1,
    }

    def plan(self, intent: str, params: Dict[str, Any]) -> Goal:
        """Build a Goal from an intent and its parameters."""
        template = self.GOAL_TEMPLATES.get(intent, self.DEFAULT_GOAL)

        # Customize based on params
        objective = self._customize_objective(template["objective"], intent, params)
        success = list(template["success_criteria"])
        constraints = list(template["constraints"])
        scope_in = list(template["scope_in"])
        scope_out = list(template["scope_out"])

        # Add param-specific constraints
        if params.get("path"):
            constraints.append(f"Operate only within: {params['path']}")
        if params.get("url"):
            constraints.append(f"Target URL: {params['url']}")
        if params.get("app"):
            scope_in.append(f"App: {params['app']}")

        # Adjust priority based on risk indicators
        priority = template["priority"]
        if any(k in params for k in ("permanent", "delete_permanent")):
            priority = min(priority, 2)
        if params.get("bulk"):
            priority = min(priority, 3)

        return Goal(
            objective=objective,
            success_criteria=success,
            constraints=constraints,
            scope_in=scope_in,
            scope_out=scope_out,
            priority=priority,
            reversible=template["reversible"],
            estimated_steps=template["estimated_steps"],
            metadata={
                "intent": intent,
                "params": params,
            },
        )

    def _customize_objective(self, base: str, intent: str, params: Dict[str, Any]) -> str:
        """Customize the objective string with params."""
        if intent == "open_website" and params.get("url"):
            return f"Open {params['url']} in a browser"
        if intent == "open_app" and params.get("app"):
            return f"Open the {params['app']} application"
        if intent == "search_web" and params.get("query"):
            return f"Search the web for: {params['query']}"
        if intent == "delete_files" and params.get("path"):
            return f"Safely remove files in {params['path']}"
        if intent == "list_files" and params.get("path"):
            return f"List files in {params['path']}"
        if intent == "screen_click" and params.get("text"):
            return f"Click the UI element labeled '{params['text']}'"
        if intent == "login" and params.get("site"):
            return f"Log into {params['site']}"
        if intent == "download_file" and params.get("url"):
            return f"Download file from {params['url']}"
        return base
