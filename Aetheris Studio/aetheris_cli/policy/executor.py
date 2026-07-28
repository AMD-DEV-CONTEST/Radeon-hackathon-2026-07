"""
Tool execution seam and approval intent model ported from ROCm CLI.
Defines ApprovalIntent, RocmToolOutcome (Result, ApprovalRequired, Error), and the ToolExecutor contract with pre-execution safety re-validation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from aetheris_cli.policy.spec import PolicySpec, is_risky_bash_command


@dataclass
class ApprovalIntent:
    title: str
    body: List[str]
    name: str
    arguments: Dict[str, Any]


class OutcomeKind(Enum):
    RESULT = "result"
    APPROVAL_REQUIRED = "approval_required"
    ERROR = "error"


@dataclass
class RocmToolOutcome:
    kind: OutcomeKind
    result: Optional[Dict[str, Any]] = None
    intent: Optional[ApprovalIntent] = None
    error: Optional[str] = None


MUTATING_TOOLS = {"write_file", "write_files", "edit_file", "rollback_action"}


class BaseToolExecutor(ABC):
    def __init__(self, policy: Optional[PolicySpec] = None):
        self.policy = policy or PolicySpec()

    def is_mutating(self, name: str, args: Dict[str, Any]) -> bool:
        if name in MUTATING_TOOLS:
            return True
        if name == "bash":
            cmd = str(args.get("command") or args.get("cmd") or "")
            if is_risky_bash_command(cmd) or self.policy.allow_bash != "true":
                return True
        return False

    @abstractmethod
    def run_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        pass

    def execute(self, name: str, args: Dict[str, Any]) -> RocmToolOutcome:
        try:
            if self.is_mutating(name, args):
                cmd_summary = str(args.get("content") or args.get("command") or args.get("path") or args)
                intent = ApprovalIntent(
                    title=f"Confirm Mutating Tool: {name}",
                    body=[f"Tool '{name}' requests execution with arguments:", f"{cmd_summary}"],
                    name=name,
                    arguments=args,
                )
                return RocmToolOutcome(kind=OutcomeKind.APPROVAL_REQUIRED, intent=intent)

            res = self.run_tool(name, args)
            return RocmToolOutcome(kind=OutcomeKind.RESULT, result=res)
        except Exception as e:
            return RocmToolOutcome(kind=OutcomeKind.ERROR, error=str(e))

    def execute_approved(self, name: str, args: Dict[str, Any]) -> RocmToolOutcome:
        try:
            if name == "bash":
                cmd = str(args.get("command") or args.get("cmd") or "")
                if is_risky_bash_command(cmd) and self.policy.allow_bash == "false":
                    return RocmToolOutcome(kind=OutcomeKind.ERROR, error=f"Denied by policy: risky bash command '{cmd}'")

            res = self.run_tool(name, args)
            return RocmToolOutcome(kind=OutcomeKind.RESULT, result=res)
        except Exception as e:
            return RocmToolOutcome(kind=OutcomeKind.ERROR, error=str(e))
