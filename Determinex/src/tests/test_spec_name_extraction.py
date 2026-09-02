"""The function name is taken from how PEOPLE write, not how programmers write.

Found 2026-08-03 by running the README's own reproduction command as a judge would, with an
idea written the way an ordinary person writes one:

    "A function called solution that takes a list of integers and returns the second
     largest distinct value. For example solution([3, 1, 4, 4, 5]) returns 4, ..."

It returned **not solved**, with the proof *"no example or typeable invariant could be derived
from this idea… Add one concrete input/output example and re-run"* — against an idea containing
three of them.

The cause was one regex: `(?:function|def|fn|func)\\s+([a-zA-Z_]\\w*)` takes the next word, and
in that sentence the next word is **`called`**. Every example calls `solution(...)`, the
extractor was filtering on the name `called`, and so it matched nothing.

This is the worst shape a failure can take — it blames the user for the one thing they did
right, and it lands on the exact behaviour §3.0a of the submission is about. It survived
because every fixture in the suite was written by a programmer: `def foo(x)` and
`solution(numbers) returns ...` both parse correctly and always did.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from determinex_synthesize import parse_spec  # noqa: E402

EXAMPLES = " For example solution([3, 1, 4, 4, 5]) returns 4, solution([9, 9, 2]) returns 2."


@pytest.mark.parametrize(
    "prose",
    [
        "A function called solution that takes a list of integers.",
        "A function named solution that takes a list of integers.",
        "A function that takes a list of integers and returns the second largest.",
        "A function to find the second largest value in a list.",
        "Write a function which returns the second largest distinct value.",
        "I need a function for finding the second largest number.",
    ],
)
def test_ordinary_english_does_not_swallow_the_function_name(prose):
    """Each of these used to name the function `called`/`named`/`that`/`to`/`which`/`for`,
    and every one of them then extracted ZERO examples from text containing two."""
    spec = parse_spec(prose + EXAMPLES, "python")
    assert spec.name == "solution", f"named {spec.name!r} from {prose!r}"
    assert len(spec.examples) == 2


def test_the_name_the_examples_actually_call_wins():
    """Prose says one thing, the examples call another. The examples are what the oracle has
    to check, so they decide -- otherwise the oracle tests a function nobody wrote."""
    spec = parse_spec(
        "Write a function tally for this. For example count_items([1, 1]) returns 2.", "python"
    )
    assert spec.name == "count_items"
    assert len(spec.examples) == 1


def test_a_declaration_with_no_examples_still_names_the_function():
    """The guard must not overreach: when NOTHING is called anywhere, a declared name is the
    only name there is, and dropping it would rename every example-free spec to `solution`."""
    assert parse_spec("def merge_intervals(items): merges overlapping intervals.").name == (
        "merge_intervals"
    )
    assert parse_spec("Write a function called merge_intervals.").name == "merge_intervals"


def test_the_programmer_phrasings_that_always_worked_still_do():
    """Negative control. These were the only shapes the suite ever exercised, which is why the
    defect survived -- so they are pinned explicitly rather than assumed."""
    spec = parse_spec(
        "solution(numbers) returns the average. For example solution([1, 2, 3]) returns 2.0, "
        "solution([10]) returns 10.0, and solution([]) returns 0.0.",
        "python",
    )
    assert spec.name == "solution"
    assert len(spec.examples) == 3
    assert parse_spec("def add(a, b) -> int. add(2, 3) == 5").name == "add"


def test_a_filler_word_is_never_reported_as_the_function_name():
    for prose in ("a function that does things", "a function to do things", "the function is"):
        assert parse_spec(prose).name == "solution"
