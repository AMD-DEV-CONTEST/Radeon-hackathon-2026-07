"""A correctness suite that never ran must not be recorded as a pass.

WHY THIS EXISTS
---------------
`run_correctness_tests` signals "the tests did not run" by returning `(True, <signal>)` for five
distinct conditions. Both call sites in `hive/executor.py` tested the boolean FIRST:

    if _ct_passed:                      # matched -- every skip signal returns True
        step.correctness_result = "pass"
    elif _ct_output in _skip_signals:    # unreachable
        step.correctness_result = "skipped"

So a step whose tests never executed was recorded as `correctness_result="pass"`, which then fed two
consumers as a verification that had not happened:

  * `executor.py` `_tests_passed` -> credits the gamma channel of the adjudication score and sets
    `tests_exist=True`, changing the weighting;
  * `dspy_modules._load_trainset_from_sessions` -> `compiler_result="PASS"`, `score=1.0`.

The triggering conditions are ordinary: the Architect declared a harness path the Builder never
wrote; the language is not rust/go/python (TypeScript included -- and validate_project now genuinely
verifies TypeScript, so a whole TS session recorded every step's tests as passing); the run timed
out; the runner binary was missing.

The tuple being matched was also incomplete and used equality: `harness_read_error` was absent
entirely, and both `harness_read_error: {e}` and `runner_not_found: {e}` append an exception message,
so exact membership could never have matched them even had the branch been reachable.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

EXECUTOR = ROOT / "scripts" / "hive" / "executor.py"
COMPILER = ROOT / "scripts" / "hive" / "compiler.py"


def test_every_skip_signal_the_compiler_emits_is_recognised_by_the_executor():
    """Derived from compiler.py, not from a copied list -- a copied list is what drifted."""
    from hive.executor import _is_correctness_skip

    compiler_src = COMPILER.read_text(encoding="utf-8")
    # Signals are returned as `return True, "name"` or `return True, f"name: {e}"`.
    emitted = set(re.findall(r'return True,\s*f?"([a-z_]+)', compiler_src))
    assert emitted, "found no skip signals in compiler.py; this test is guarding nothing"

    for signal in sorted(emitted):
        assert _is_correctness_skip(signal), (
            f"compiler.py emits {signal!r} as a skip but the executor does not recognise it, so a "
            f"step whose tests never ran would be recorded as a correctness pass"
        )


def test_signals_carrying_an_exception_message_are_still_recognised():
    """`harness_read_error` and `runner_not_found` append ": {e}". Equality could never match them."""
    from hive.executor import _is_correctness_skip

    assert _is_correctness_skip("harness_read_error: [Errno 2] No such file or directory: 'x'")
    assert _is_correctness_skip("runner_not_found: [WinError 2] The system cannot find the file")


def test_a_real_test_failure_is_not_mistaken_for_a_skip():
    """The guard has to be narrow: misreading a genuine failure as a skip would discard the TDD
    enforcement that makes compiler-PASS insufficient."""
    from hive.executor import _is_correctness_skip

    for real_output in (
        "test_counts_lines ... FAILED\nassert 3 == 4",
        "REJECTED_SECURITY",
        "REJECTED_HALLUCINATED_TEST",
        "error[E0308]: mismatched types",
        "",
    ):
        assert not _is_correctness_skip(real_output), real_output


def test_both_call_sites_check_for_a_skip_before_checking_the_boolean():
    """Structural, because the ordering IS the bug. Reachability of the skip branch depends entirely
    on it being evaluated before the truthy `passed` flag."""
    src = EXECUTOR.read_text(encoding="utf-8")

    calls = [m.start() for m in re.finditer(r"run_correctness_tests\(", src)]
    assert len(calls) >= 2, f"expected at least two call sites, found {len(calls)}"

    for start in calls:
        window = src[start : start + 1400]
        skip_at = window.find("_is_correctness_skip(")
        assert skip_at != -1, (
            "a run_correctness_tests call site does not consult _is_correctness_skip; skip signals "
            "return (True, signal) and would be recorded as a pass"
        )
        # The skip test must come before whichever branch assigns "pass".
        pass_at = window.find('correctness_result = "pass"')
        if pass_at != -1:
            assert skip_at < pass_at, (
                "the skip check appears AFTER the branch that records a pass, so it is unreachable "
                "-- this is precisely the original defect"
            )


def test_a_skipped_step_is_excluded_from_the_monitor_trainset():
    """Not merely relabelled. Letting a skip fall through to the else branch would emit
    compiler_result="FAIL"/score=0.2 -- teaching the monitor that correct code is wrong, which is the
    mirror image of the original bug rather than a fix for it."""
    src = (ROOT / "scripts" / "hive" / "dspy_modules.py").read_text(encoding="utf-8")
    assert 'correctness_result") == "skipped"' in src, (
        "the trainset loader does not exclude skipped steps"
    )
    skip_at = src.index('correctness_result") == "skipped"')
    example_at = src.index("dspy.Example(")
    assert skip_at < example_at, "the exclusion must happen before the example is constructed"


def test_every_skip_signal_the_oracle_can_emit_is_recognised_as_a_skip():
    """The two lists must not drift apart.

    `compiler.run_correctness_tests` signals "the suite never ran" by returning `(True, <signal>)`,
    and `executor._is_correctness_skip` decides what counts as a skip from its own separate tuple of
    prefixes. Nothing links them, so a sixth signal added to the oracle would be truthy, unrecognised,
    and recorded as a verified pass -- reintroducing the original bug by addition rather than by edit.

    This derives the signals from the oracle's source and asserts each one is recognised. Same defect
    shape as the Agent Chat default model, which drifted from the installer's model list for exactly
    this reason.
    """
    import re
    import sys

    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from hive.executor import _is_correctness_skip  # noqa: PLC0415

    src = (scripts / "hive" / "compiler.py").read_text(encoding="utf-8")
    # `return True, "sig"` and `return True, f"sig: {e}"` -- capture the literal prefix of each.
    signals = set(re.findall(r'return\s+True,\s*f?"([a-z_]+)', src))
    assert signals, "no skip signals found in compiler.py; has run_correctness_tests been renamed?"

    unrecognised = sorted(s for s in signals if not _is_correctness_skip(s))
    assert not unrecognised, (
        f"the oracle can return these skip signals but executor._is_correctness_skip does not "
        f"recognise them, so each would be recorded as a verified pass: {unrecognised}. Add them to "
        f"_CORRECTNESS_SKIP_PREFIXES."
    )

    # And the reverse: a real compiler pass carries "" or real output, and must NOT be read as a skip.
    for genuine in ("", "ok", "1 test passed", "Compiling foo v0.1.0"):
        assert not _is_correctness_skip(genuine), (
            f"{genuine!r} is a genuine result but is being treated as a skip, which would discard "
            f"real verification"
        )
