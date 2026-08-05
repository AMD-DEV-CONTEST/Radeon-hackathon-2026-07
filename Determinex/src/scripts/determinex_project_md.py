#!/usr/bin/env python3
"""determinex_project_md.py -- generate the per-project instructions file every LLM/agent tool
reads first (Claude Code's CLAUDE.md, Gemini CLI's GEMINI.md, OpenAI Codex's AGENTS.md, Cursor's
.cursorrules, ...), for every project Determinex builds or opens.

Ryan's direct instruction (2026-07-27): "The projects no matter the llms, should all default to
the project md... its where all llms go for context, layout, marching orders, etc... You should
know what the perfect project md looks like, what questions should auto ask based on the initial
information, and sub clarifying information."

Design, three pieces:

1. ONE canonical file, AGENTS.md -- the emerging cross-tool convention (OpenAI Codex CLI and a
   growing set of other agentic tools read it natively), and already this exact repo's own
   pattern for frontend/ (frontend/AGENTS.md holds the real content; frontend/CLAUDE.md is one
   line: "@AGENTS.md"). Every fact in it is DERIVED, not invented -- from determinex_ingest.py's
   TaskUnderstanding (language/build_system/harness/oracle, already-inferred no-LLM) plus the
   build spec (Goal/Language/Constraints/Files) already produced by spec_generator.py. This
   module adds no new inference step for facts ingest() can already answer; it only formats them.

2. Tool-specific files. CLAUDE.md is written as `@AGENTS.md` -- verified live in THIS session
   (this repo's own frontend/CLAUDE.md resolves that way through the harness reading it right
   now) -- so it is a one-line pointer, not a duplicate. Every other tool file (GEMINI.md,
   .cursorrules, CODEX.md) is a FULL copy of the same content: import-syntax support for those
   tools is not verified, and a silent no-op pointer would be worse than a duplicated-but-working
   file. Existing files are NEVER overwritten -- write_project_md_files() skips any target that
   already exists, so a user's own hand-written instructions are never clobbered.

3. infer_project_convention_questions() -- the "auto ask, sub-clarify" half. Everything ingest()
   can derive (language, build/test commands, existing behaviors) is filled in with NO question
   asked. Only the small set of conventions that are genuinely NOT inferable from source/spec
   alone -- API surface shape, lint strictness, testing philosophy -- become explicit questions,
   each carrying a `why_it_matters` so a caller (the setup wizard, idea_oracle's conversation)
   can show the user why it's asking rather than just a bare prompt. This deliberately does NOT
   reimplement idea_oracle.py's LLM-driven discovery conversation (audit-before-build: that
   already exists and works) -- it is a small, separate, purely-deterministic supplement scoped
   to project-md conventions specifically.

CLI:
    python scripts/determinex_project_md.py generate <project_root> [--answers answers.json]
    python scripts/determinex_project_md.py questions <project_root>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from determinex_ingest import Spec, TaskUnderstanding, ingest  # noqa: E402

# Concrete build/test/lint commands per language. Deliberately a plain, hand-maintained table
# rather than sourced from determinex_oracle.py's Oracle.verify_fn: those are arbitrary Python
# (subprocess call sequences, JUnit XML parsing), not a single extractable command string, and
# reverse-engineering one out of each would be a much larger and more fragile undertaking than
# maintaining the well-known standard command for each ecosystem directly.
LANGUAGE_COMMANDS: dict[str, dict[str, str]] = {
    "rust": {"build": "cargo build", "test": "cargo test", "lint": "cargo clippy"},
    "go": {"build": "go build ./...", "test": "go test ./...", "lint": "go vet ./..."},
    "python": {"build": "pip install -e .", "test": "pytest", "lint": "ruff check ."},
    "typescript": {"build": "npm run build", "test": "npm test", "lint": "npm run lint"},
    "javascript": {"build": "npm run build", "test": "npm test", "lint": "npm run lint"},
    "java": {"build": "gradle build", "test": "gradle test", "lint": ""},
    "kotlin": {"build": "gradle build", "test": "gradle test", "lint": ""},
    "csharp": {"build": "dotnet build", "test": "dotnet test", "lint": ""},
    "cpp": {"build": "cmake --build build", "test": "ctest --test-dir build", "lint": ""},
    "c": {"build": "make", "test": "make test", "lint": ""},
    "ruby": {"build": "bundle install", "test": "bundle exec rspec", "lint": "rubocop"},
    "php": {"build": "composer install", "test": "phpunit", "lint": "phpcs"},
    "swift": {"build": "swift build", "test": "swift test", "lint": ""},
}

# Short system/harness names matching determinex_ingest.py's own convention (_detect_build /
# _detect_harness return "cargo"/"go-test"/etc, not a full command string) -- kept separate from
# LANGUAGE_COMMANDS so the "Stack" section reads the same whether a project came from ingest()
# on real source or spec_to_understanding() on a fresh spec with no source yet.
_BUILD_SYSTEM_NAMES: dict[str, str] = {
    "rust": "cargo",
    "go": "go",
    "python": "pip",
    "typescript": "npm",
    "javascript": "npm",
    "java": "gradle",
    "kotlin": "gradle",
    "csharp": "dotnet",
    "cpp": "cmake",
    "c": "make",
    "ruby": "bundler",
    "php": "composer",
    "swift": "swift-pm",
}
_HARNESS_NAMES: dict[str, str] = {
    "rust": "cargo-test",
    "go": "go-test",
    "python": "pytest",
    "typescript": "npm-test",
    "javascript": "npm-test",
    "java": "gradle-test",
    "kotlin": "gradle-test",
    "csharp": "dotnet-test",
    "cpp": "ctest",
    "c": "make-test",
    "ruby": "rspec",
    "php": "phpunit",
    "swift": "swift-test",
}

# Files every common LLM/agent tool reads for project instructions, in write order.
# CLAUDE.md gets the pointer form (see module docstring); everything else gets a full copy.
_POINTER_TARGETS = ("CLAUDE.md",)
_FULL_COPY_TARGETS = ("GEMINI.md", ".cursorrules", "CODEX.md")
CANONICAL_FILENAME = "AGENTS.md"


@dataclass
class ConventionQuestion:
    id: str
    question: str
    why_it_matters: str
    options: list[str] = field(default_factory=list)  # empty = free-text


def infer_project_convention_questions(
    understanding: TaskUnderstanding,
) -> list[ConventionQuestion]:
    """The bounded, deterministic 'what to ask' list. Every question here is something
    determinex_ingest.py's TaskUnderstanding genuinely cannot answer from source/spec alone --
    if a future ingest() improvement CAN derive one of these (e.g. detecting a public API from
    exported symbols), remove the question here rather than leave a redundant one."""
    qs = [
        ConventionQuestion(
            id="api_surface",
            question="Is this a library (other code imports it) or an application "
            "(it's the thing that runs)?",
            why_it_matters="Changes whether backward-compatibility and public-API stability "
            "matter, and whether the project-md should warn against breaking "
            "signatures other code depends on.",
            options=["library", "application", "both"],
        ),
        ConventionQuestion(
            id="lint_strictness",
            question="Should lint/format failures block a build, or just warn?",
            why_it_matters="Determines whether the generated marching-orders section tells an "
            "agent to treat lint output as a hard gate or an advisory pass.",
            options=["blocking", "advisory"],
        ),
        ConventionQuestion(
            id="test_philosophy",
            question="Unit-test-first, integration-test-first, or a mix?",
            why_it_matters="Shapes what 'done' means when an agent adds a feature -- whether it "
            "should reach for a narrow unit test or a broader end-to-end one by "
            "default.",
            options=["unit-first", "integration-first", "mixed"],
        ),
    ]
    # A synthesized/no-test-suite project has one more real unknown: whether the user wants
    # Determinex's synthesize_oracle() to manufacture a test suite automatically, or wants to
    # write the first tests by hand before any agent touches the code.
    if not understanding.has_tests:
        qs.append(
            ConventionQuestion(
                id="oracle_synthesis",
                question="No test suite was found. Synthesize one automatically (example + "
                "property tests), or do you want to write the first tests yourself?",
                why_it_matters="Determinex's compiler-oracle contract requires SOME ground truth to "
                "verify against; this decides whether that ground truth is "
                "machine-synthesized now or supplied by you first.",
                options=["synthesize", "i_will_write_tests"],
            )
        )
    return qs


def spec_to_understanding(spec_text: str, language: str, root: str = "") -> TaskUnderstanding:
    """Adapt a fresh hive build spec (## Goal / ## Language / ## Constraints / ## Files -- the
    format `determinex_hive.py new-session` takes) into the same TaskUnderstanding shape
    generate_agents_md() already consumes, so a BRAND NEW project (no source exists yet to
    ingest()) gets a real project-md from its spec instead of needing a second code path.

    has_tests=False always -- correct by construction: at `new-session` time nothing has been
    built yet, so there is no test suite regardless of what the spec eventually leads to.
    """
    goal_m = re.search(r"##\s*Goal\s*\n(.*?)(?:\n##|\Z)", spec_text, re.DOTALL)
    summary = goal_m.group(1).strip() if goal_m else ""

    constraints_m = re.search(r"##\s*Constraints\s*\n(.*?)(?:\n##|\Z)", spec_text, re.DOTALL)
    invariants = []
    if constraints_m:
        for line in constraints_m.group(1).splitlines():
            line = line.strip().lstrip("-*").strip()
            if line:
                invariants.append(line)

    lang_lower = language.lower()
    return TaskUnderstanding(
        root=root,
        language=language,
        language_census={language: 1},
        build_system=_BUILD_SYSTEM_NAMES.get(lang_lower, "unknown"),
        harness=_HARNESS_NAMES.get(lang_lower, "unknown"),
        has_tests=False,
        oracle=language,
        oracle_available=True,
        spec=Spec(summary=summary, invariants=invariants),
    )


def _commands_section(language: str) -> str:
    cmds = LANGUAGE_COMMANDS.get(language.lower())
    if not cmds:
        return (
            f"- No known standard command set for `{language}` -- confirm build/test/lint "
            f"commands with the project owner before assuming any."
        )
    lines = [f"- Build: `{cmds['build']}`", f"- Test: `{cmds['test']}`"]
    if cmds.get("lint"):
        lines.append(f"- Lint: `{cmds['lint']}`")
    return "\n".join(lines)


def generate_agents_md(
    understanding: TaskUnderstanding,
    project_name: str,
    answers: dict[str, str] | None = None,
) -> str:
    """Build the canonical AGENTS.md content. Every fact is either directly from
    `understanding` (deterministic, no-LLM, from determinex_ingest.ingest()) or from an explicit
    answer in `answers` (from infer_project_convention_questions()) -- nothing here is invented.
    """
    answers = answers or {}
    spec = understanding.spec
    lines: list[str] = []

    lines.append(f"# {project_name}")
    lines.append("")
    if spec.summary:
        lines.append(spec.summary.strip())
        lines.append("")

    lines.append("## Stack")
    lines.append(f"- Language: **{understanding.language}**")
    lines.append(f"- Build system: {understanding.build_system}")
    lines.append(f"- Test harness: {understanding.harness}")
    lines.append("")

    lines.append("## Commands")
    lines.append(_commands_section(understanding.language))
    lines.append("")

    if spec.invariants:
        lines.append("## Invariants (must hold)")
        for inv in spec.invariants[:20]:
            lines.append(f"- {inv}")
        lines.append("")

    if spec.behaviors:
        lines.append("## Observed behaviors")
        for b in spec.behaviors[:20]:
            lines.append(f"- {b}")
        lines.append("")

    if spec.cli_surface:
        lines.append("## CLI surface")
        for c in spec.cli_surface[:20]:
            lines.append(f"- `{c}`")
        lines.append("")

    api_surface = answers.get("api_surface")
    if api_surface:
        lines.append("## API surface")
        if api_surface == "library":
            lines.append(
                "This is a **library** -- other code imports it. Treat public "
                "signatures as load-bearing; don't break them without a version bump."
            )
        elif api_surface == "application":
            lines.append(
                "This is an **application** -- it is the thing that runs. Public "
                "function signatures are internal; the CLI/API contract with its "
                "users is what must stay stable."
            )
        else:
            lines.append(
                "This project has **both** library and application surfaces -- treat "
                "exported symbols as load-bearing, internal wiring as free to change."
            )
        lines.append("")

    lint_strictness = answers.get("lint_strictness")
    test_philosophy = answers.get("test_philosophy")
    if lint_strictness or test_philosophy:
        lines.append("## Conventions")
        if lint_strictness == "blocking":
            lines.append(
                "- Lint/format failures are a hard gate -- fix them before considering "
                "a change done."
            )
        elif lint_strictness == "advisory":
            lines.append("- Lint/format output is advisory -- worth fixing, not a blocker.")
        if test_philosophy:
            label = {
                "unit-first": "Prefer a narrow unit test for new logic.",
                "integration-first": "Prefer a broader end-to-end test over a narrow unit test.",
                "mixed": "Use unit tests for logic, integration tests for behavior across "
                "components.",
            }.get(test_philosophy)
            if label:
                lines.append(f"- {label}")
        lines.append("")

    lines.append("## Ground truth")
    lines.append(
        "This project is built and verified through Determinex's Compiler Oracle: every change "
        "is checked by a real compiler run or test execution, never by an LLM's own claim that "
        "it worked. Whichever model or agent is working on this project, treat a failing "
        "build/test as the ground truth over your own assessment of the change."
    )
    if understanding.oracle == "SYNTHESIZE" or not understanding.has_tests:
        oracle_choice = answers.get("oracle_synthesis")
        if oracle_choice == "synthesize":
            lines.append(
                "No test suite existed at project creation; one was synthesized "
                "(`determinex_synthesize.py`) as the ground truth this contract refers to."
            )
        else:
            lines.append(
                "No test suite exists yet. Until one is added, there is no ground truth to "
                "verify against -- write tests before trusting any agent's code as correct."
            )
    lines.append("")

    lines.append("## Marching orders")
    lines.append("1. Read this file before making any change.")
    lines.append(
        f"2. Run the test command above ({_first_test_cmd(understanding.language)}) "
        "before AND after your change -- confirm the baseline, then confirm you didn't "
        "break it."
    )
    lines.append(
        "3. Match the existing code's own conventions in files you touch over any "
        "generic style preference."
    )
    lines.append("4. Don't add scope beyond what was asked.")
    lines.append("")

    return "\n".join(lines)


def _first_test_cmd(language: str) -> str:
    cmds = LANGUAGE_COMMANDS.get(language.lower())
    return f"`{cmds['test']}`" if cmds else "(confirm the test command with the project owner)"


def write_project_md_files(root: Path, content: str) -> list[Path]:
    """Write AGENTS.md (full content) + tool-specific files, skipping any target that already
    exists so a user's own hand-written instructions are never overwritten. Returns the list of
    paths actually written (not skipped)."""
    root = Path(root)
    written: list[Path] = []

    canonical = root / CANONICAL_FILENAME
    if not canonical.exists():
        canonical.write_text(content, encoding="utf-8")
        written.append(canonical)

    for name in _POINTER_TARGETS:
        p = root / name
        if not p.exists():
            p.write_text(f"@{CANONICAL_FILENAME}\n", encoding="utf-8")
            written.append(p)

    for name in _FULL_COPY_TARGETS:
        p = root / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")
            written.append(p)

    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Ingest a project and write its AGENTS.md + tool files")
    g.add_argument("root", help="Project root directory")
    g.add_argument("--name", help="Project name (default: directory name)")
    g.add_argument("--answers", help="Path to a JSON file of convention-question answers")

    q = sub.add_parser("questions", help="Print the convention questions for a project")
    q.add_argument("root", help="Project root directory")

    args = ap.parse_args()
    root = Path(args.root).resolve()

    understanding = ingest(root)

    if args.cmd == "questions":
        qs = infer_project_convention_questions(understanding)
        print(json.dumps([q.__dict__ for q in qs], indent=2))
        return 0

    answers = {}
    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))

    name = args.name or root.name
    content = generate_agents_md(understanding, name, answers)
    written = write_project_md_files(root, content)
    if written:
        print(f"Wrote {len(written)} file(s):")
        for p in written:
            print(f"  {p}")
    else:
        print("Nothing written -- all target files already exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
