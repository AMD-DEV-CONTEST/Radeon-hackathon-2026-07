"""Native LLM-neutral program advisory packets.

This module does not call a model. It prepares a verifier-first brief that a
user can paste into any LLM, or that the IDE can pass to a configured provider.
The packet is advisory only: it does not prove correctness, authorize source
mutation, or open training eligibility.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = "determinex-llm-program-advisory-v1"

_REPAIR_WORDS = ("repair", "fix", "bug", "broken", "failing", "failure", "regression", "error")
_UPKEEP_WORDS = (
    "maintain",
    "upkeep",
    "update",
    "upgrade",
    "dependency",
    "security",
    "refactor",
    "cleanup",
)

_BUILD_FILES = (
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Makefile",
    "CMakeLists.txt",
)

_SKIP_DIRS = {
    ".git",
    ".tmp",
    ".venv",
    "__pycache__",
    "node_modules",
    "target",
    ".next",
    "playwright-report",
    "corpus",
    "logs",
}

_LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".js": "javascript",
    ".jsx": "javascript-react",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".h": "c-cpp-header",
    ".hpp": "cpp-header",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "shell",
    ".sql": "sql",
}


@dataclass(frozen=True)
class LLMProgramAdvisoryPacket:
    schema_version: str
    intent: str
    workspace: str
    workspace_exists: bool
    user_request: str
    language_signals: tuple[str, ...]
    build_signals: tuple[str, ...]
    context_files: tuple[str, ...]
    advisory_only: bool = True
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    universal_verified_support_claimed: bool = False
    llm_contract: dict[str, object] = field(default_factory=dict)
    verifier_plan: tuple[str, ...] = field(default_factory=tuple)
    blocked_claims: tuple[str, ...] = field(default_factory=tuple)
    prompt_template: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["language_signals"] = list(self.language_signals)
        payload["build_signals"] = list(self.build_signals)
        payload["context_files"] = list(self.context_files)
        payload["verifier_plan"] = list(self.verifier_plan)
        payload["blocked_claims"] = list(self.blocked_claims)
        return payload

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def classify_intent(user_request: str) -> str:
    lowered = user_request.lower()
    if any(word in lowered for word in _REPAIR_WORDS):
        return "repair"
    if any(word in lowered for word in _UPKEEP_WORDS):
        return "upkeep"
    return "creation"


def _iter_workspace_files(workspace: Path, *, limit: int = 240) -> list[Path]:
    if not workspace.is_dir():
        return []
    out: list[Path] = []
    stack = [workspace]
    while stack and len(out) < limit:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            continue
        for path in children:
            if len(out) >= limit:
                break
            if path.is_dir():
                if path.name not in _SKIP_DIRS:
                    stack.append(path)
            elif path.is_file():
                out.append(path)
    return out


def inspect_workspace(
    workspace: Path | None,
) -> tuple[bool, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if workspace is None:
        return False, (), (), ()
    root = Path(workspace)
    files = _iter_workspace_files(root)
    languages = sorted(
        {
            _LANGUAGE_EXTENSIONS[path.suffix.lower()]
            for path in files
            if path.suffix.lower() in _LANGUAGE_EXTENSIONS
        }
    )
    build_signals = sorted(path.name for path in files if path.name in _BUILD_FILES)
    context_files = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if path.name in _BUILD_FILES or path.name.lower() in {
            "readme.md",
            "readme",
            "requirements.txt",
        }:
            context_files.append(rel)
        elif path.suffix.lower() in _LANGUAGE_EXTENSIONS and len(context_files) < 12:
            context_files.append(rel)
        if len(context_files) >= 20:
            break
    return root.is_dir(), tuple(languages), tuple(build_signals), tuple(context_files)


def _verifier_plan(
    intent: str, languages: tuple[str, ...], build_signals: tuple[str, ...]
) -> tuple[str, ...]:
    base = [
        "Identify the smallest deterministic verifier before proposing changes.",
        "Prefer existing project commands over invented commands.",
        "Run formatting, type checks, unit tests, and targeted reproduction where available.",
        "Treat screenshots, logs, and model analysis as advisory until a verifier passes.",
    ]
    if intent == "repair":
        base.insert(0, "Reproduce the failure or capture the exact blocker before patching.")
    elif intent == "upkeep":
        base.insert(
            0, "List compatibility risks and rollback steps before applying maintenance changes."
        )
    else:
        base.insert(0, "Define acceptance tests before generating the first implementation.")
    if "package.json" in build_signals:
        base.append("For Node work, inspect package scripts and use lockfile-preserving installs.")
    if "pyproject.toml" in build_signals or "requirements.txt" in build_signals:
        base.append(
            "For Python work, use the repository virtualenv and run focused pytest targets."
        )
    if "Cargo.toml" in build_signals or "rust" in languages:
        base.append(
            "For Rust work, run cargo fmt/check/test with the repo's configured target dir when needed."
        )
    return tuple(base)


def build_advisory_packet(
    *,
    user_request: str,
    workspace: Path | None = None,
) -> LLMProgramAdvisoryPacket:
    intent = classify_intent(user_request)
    workspace_exists, languages, build_signals, context_files = inspect_workspace(workspace)
    workspace_label = str(Path(workspace)) if workspace is not None else ""
    verifier_plan = _verifier_plan(intent, languages, build_signals)
    blocked_claims = (
        "Do not claim the program is correct until deterministic verifiers pass.",
        "Do not claim universal language, framework, or ecosystem support from this advisory packet.",
        "Do not mutate source unless the user explicitly approves a reviewed patch.",
        "Do not mark outputs training-eligible from advisory content.",
    )
    role = {
        "creation": "Turn the request into tests, a minimal implementation plan, and verifier commands.",
        "upkeep": "Identify maintenance risks, safe update order, rollback points, and verifier commands.",
        "repair": "Reproduce the failure, isolate likely cause, propose the smallest patch, and verify.",
    }[intent]
    prompt = "\n".join(
        [
            "You are advising inside Determinex.",
            f"Intent: {intent}",
            f"User request: {user_request.strip() or '<empty request>'}",
            f"Workspace exists: {workspace_exists}",
            f"Language signals: {', '.join(languages) if languages else 'unknown'}",
            f"Build signals: {', '.join(build_signals) if build_signals else 'unknown'}",
            "Rules: be verifier-first, preserve source until approval, and separate advice from proof.",
            "Return: diagnosis/plan, exact files to inspect, exact verifier commands, risks, and next blocked gate.",
        ]
    )
    return LLMProgramAdvisoryPacket(
        schema_version=SCHEMA_VERSION,
        intent=intent,
        workspace=workspace_label,
        workspace_exists=workspace_exists,
        user_request=user_request,
        language_signals=languages,
        build_signals=build_signals,
        context_files=context_files,
        llm_contract={
            "model_agnostic": True,
            "role": role,
            "allowed_uses": ["creation", "upkeep", "repair"],
            "output_must_include": [
                "exact verifier commands",
                "source files to inspect",
                "risk and rollback notes",
                "proof boundary",
            ],
        },
        verifier_plan=verifier_plan,
        blocked_claims=blocked_claims,
        prompt_template=prompt,
    )


__all__ = [
    "LLMProgramAdvisoryPacket",
    "SCHEMA_VERSION",
    "build_advisory_packet",
    "classify_intent",
    "inspect_workspace",
]
