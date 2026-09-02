"""scripts/intake/build_adapters.py — Per-language build adapters.

BuildAdapter protocol + concrete adapters for Python, Rust, Go, Node/TS,
Java/Maven, Java/Gradle, and a deliberate Unknown fallback. Established by
BUILD_ADAPTER_REGISTRY_LOCK_001 as the replacement for the 14-line
if-ladder in ``codebase_explorer.detect_build_system``.

Contract (intentionally minimal — this lock proves the pattern; later rungs
extend it):

    name                  human-readable label
    build_system_id       string identifier; MUST match historical strings
                          returned by codebase_explorer.detect_build_system
                          ("pip", "cargo", "go", "npm", "maven", "gradle",
                          "unknown")
    test_framework_id     default test-framework string ("pytest",
                          "cargo test", "go test", "jest", ...)
    priority              integer; higher wins under multi-match. Mirrors
                          the historical if-ladder order so monorepo
                          fixtures resolve identically.
    detect(workspace)     → DetectionResult
    discover_tests(workspace) → list[str]
    run_shadow_build(workspace, timeout) → ShadowBuildResult
    parse_failure(output) → list[ParsedFinding]

The adapters are class-method based — no instance state — so they compose
cleanly with the registry and are trivial to mock in tests.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol

from intake.hardened_runner import run as _hardened_run

# ---------------------------------------------------------------------------
# Dataclasses returned by adapter methods
# ---------------------------------------------------------------------------


@dataclass
class DetectionResult:
    matched: bool
    confidence: float  # 0.0 (no match) .. 1.0 (unambiguous match)
    evidence_files: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ShadowBuildResult:
    ran: bool  # did we actually invoke the toolchain?
    success: bool  # exit code 0?
    output: str  # captured stdout+stderr, trimmed to 4000 chars
    tool_missing: bool = False
    timed_out: bool = False


@dataclass
class ParsedFinding:
    severity: str  # "error" | "warning"
    category: str  # "compilation" | "test_failure"
    message: str
    file: str = ""
    line: int = 0


# ---------------------------------------------------------------------------
# Internal helper — bounded subprocess call.
# As of HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001 this routes through
# intake.hardened_runner.run, which enforces: list[str] argv, workspace-
# scoped cwd, scrubbed env, no Docker, no shell=True, structured failure.
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path, timeout: int) -> ShadowBuildResult:
    result = _hardened_run(cmd, workspace=cwd, timeout=timeout)
    if result.blocked:
        return ShadowBuildResult(
            ran=False,
            success=False,
            output=result.reason or result.stderr,
        )
    if result.tool_missing:
        return ShadowBuildResult(
            ran=False,
            success=False,
            output=result.stderr or f"tool not found on PATH: {cmd[0]}",
            tool_missing=True,
        )
    if result.timed_out:
        return ShadowBuildResult(
            ran=False,
            success=False,
            output=result.stderr or f"timed out after {timeout}s",
            timed_out=True,
        )
    out = (
        result.stdout + ("\n" if result.stdout and result.stderr else "") + result.stderr
    ).strip()
    return ShadowBuildResult(
        ran=True,
        success=(result.exit_code == 0),
        output=out[:4000],
    )


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------


class BuildAdapter(Protocol):
    """Adapter contract. Class-method based: no instance state."""

    name: ClassVar[str]
    build_system_id: ClassVar[str]
    test_framework_id: ClassVar[str]
    priority: ClassVar[int]

    @classmethod
    def detect(cls, workspace: Path) -> DetectionResult: ...

    @classmethod
    def discover_tests(cls, workspace: Path) -> list[str]: ...

    @classmethod
    def run_shadow_build(cls, workspace: Path, timeout: int = 60) -> ShadowBuildResult: ...

    @classmethod
    def parse_failure(cls, output: str) -> list[ParsedFinding]: ...


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


class RustAdapter:
    name: ClassVar[str] = "Rust"
    build_system_id: ClassVar[str] = "cargo"
    test_framework_id: ClassVar[str] = "cargo test"
    # Highest priority: Cargo.toml is unique-named, unambiguous.
    priority: ClassVar[int] = 100

    @classmethod
    def detect(cls, workspace: Path) -> DetectionResult:
        if (workspace / "Cargo.toml").is_file():
            return DetectionResult(matched=True, confidence=1.0, evidence_files=["Cargo.toml"])
        return DetectionResult(matched=False, confidence=0.0)

    @classmethod
    def discover_tests(cls, workspace: Path) -> list[str]:
        return ["cargo test -- --test-threads=1", "cargo test --doc"]

    @classmethod
    def run_shadow_build(cls, workspace: Path, timeout: int = 60) -> ShadowBuildResult:
        return _run(["cargo", "check", "--message-format=short"], workspace, timeout)

    @classmethod
    def parse_failure(cls, output: str) -> list[ParsedFinding]:
        findings: list[ParsedFinding] = []
        # cargo error format: "error[E0308]: ..." appears first; the
        # location follows on the next "  --> path:line:col" line. We
        # therefore annotate the most-recent un-located finding when we
        # see the location.
        loc_pat = re.compile(r"-->\s*(.+?):(\d+):\d+")
        for raw in output.splitlines():
            line = raw.strip()
            if line.startswith(("error[", "error:")):
                findings.append(
                    ParsedFinding(
                        severity="error",
                        category="compilation",
                        message=line,
                    )
                )
                continue
            m = loc_pat.search(line)
            if m and findings and not findings[-1].file:
                findings[-1].file = m.group(1)
                findings[-1].line = int(m.group(2))
        return findings


class GoAdapter:
    name: ClassVar[str] = "Go"
    build_system_id: ClassVar[str] = "go"
    test_framework_id: ClassVar[str] = "go test"
    priority: ClassVar[int] = 95

    @classmethod
    def detect(cls, workspace: Path) -> DetectionResult:
        if (workspace / "go.mod").is_file():
            return DetectionResult(matched=True, confidence=1.0, evidence_files=["go.mod"])
        return DetectionResult(matched=False, confidence=0.0)

    @classmethod
    def discover_tests(cls, workspace: Path) -> list[str]:
        return ["go test ./... -count=1 -short"]

    @classmethod
    def run_shadow_build(cls, workspace: Path, timeout: int = 60) -> ShadowBuildResult:
        return _run(["go", "build", "./..."], workspace, timeout)

    @classmethod
    def parse_failure(cls, output: str) -> list[ParsedFinding]:
        findings: list[ParsedFinding] = []
        pat = re.compile(r"^(.+\.go):(\d+):(?:\d+:)?\s*(.+)$")
        for raw in output.splitlines():
            line = raw.strip()
            m = pat.match(line)
            if m:
                findings.append(
                    ParsedFinding(
                        severity="error",
                        category="compilation",
                        message=m.group(3),
                        file=m.group(1),
                        line=int(m.group(2)),
                    )
                )
        return findings


class PythonAdapter:
    name: ClassVar[str] = "Python"
    build_system_id: ClassVar[str] = "pip"
    test_framework_id: ClassVar[str] = "pytest"
    priority: ClassVar[int] = 50

    _MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")

    @classmethod
    def detect(cls, workspace: Path) -> DetectionResult:
        evidence = [m for m in cls._MANIFESTS if (workspace / m).is_file()]
        if not evidence:
            return DetectionResult(matched=False, confidence=0.0)
        # confidence: 0.65 for one signal, +0.15 per additional
        conf = min(1.0, 0.65 + 0.15 * (len(evidence) - 1))
        return DetectionResult(matched=True, confidence=conf, evidence_files=evidence)

    @classmethod
    def discover_tests(cls, workspace: Path) -> list[str]:
        suggestions: list[str] = []
        has_tests_dir = (workspace / "tests").is_dir()
        has_test_files = any(
            True for _ in workspace.rglob("test_*.py") if "__pycache__" not in str(_)
        )
        if has_tests_dir or has_test_files:
            suggestions.append("pytest -x --tb=short -q")
        return suggestions

    @classmethod
    def run_shadow_build(cls, workspace: Path, timeout: int = 60) -> ShadowBuildResult:
        errors: list[str] = []
        # Cap at 200 files to bound execution; mirrors codebase_explorer behavior.
        py_files = [
            p
            for p in workspace.rglob("*.py")
            if not any(
                skip in p.parts
                for skip in ("__pycache__", ".venv", "venv", "site-packages", "build", "dist")
            )
        ][:200]
        for f in py_files:
            # Per-file py_compile, routed through the hardened runner.
            r = _hardened_run(
                [sys.executable, "-m", "py_compile", str(f)],
                workspace=workspace,
                timeout=10,
            )
            if r.blocked:
                errors.append(f"{f.name}: blocked by hardened runner: {r.reason}")
            elif r.timed_out:
                errors.append(f"{f.name}: py_compile timed out")
            elif r.tool_missing:
                # If the Python interpreter itself isn't found, surface once
                # and stop iterating — every file would fail the same way.
                errors.append(f"py_compile tool missing: {r.stderr}")
                break
            elif r.exit_code != 0:
                rel = str(f.relative_to(workspace))
                errors.append(f"{rel}: {r.stderr.strip()}")
        out = "\n".join(errors[:20])
        return ShadowBuildResult(ran=True, success=(not errors), output=out)

    @classmethod
    def parse_failure(cls, output: str) -> list[ParsedFinding]:
        findings: list[ParsedFinding] = []
        for raw in output.splitlines():
            line = raw.strip()
            if "FAILED" in line:
                findings.append(
                    ParsedFinding(
                        severity="error",
                        category="test_failure",
                        message=line,
                    )
                )
            elif "SyntaxError" in line or "IndentationError" in line:
                findings.append(
                    ParsedFinding(
                        severity="error",
                        category="compilation",
                        message=line,
                    )
                )
        return findings


class NodeAdapter:
    name: ClassVar[str] = "Node/TypeScript"
    build_system_id: ClassVar[str] = "npm"
    test_framework_id: ClassVar[str] = "jest"  # default; refined from package.json devDeps
    priority: ClassVar[int] = 40

    @classmethod
    def detect(cls, workspace: Path) -> DetectionResult:
        if (workspace / "package.json").is_file():
            return DetectionResult(matched=True, confidence=1.0, evidence_files=["package.json"])
        return DetectionResult(matched=False, confidence=0.0)

    @classmethod
    def discover_tests(cls, workspace: Path) -> list[str]:
        pkg = workspace / "package.json"
        suggestions: list[str] = []
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ["npm test"]
        dev = data.get("devDependencies", {}) or {}
        if "vitest" in dev:
            suggestions.append("vitest run")
        elif "mocha" in dev:
            suggestions.append("mocha --bail")
        elif "jest" in dev:
            suggestions.append("jest --bail")
        if (data.get("scripts", {}) or {}).get("test") and not suggestions:
            suggestions.append("npm test")
        return suggestions or ["npm test"]

    @classmethod
    def refine_test_framework_id(cls, workspace: Path) -> str:
        """Helper for callers that want the legacy ('npm','jest'|'vitest'|'mocha')
        return value. Encapsulates the original detect_build_system npm refinement."""
        pkg = workspace / "package.json"
        try:
            dev = json.loads(pkg.read_text(encoding="utf-8")).get("devDependencies", {}) or {}
        except (OSError, json.JSONDecodeError):
            return cls.test_framework_id
        if "vitest" in dev:
            return "vitest"
        if "mocha" in dev:
            return "mocha"
        if "jest" in dev:
            return "jest"
        return cls.test_framework_id

    @classmethod
    def run_shadow_build(cls, workspace: Path, timeout: int = 60) -> ShadowBuildResult:
        return _run(["npm", "run", "build", "--if-present"], workspace, timeout)

    @classmethod
    def parse_failure(cls, output: str) -> list[ParsedFinding]:
        findings: list[ParsedFinding] = []
        for raw in output.splitlines():
            line = raw.strip()
            # TypeScript-style: file.ts(L,C): error TS####:
            tsc = re.match(r"^(.+?)\((\d+),\d+\):\s*error\s+TS\d+:\s*(.+)$", line)
            if tsc:
                findings.append(
                    ParsedFinding(
                        severity="error",
                        category="compilation",
                        message=tsc.group(3),
                        file=tsc.group(1),
                        line=int(tsc.group(2)),
                    )
                )
                continue
            if "Error:" in line or line.startswith("ERROR"):
                findings.append(
                    ParsedFinding(
                        severity="error",
                        category="compilation",
                        message=line,
                    )
                )
        return findings


class JavaMavenAdapter:
    name: ClassVar[str] = "Java/Maven"
    build_system_id: ClassVar[str] = "maven"
    test_framework_id: ClassVar[str] = "maven test"
    priority: ClassVar[int] = 30

    @classmethod
    def detect(cls, workspace: Path) -> DetectionResult:
        if (workspace / "pom.xml").is_file():
            return DetectionResult(matched=True, confidence=1.0, evidence_files=["pom.xml"])
        return DetectionResult(matched=False, confidence=0.0)

    @classmethod
    def discover_tests(cls, workspace: Path) -> list[str]:
        return ["mvn test -q"]

    @classmethod
    def run_shadow_build(cls, workspace: Path, timeout: int = 60) -> ShadowBuildResult:
        return _run(["mvn", "compile", "-q"], workspace, timeout)

    @classmethod
    def parse_failure(cls, output: str) -> list[ParsedFinding]:
        findings: list[ParsedFinding] = []
        for raw in output.splitlines():
            line = raw.strip()
            if line.startswith("[ERROR]") or "BUILD FAILURE" in line:
                findings.append(
                    ParsedFinding(
                        severity="error",
                        category="compilation",
                        message=line,
                    )
                )
        return findings


class JavaGradleAdapter:
    name: ClassVar[str] = "Java/Gradle"
    build_system_id: ClassVar[str] = "gradle"
    test_framework_id: ClassVar[str] = "gradle test"
    priority: ClassVar[int] = 30

    @classmethod
    def detect(cls, workspace: Path) -> DetectionResult:
        evidence = [m for m in ("build.gradle", "build.gradle.kts") if (workspace / m).is_file()]
        if evidence:
            return DetectionResult(matched=True, confidence=1.0, evidence_files=evidence)
        return DetectionResult(matched=False, confidence=0.0)

    @classmethod
    def discover_tests(cls, workspace: Path) -> list[str]:
        return ["gradle test -q"]

    @classmethod
    def run_shadow_build(cls, workspace: Path, timeout: int = 60) -> ShadowBuildResult:
        return _run(["gradle", "compileJava", "-q"], workspace, timeout)

    @classmethod
    def parse_failure(cls, output: str) -> list[ParsedFinding]:
        findings: list[ParsedFinding] = []
        for raw in output.splitlines():
            line = raw.strip()
            if "error:" in line.lower() or "FAILED" in line:
                findings.append(
                    ParsedFinding(
                        severity="error",
                        category="compilation",
                        message=line,
                    )
                )
        return findings


class UnknownAdapter:
    """Fallback. Only selected by the registry when nothing else matches."""

    name: ClassVar[str] = "Unknown"
    build_system_id: ClassVar[str] = "unknown"
    test_framework_id: ClassVar[str] = "unknown"
    priority: ClassVar[int] = -1  # never wins a multi-match

    @classmethod
    def detect(cls, workspace: Path) -> DetectionResult:
        # detect() returns NOT MATCHED so the registry knows to fall back
        # explicitly. The registry constructs an UnknownAdapter selection
        # itself when nothing else matched.
        return DetectionResult(matched=False, confidence=0.0, notes="no build manifest detected")

    @classmethod
    def discover_tests(cls, workspace: Path) -> list[str]:
        return []

    @classmethod
    def run_shadow_build(cls, workspace: Path, timeout: int = 60) -> ShadowBuildResult:
        return ShadowBuildResult(
            ran=False,
            success=True,
            output="no shadow build for unknown project type",
        )

    @classmethod
    def parse_failure(cls, output: str) -> list[ParsedFinding]:
        return []


# ---------------------------------------------------------------------------
# Built-in registry contents
# ---------------------------------------------------------------------------

ADAPTERS_BUILTIN: Sequence[type[BuildAdapter]] = (
    RustAdapter,
    GoAdapter,
    PythonAdapter,
    NodeAdapter,
    JavaMavenAdapter,
    JavaGradleAdapter,
    UnknownAdapter,
)
