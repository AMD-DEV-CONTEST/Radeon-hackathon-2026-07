"""The Concept Lab interview must end when the context is complete, not when a counter is.

TWO CAPS EXISTED, both arbitrary:

  * guided mode asked exactly 4 questions from a static per-project-type bank and then
    generated the spec, whatever the answers contained;
  * `idea_oracle.converse` forced `ready_to_spec=True` after TWO user replies, commented
    "The 3B model reliably loops on the 3rd exchange; cut it off here."

The second names the real cause -- a small model looping -- and the remedy chosen traded the
user's spec quality for the model's stamina. A spec built from two answers to a five-answer
problem yields a confident build of the wrong thing, and the compiler oracle will happily
certify it, because compiling is not the same as being what was asked for.

The replacement measures instead of counting, against Determinex's own existing standard:
can a SOUND ORACLE be synthesized from what we have been told? `determinex_synthesize`
answers exactly that and emits DETERMINEX_VACUOUS_ORACLE when it cannot. Tying the interview
to that verdict means "enough context" cannot drift from "enough to verify".
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from idea_context import REQUIREMENTS, assess, assess_round  # noqa: E402

_VAGUE = "I want a tool to manage my tasks"
_FOUR_ANSWERS_NO_EXAMPLE = [
    "It should let me add and list tasks",
    "Python",
    "A CLI command",
    "No dependencies",
]
_WITH_EXAMPLE = _FOUR_ANSWERS_NO_EXAMPLE + [
    "add_task([], 'buy milk') == ['buy milk']",
    "Empty list returns empty; duplicate titles are rejected",
]


def test_a_vague_idea_is_not_enough_to_build_from():
    a = assess(_VAGUE)
    assert a.sufficient is False
    assert a.oracle_would_be_vacuous is True
    assert a.questions, "an insufficient context must produce a follow-up"


def test_four_answers_without_a_worked_example_are_still_not_enough():
    """THE CASE THE OLD CAP GOT WRONG. This is exactly where guided mode stopped asking and
    generated the spec. Four thoughtful answers, no checkable behaviour anywhere in them --
    so the synthesized oracle would assert nothing and the build would prove nothing."""
    a = assess(_VAGUE, _FOUR_ANSWERS_NO_EXAMPLE)
    assert a.sufficient is False, "four answers is not a completeness criterion"
    assert a.oracle_would_be_vacuous is True
    assert "example" in a.missing
    assert any("example" in q.lower() for q in a.questions)


def test_a_concrete_example_is_what_flips_it():
    a = assess(_VAGUE, _WITH_EXAMPLE)
    assert a.sufficient is True
    assert a.oracle_would_be_vacuous is False
    assert a.questions == [], "a sufficient context must stop asking"


def test_the_verdict_comes_from_the_real_synthesizer_not_a_regex():
    """The gate must be the same component that later builds the oracle, or the interview's
    idea of 'enough' drifts from the verifier's. Asserted by giving it text a keyword check
    would wave through -- it TALKS about examples without containing one."""
    talky = [
        "Python. It handles many examples of input and output, and returns the expected "
        "output for each given input as described above."
    ]
    a = assess(_VAGUE, talky)
    assert a.oracle_would_be_vacuous is True, (
        "prose about examples is not an example; only the synthesizer can tell the difference"
    )
    assert a.sufficient is False


def test_it_never_repeats_a_question_it_already_asked():
    """The original cap existed because a model looped. Re-asking is the loop."""
    first = assess(_VAGUE)
    asked = [first.questions[0]]
    second = assess(_VAGUE, ["python"], asked=asked)
    assert first.questions[0] not in second.questions


def test_a_round_that_satisfies_nothing_new_is_reported_as_stalled():
    """Not a failure -- a signal. The caller should offer to proceed with what it has rather
    than rephrasing the same question forever, which is what the hard cap was crudely
    protecting against."""
    before = assess(_VAGUE, ["python"])
    after = assess_round(_VAGUE, ["python", "yeah sounds good", "sure"],
                         asked=[], previous_satisfied=before.satisfied)
    assert after.sufficient is False
    assert after.stalled is True


def test_progress_is_reported_so_the_interview_is_not_a_black_box():
    """A user answering an open-ended number of questions is owed a reason each time."""
    a = assess(_VAGUE, _FOUR_ANSWERS_NO_EXAMPLE)
    assert a.rationale, "every verdict must carry its reason"
    assert a.satisfied, "and must credit what has already been established"
    assert set(a.satisfied) | set(a.missing) == {r.key for r in REQUIREMENTS}


def test_skipped_answers_do_not_count_as_context():
    """The UI offers a Skip button; a skipped question must not satisfy the requirement it
    was asking about, or skipping four times would 'complete' the interview."""
    a = assess(_VAGUE, ["(skipped)", "(skipped)", "(skipped)", "(skipped)"])
    assert a.sufficient is False
    assert a.oracle_would_be_vacuous is True


def test_the_hard_gate_is_the_oracle_not_the_checklist():
    """A context can tick most boxes and still produce an oracle that checks nothing. That
    combination is the dangerous one -- it looks complete and verifies nothing -- so the
    oracle verdict must be able to veto a full-looking checklist."""
    boxes_ticked_no_example = [
        "Python", "a CLI command", "no dependencies, must run offline on windows",
        "empty input should error",
    ]
    a = assess(_VAGUE, boxes_ticked_no_example)
    assert len(a.satisfied) >= 4, "premise: most of the checklist is satisfied"
    assert a.oracle_would_be_vacuous is True
    assert a.sufficient is False, "the oracle veto must win"
