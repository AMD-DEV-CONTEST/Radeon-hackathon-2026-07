"""Opt-in repository context providers for controlled ablations.

Each provider is deliberately best-effort and reports whether its native
implementation was available.  The runner can therefore compare an explicit
fallback result with a missing dependency instead of silently claiming that a
context method ran.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from typing import Any, Callable, Mapping


CommandRunner = Callable[[str, int], Mapping[str, Any]]


@dataclass(frozen=True)
class ContextResult:
    variant: str
    text: str
    provider: str
    available: bool
    metadata: dict[str, Any]


def _command_output(runner: CommandRunner, command: str, timeout: int = 30) -> tuple[str, int]:
    result = runner(command, timeout)
    return str(result.get("output", "")), int(result.get("exit_code", result.get("returncode", 0)))


class ContextProvider:
    variant = "C0"
    name = "baseline"

    def build(self, runner: CommandRunner, issue: str) -> ContextResult:
        return ContextResult(self.variant, "", self.name, True, {})


class RepoMapProvider(ContextProvider):
    variant = "C1"
    name = "aider-repomap-static"

    def build(self, runner: CommandRunner, issue: str) -> ContextResult:
        command = os.getenv(
            "TRACK2_AIDER_REPOMAP_COMMAND",
            "aider --show-repo-map --map-tokens 4096",
        )
        output, code = _command_output(runner, command, 60)
        if code == 0 and output.strip():
            return ContextResult(
                self.variant,
                output.strip(),
                self.name,
                True,
                {"command": command, "native": True, "token_budget": 4096},
            )
        # A deterministic fallback is useful for local smoke tests, but it is
        # marked unavailable so it cannot be confused with Aider's map.
        fallback = "find . -maxdepth 3 -type f -not -path './.git/*' | sort | head -200"
        fallback_output, fallback_code = _command_output(runner, fallback, 30)
        return ContextResult(
            self.variant,
            fallback_output.strip(),
            self.name,
            False,
            {"command": command, "exit_code": code, "fallback": fallback_code},
        )


class RepoGraphProvider(ContextProvider):
    variant = "C2"
    name = "repograph-static-summary"

    def build(self, runner: CommandRunner, issue: str) -> ContextResult:
        command = os.getenv("TRACK2_REPOGRAPH_COMMAND", "")
        if not command:
            return ContextResult(
                self.variant,
                "RepoGraph is not configured. Set TRACK2_REPOGRAPH_COMMAND to the pinned RepoGraph extractor.",
                self.name,
                False,
                {"configured": False, "interactive": False},
            )
        output, code = _command_output(runner, command, 120)
        return ContextResult(
            self.variant,
            output.strip(),
            self.name,
            code == 0 and bool(output.strip()),
            {"command": command, "exit_code": code, "interactive": False},
        )


class AgentlessLocalizationProvider(ContextProvider):
    variant = "C3"
    name = "agentless-localization"

    def build(self, runner: CommandRunner, issue: str) -> ContextResult:
        terms = [word for word in issue.replace("/", " ").split() if len(word) >= 4][:8]
        if not terms:
            return ContextResult(self.variant, "", self.name, False, {"terms": []})
        pattern = "|".join(shlex.quote(term) for term in terms)
        command = f"rg -n -i --hidden --glob '!.git' -e {pattern} . | head -120"
        output, code = _command_output(runner, command, 60)
        return ContextResult(
            self.variant,
            output.strip(),
            self.name,
            code in {0, 1} and bool(output.strip()),
            {"terms": terms, "command": command, "exit_code": code},
        )


class GitHistoryProvider(ContextProvider):
    variant = "C4"
    name = "git-history"

    def build(self, runner: CommandRunner, issue: str) -> ContextResult:
        command = "git log --oneline --decorate -20"
        output, code = _command_output(runner, command, 30)
        return ContextResult(
            self.variant,
            output.strip(),
            self.name,
            code == 0 and bool(output.strip()),
            {"command": command, "exit_code": code},
        )


class LoopGuardContext(ContextProvider):
    variant = "C5"
    name = "loop-guard"

    def build(self, runner: CommandRunner, issue: str) -> ContextResult:
        return ContextResult(
            self.variant,
            "Avoid repeating an identical command or edit. If two consecutive attempts produce the same failure, change strategy or recover.",
            self.name,
            True,
            {},
        )


PROVIDERS = {
    "C0": ContextProvider,
    "C1": RepoMapProvider,
    "C2": RepoGraphProvider,
    "C3": AgentlessLocalizationProvider,
    "C4": GitHistoryProvider,
    "C5": LoopGuardContext,
}


def build_context(variant: str, runner: CommandRunner, issue: str) -> ContextResult:
    try:
        provider_type = PROVIDERS[variant.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown context variant: {variant!r}") from exc
    return provider_type().build(runner, issue)
