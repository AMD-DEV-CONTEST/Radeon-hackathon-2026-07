"""
Policy specification parser and data structures.
Normalizes command line flags such as --allow, --allow-bash, --plan-only, and --egress-strict.
"""

from dataclasses import dataclass, field
from typing import List, Set


KNOWN_TOOLS = {
    "write_file",
    "edit_file",
    "bash",
    "manage_todo",
    "navigate_browser",
    "read_browser_page",
    "inspect_session",
    "verify_chain",
    "search_workspace",
    "list_dir",
    "read_file",
    "undo",
}

RISKY_BASH_KEYWORDS = [
    "rm -rf", "rmdir /s", "mkfs", "dd ", "> /dev/", "shutdown", "reboot", "chmod -R", "chown -R"
]


@dataclass
class PolicySpec:
    allowed_tools: Set[str] = field(default_factory=set)
    allow_bash: bool = False
    allow_risky_bash: bool = False
    plan_only: bool = False
    egress_strict: bool = False

    @classmethod
    def parse(
        cls,
        allow_str: str = "",
        allow_bash_val: str = "false",
        plan_only: bool = False,
        egress_strict: bool = False,
    ) -> "PolicySpec":
        spec = cls(plan_only=plan_only, egress_strict=egress_strict)

        if allow_str:
            parts = [p.strip().lower() for p in allow_str.split(",") if p.strip()]
            for item in parts:
                spec.allowed_tools.add(item)

        bash_flag = allow_bash_val.strip().lower() if isinstance(allow_bash_val, str) else str(allow_bash_val).lower()
        if bash_flag in ("true", "1", "yes", "all", "risky"):
            spec.allow_bash = True
            if bash_flag == "risky":
                spec.allow_risky_bash = True

        return spec

    def validate(self) -> List[str]:
        errors = []
        for tool in self.allowed_tools:
            if tool not in KNOWN_TOOLS:
                errors.append(f"Unknown tool specified in --allow: {tool!r}")
        return errors


def is_risky_bash_command(cmd_text: str) -> bool:
    lowered = cmd_text.lower()
    return any(keyword in lowered for keyword in RISKY_BASH_KEYWORDS)
