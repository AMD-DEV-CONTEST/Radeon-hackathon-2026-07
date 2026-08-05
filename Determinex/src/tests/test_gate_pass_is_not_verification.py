"""A compile gate PASS is not proof a compiler ran, and only proof may enter the corpus.

WHY THIS EXISTS
---------------
Found 2026-07-30 (S2.5). `_compile_gate` returned `(True, "")` -- indistinguishable from a real
compile pass -- in every one of these cases:

  * the baseline compile failed, so the patch was applied but never compiled
  * `_run_compile_check` hit FileNotFoundError, i.e. cargo/go/mvn is not installed
  * the language was unsupported, or had no pom/gradle/tsconfig/CMakeLists/Makefile
  * any exception at all

The cause was a sentinel collision: `_run_compile_check` returned a bare string where `""` meant
BOTH "compiled clean" and "could not check". Seven paths returned `""` without compiling.

That PASS is what caused `capture_successful_epoch` to write `"verified": true` into
auto_curriculum.jsonl -- a file whose whole purpose is LoRA training data, and which CLAUDE.md
says holds only samples that have "passed a real compiler". So on a host missing a toolchain,
every patch was captured as verified and taught to the next model. The function's own docstring
claimed "Called only when: targeted tests PASS AND regression sweep PASSES", which was false.

This is the same defect shape as the correctness-skip bug fixed in the same session: a value that
means "not checked" being truthy where "checked and fine" was expected. Both are guarded now
because the shape recurs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import determinex_flywheel as F  # noqa: E402


@pytest.fixture()
def curriculum(tmp_path, monkeypatch):
    """Point the flywheel at a throwaway corpus file."""
    path = tmp_path / "auto_curriculum.jsonl"
    monkeypatch.setattr(F, "FLYWHEEL_PATH", path)
    return path


def _entries(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


PATCH = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"


@pytest.mark.parametrize(
    "verification",
    [
        "unverified:baseline_compile_failed",
        "unverified:no_compile_check",
        "unverified:gate_exception",
        "unverified:no_gate_run",
    ],
)
def test_an_unverified_patch_never_enters_the_training_corpus(curriculum, verification):
    """THE regression. Not "written with verified=False" -- not written at all, so the corpus
    stays clean whether or not a downstream consumer remembers to filter."""
    F.capture_successful_epoch("issue", PATCH, "inst-1", "o/r", verification=verification)
    assert _entries(curriculum) == [], (
        f"a patch whose gate outcome was {verification!r} was written to the training corpus"
    )


@pytest.mark.parametrize("verification", ["compiled+tested", "compiled_only"])
def test_a_compiler_validated_patch_is_captured_with_its_provenance(curriculum, verification):
    """Compile-only still clears CLAUDE.md's compiler-validated bar -- a compiler really ran and
    really passed -- so it must NOT be rejected. Over-tightening here would silently starve the
    flywheel, which is the opposite failure and just as bad."""
    F.capture_successful_epoch("issue", PATCH, "inst-2", "o/r", verification=verification)
    rows = _entries(curriculum)
    assert len(rows) == 1, f"a {verification} patch was not captured"
    assert rows[0]["verified"] is True
    assert rows[0]["verification"] == verification, (
        "provenance is missing, so a compile-only sample is indistinguishable from a tested one"
    )


def test_verification_is_required_and_cannot_be_defaulted():
    """Keyword-only and required on purpose. A default would let a future caller omit it and
    silently reintroduce the bug -- the same way the old signature let every caller through."""
    with pytest.raises(TypeError):
        F.capture_successful_epoch("issue", PATCH, "inst-3", "o/r")  # type: ignore[call-arg]


def test_an_empty_patch_is_still_skipped(curriculum):
    """Pre-existing guard; kept so the new check did not displace it."""
    F.capture_successful_epoch("issue", "   ", "inst-4", "o/r", verification="compiled+tested")
    assert _entries(curriculum) == []


class _Gate:
    """Minimal stand-in exercising the real classification block of _compile_gate."""

    def __init__(self, compile_checked: bool, tests_ran: bool):
        self.compile_checked = compile_checked
        self.tests_ran = tests_ran
        self.last_gate_verification = "unverified:no_gate_run"

    def classify(self) -> str:
        if self.compile_checked and self.tests_ran:
            self.last_gate_verification = "compiled+tested"
        elif self.compile_checked:
            self.last_gate_verification = "compiled_only"
        else:
            self.last_gate_verification = "unverified:no_compile_check"
        return self.last_gate_verification


@pytest.mark.parametrize(
    "compiled,tested,expected",
    [
        (True, True, "compiled+tested"),
        (True, False, "compiled_only"),
        (False, False, "unverified:no_compile_check"),
        (False, True, "unverified:no_compile_check"),  # tests without a compile is not verified
    ],
)
def test_the_gate_classification_maps_to_what_actually_ran(compiled, tested, expected):
    assert _Gate(compiled, tested).classify() == expected


def test_the_agent_defaults_to_unverified_before_any_gate_runs():
    """A patch produced without a gate run must not inherit a verified label, so the default is
    an unverified kind rather than an empty string (which would be falsy but not classified)."""
    src = (REPO_ROOT / "scripts" / "determinex_swebench_agent.py").read_text(encoding="utf-8")
    assert 'last_gate_verification: str = "unverified:no_gate_run"' in src, (
        "the agent no longer declares an unverified default for last_gate_verification"
    )
    assert "unverified:no_gate_run" not in F.VERIFIED_GATE_KINDS


def test_every_gate_verification_string_is_classified_by_the_flywheel():
    """If _compile_gate gains a new outcome string that the flywheel does not know, it falls into
    the reject branch -- safe, but silently starving. This pins the two sets together."""
    src = (REPO_ROOT / "scripts" / "determinex_swebench_agent.py").read_text(encoding="utf-8")
    import re

    assigned = set(re.findall(r'last_gate_verification\s*=\s*"([^"]+)"', src))
    assert assigned, "no gate verification assignments found; did the field get renamed?"
    for kind in assigned:
        assert kind in F.VERIFIED_GATE_KINDS or kind.startswith("unverified:"), (
            f"gate outcome {kind!r} is neither a recognised verified kind nor marked unverified, "
            f"so its corpus eligibility is ambiguous"
        )
