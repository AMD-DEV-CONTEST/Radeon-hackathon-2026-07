"""Tests for scripts/determinex_project_md.py -- the per-project AGENTS.md/CLAUDE.md/GEMINI.md
generator. Built 2026-07-27 per Ryan's direct instruction that every project Determinex builds
or opens should default to a project-instructions file readable by any LLM/agent tool.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from determinex_ingest import Spec, TaskUnderstanding  # noqa: E402
from determinex_project_md import (  # noqa: E402
    CANONICAL_FILENAME,
    LANGUAGE_COMMANDS,
    generate_agents_md,
    infer_project_convention_questions,
    spec_to_understanding,
    write_project_md_files,
)


def _understanding(**overrides) -> TaskUnderstanding:
    base = dict(
        root="/tmp/proj",
        language="rust",
        language_census={"rust": 5},
        build_system="cargo",
        harness="cargo-test",
        has_tests=True,
        oracle="rust",
        oracle_available=True,
        spec=Spec(
            summary="A line-counting library.",
            cli_surface=["linecounter --file <path>"],
            behaviors=["returns Err on missing file", "counts newline-terminated lines"],
            invariants=["never panics on empty input"],
        ),
    )
    base.update(overrides)
    return TaskUnderstanding(**base)


def test_generate_includes_derived_facts_not_invented_ones():
    """Every fact in the output must trace to TaskUnderstanding or an explicit answer -- this
    is what keeps the generator honest instead of an LLM hallucinating project conventions."""
    u = _understanding()
    md = generate_agents_md(u, "LineCounter")
    assert "rust" in md
    assert "cargo build" in md
    assert "cargo test" in md
    assert "cargo clippy" in md
    assert "returns Err on missing file" in md
    assert "never panics on empty input" in md
    assert "linecounter --file <path>" in md


def test_ground_truth_section_always_present():
    """The compiler-oracle contract is the one thing every generated file must say, regardless
    of language -- it's what makes 'any LLM' safe to point at a Determinex-built project."""
    u = _understanding()
    md = generate_agents_md(u, "X")
    assert "Compiler Oracle" in md
    assert "never by an LLM's own claim" in md


def test_no_test_suite_flags_missing_ground_truth_without_an_answer():
    u = _understanding(has_tests=False, oracle="SYNTHESIZE")
    md = generate_agents_md(u, "X")
    assert "No test suite exists yet" in md


def test_no_test_suite_with_synthesize_answer_says_so():
    u = _understanding(has_tests=False, oracle="SYNTHESIZE")
    md = generate_agents_md(u, "X", answers={"oracle_synthesis": "synthesize"})
    assert "was synthesized" in md


def test_unknown_language_does_not_fabricate_a_command():
    u = _understanding(language="cobol", build_system="unknown", harness="unknown")
    md = generate_agents_md(u, "X")
    assert "No known standard command set for `cobol`" in md
    assert "confirm build/test/lint commands" in md


def test_api_surface_answer_changes_the_generated_guidance():
    u = _understanding()
    lib_md = generate_agents_md(u, "X", answers={"api_surface": "library"})
    app_md = generate_agents_md(u, "X", answers={"api_surface": "application"})
    assert "load-bearing" in lib_md
    assert "internal; the CLI/API contract" in app_md
    assert lib_md != app_md


def test_write_creates_canonical_plus_pointer_plus_full_copies(tmp_path):
    u = _understanding()
    md = generate_agents_md(u, "X")
    written = write_project_md_files(tmp_path, md)
    names = {p.name for p in written}
    assert names == {CANONICAL_FILENAME, "CLAUDE.md", "GEMINI.md", ".cursorrules", "CODEX.md"}

    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.strip() == f"@{CANONICAL_FILENAME}"

    gemini = (tmp_path / "GEMINI.md").read_text(encoding="utf-8")
    assert gemini == md, "GEMINI.md must be a full copy, not a pointer (import support unverified)"


def test_write_never_overwrites_an_existing_file(tmp_path):
    """The single most important safety property: a user's own hand-written CLAUDE.md must
    never be silently clobbered by project-md generation."""
    (tmp_path / "CLAUDE.md").write_text("# Do not touch this\n", encoding="utf-8")
    u = _understanding()
    md = generate_agents_md(u, "X")
    written = write_project_md_files(tmp_path, md)

    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "# Do not touch this\n"
    assert all(p.name != "CLAUDE.md" for p in written)
    # Everything else with no prior file should still be written.
    assert (tmp_path / CANONICAL_FILENAME).exists()


def test_write_is_idempotent_second_run_writes_nothing(tmp_path):
    u = _understanding()
    md = generate_agents_md(u, "X")
    first = write_project_md_files(tmp_path, md)
    second = write_project_md_files(tmp_path, md)
    assert len(first) == 5
    assert second == []


def test_convention_questions_are_bounded_and_answer_ids_match_generator():
    """Every question id must correspond to something generate_agents_md() actually reads --
    otherwise a caller could collect an answer that silently does nothing."""
    u = _understanding()
    qs = infer_project_convention_questions(u)
    ids = {q.id for q in qs}
    assert ids == {"api_surface", "lint_strictness", "test_philosophy"}
    for q in qs:
        assert q.question
        assert q.why_it_matters


def test_missing_tests_adds_the_oracle_synthesis_question():
    u = _understanding(has_tests=False)
    qs = infer_project_convention_questions(u)
    ids = {q.id for q in qs}
    assert "oracle_synthesis" in ids


def test_has_tests_does_not_ask_the_oracle_synthesis_question():
    u = _understanding(has_tests=True)
    qs = infer_project_convention_questions(u)
    ids = {q.id for q in qs}
    assert "oracle_synthesis" not in ids


def test_language_commands_table_has_no_empty_build_or_test():
    """A silently-empty build/test command would produce a broken 'Build: ``' line."""
    for lang, cmds in LANGUAGE_COMMANDS.items():
        assert cmds.get("build"), f"{lang} missing a build command"
        assert cmds.get("test"), f"{lang} missing a test command"


SPEC_TEXT = """# Line Counter

## Goal
A Rust function that reads a file and counts lines.

## Language
rust

## Constraints
- No unsafe blocks
- Returns Result<usize, std::io::Error>

## Files
- src/lib.rs -- core logic
"""


def test_spec_to_understanding_extracts_goal_as_summary():
    u = spec_to_understanding(SPEC_TEXT, "rust")
    assert u.spec.summary == "A Rust function that reads a file and counts lines."


def test_spec_to_understanding_extracts_constraints_as_invariants():
    u = spec_to_understanding(SPEC_TEXT, "rust")
    assert u.spec.invariants == [
        "No unsafe blocks",
        "Returns Result<usize, std::io::Error>",
    ]


def test_spec_to_understanding_always_has_tests_false():
    """A brand-new project from a fresh spec has no test suite yet, by construction --
    regardless of what the spec's eventual build produces."""
    u = spec_to_understanding(SPEC_TEXT, "rust")
    assert u.has_tests is False


def test_spec_to_understanding_build_system_matches_ingest_short_names():
    """Must read the same as determinex_ingest.ingest() would report for a real cargo
    project ('cargo', not the full 'cargo build' command) so the Stack section is consistent
    regardless of which path (fresh spec vs ingested existing repo) produced it."""
    u = spec_to_understanding(SPEC_TEXT, "rust")
    assert u.build_system == "cargo"
    assert u.harness == "cargo-test"


def test_spec_to_understanding_feeds_a_working_generate_agents_md():
    u = spec_to_understanding(SPEC_TEXT, "rust")
    md = generate_agents_md(u, "LineCounter")
    assert "No unsafe blocks" in md
    assert "cargo build" in md
    assert "No test suite exists yet" in md


def test_spec_with_no_constraints_section_yields_empty_invariants():
    minimal = "# X\n\n## Goal\nDo a thing.\n\n## Language\npython\n"
    u = spec_to_understanding(minimal, "python")
    assert u.spec.invariants == []
    assert u.spec.summary == "Do a thing."
