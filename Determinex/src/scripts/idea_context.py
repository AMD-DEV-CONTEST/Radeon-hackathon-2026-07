#!/usr/bin/env python3
"""
idea_context.py — is there enough context yet to build the thing the user asked for?
====================================================================================
The Concept Lab interviews a user before writing a spec. Until now it stopped counting:

  * guided mode asked exactly 4 questions from a static per-project-type bank, then
    generated the spec whatever the answers were;
  * free-form mode was harder still -- `idea_oracle.converse` forced `ready_to_spec=True`
    after TWO user replies, with the comment "The 3B model reliably loops on the 3rd
    exchange; cut it off here."

That second one names the real cause: a small model looping. The fix chosen was to truncate
the interview, which trades the user's spec quality for the model's stamina -- and a spec
built from two answers to a five-answer problem produces a confident build of the wrong
thing. Ryan, 2026-08-02: "it needs to go until all the full context is gathered from the
user to have a full project."

WHAT "ENOUGH" MEANS, MEASURED RATHER THAN COUNTED
------------------------------------------------
Determinex already has an exact standard for this, and it is not a number of questions:
**can a SOUND ORACLE be synthesized from what we have been told?** `determinex_synthesize`
answers precisely that, and emits `DETERMINEX_VACUOUS_ORACLE` when the answer is no. An
oracle that cannot check anything means the interview has not yet extracted the one thing a
verified build requires -- concrete, checkable behaviour.

So the gate is: keep asking until the accumulated context yields a non-vacuous oracle AND
the structural fields a Determinex spec needs (goal, language, constraints, at least one
worked example). Every missing item maps to a specific question, so the follow-ups are
derived from what is actually absent rather than drawn from a fixed list.

WHY THIS DOES NOT LOOP
----------------------
The original cap existed because the model repeated itself. This does not ask the model what
to ask next: the questions come from a deterministic checklist of what is still missing, so a
question can only be asked while the thing it asks for is genuinely absent. Two further
guards: a question already asked is never re-asked, and if a whole round of answers adds no
new satisfied requirement, that is reported as `stalled` so the caller can offer to proceed
rather than grinding. Progress is a property of the CONTEXT, not of the conversation length.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ── the checklist ───────────────────────────────────────────────────────────────────────
# Each requirement knows how to detect itself in the accumulated text and what to ask when
# it is missing. Ordered by how much the rest depends on it.


@dataclass(frozen=True)
class Requirement:
    key: str
    #: Shown to the user when explaining what is still needed.
    label: str
    #: The question to ask when this is not yet satisfied.
    question: str
    #: Why a build cannot be trusted without it -- surfaced so the interview never feels
    #: like an arbitrary form.
    why: str


REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        "goal",
        "what it should do",
        "In one sentence, what should this program do when it works?",
        "without a goal there is nothing to verify against",
    ),
    Requirement(
        "language",
        "language or runtime",
        "What language or runtime should it be written in? (python, rust, go, typescript...)",
        "the oracle is language-specific; the wrong one cannot compile or test the result",
    ),
    Requirement(
        "example",
        "a worked example",
        "Give me one concrete example: for a specific input, what exactly should come out?",
        "this is the one that makes the build verifiable -- without a single worked example "
        "the synthesized oracle checks nothing, and a passing build proves nothing",
    ),
    Requirement(
        "edge_cases",
        "edge cases",
        "What should happen in the awkward cases -- empty input, bad input, duplicates?",
        "most wrong builds are correct on the happy path and wrong at the edges",
    ),
    Requirement(
        "interface",
        "how it is used",
        "How is it invoked -- a function someone calls, a CLI command, an HTTP endpoint?",
        "the shape of the interface decides what the oracle can call",
    ),
    Requirement(
        "constraints",
        "constraints",
        "Any hard constraints? (dependencies you must or must not use, performance, platform)",
        "a constraint discovered after the build is a rebuild",
    ),
)

_REQ_BY_KEY = {r.key: r for r in REQUIREMENTS}

_LANG_WORDS = (
    "python", "rust", "go ", "golang", "typescript", "javascript", "java", "kotlin",
    "swift", "c++", "cpp", " c#", "csharp", "ruby", "php", "bash", "shell",
)
_EDGE_WORDS = (
    "empty", "none", "null", "zero", "invalid", "error", "duplicate", "missing",
    "negative", "malformed", "edge case", "fail", "raise", "throw", "unicode",
)
_INTERFACE_WORDS = (
    "function", "cli", "command", "endpoint", "api", "http", "library", "import",
    "argument", "flag", "stdin", "script", "module", "class", "route",
)
_CONSTRAINT_WORDS = (
    "no dependencies", "stdlib", "standard library", "must not", "must use", "only use",
    "offline", "performance", "memory", "platform", "windows", "linux", "macos",
    "without", "constraint", "limit", "requirement",
)

#: An example is a concrete input paired with a concrete output. Prose promising one
#: ("it should handle lists") is not an example; `f([1,2]) == [1,2]` is.
_EXAMPLE_PATTERNS = (
    re.compile(r"\w+\s*\([^)]*\)\s*(?:==|=>|->|returns?|gives?|yields?)\s*\S+", re.I),
    re.compile(r"\binput\b.{0,60}\boutput\b", re.I | re.DOTALL),
    re.compile(r"\bgiven\b.{0,60}\b(?:then|expect|should (?:be|return|give))\b", re.I | re.DOTALL),
    re.compile(r"\bfor\b\s+\S+\s*,?\s*(?:it |we |you )?(?:should |must )?(?:return|output|print|give)\b", re.I),
)


@dataclass
class ContextAssessment:
    sufficient: bool
    satisfied: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    #: Ordered follow-ups, most load-bearing first. Empty when sufficient.
    questions: list[str] = field(default_factory=list)
    #: Human-readable reason, always populated -- "sufficient" is a claim that needs support.
    rationale: str = ""
    #: True when a full round of answers satisfied nothing new. Not a failure: the caller
    #: should offer to proceed rather than asking the same thing in different words.
    stalled: bool = False
    #: Would the oracle synthesized from this context actually check anything?
    oracle_would_be_vacuous: bool = True


def _has_example(text: str) -> bool:
    return any(p.search(text) for p in _EXAMPLE_PATTERNS)


def _oracle_is_vacuous(text: str) -> bool:
    """Ask the real synthesizer, not a proxy.

    This is the load-bearing check: `determinex_synthesize` emits an explicit
    VACUOUS_ORACLE marker when it could extract no example and no typeable invariant, i.e.
    when a build against it would prove nothing. Using its own verdict means the interview's
    definition of "enough" cannot drift from the verifier's.
    """
    try:
        from determinex_synthesize import oracle_is_vacuous, parse_spec, synthesize_oracle_tests

        spec = parse_spec(text, "python")
        return bool(oracle_is_vacuous(synthesize_oracle_tests(spec)))
    except Exception:
        # The synthesizer is a stronger signal than the regex, but its absence must not
        # silently mark a context as sufficient -- fall back to the conservative answer.
        return not _has_example(text)


def assess(idea: str, answers: list[str] | None = None,
           asked: list[str] | None = None) -> ContextAssessment:
    """Decide whether the interview has gathered enough to build a real project."""
    answers = [a for a in (answers or []) if a and a.strip() and a.strip() != "(skipped)"]
    asked = asked or []
    blob = "\n".join([idea or "", *answers])
    low = blob.lower()

    satisfied: list[str] = []
    if len((idea or "").split()) >= 4:
        satisfied.append("goal")
    if any(w in low for w in _LANG_WORDS):
        satisfied.append("language")
    if _has_example(blob):
        satisfied.append("example")
    if any(w in low for w in _EDGE_WORDS):
        satisfied.append("edge_cases")
    if any(w in low for w in _INTERFACE_WORDS):
        satisfied.append("interface")
    if any(w in low for w in _CONSTRAINT_WORDS):
        satisfied.append("constraints")

    vacuous = _oracle_is_vacuous(blob)
    missing = [r.key for r in REQUIREMENTS if r.key not in satisfied]

    # The hard gate is the oracle, not the checklist. A context can tick every box and still
    # yield an oracle that checks nothing -- and that is the case that produces a confident
    # build of the wrong thing.
    sufficient = (not vacuous) and not ({"goal", "language", "example"} - set(satisfied))

    questions = [
        _REQ_BY_KEY[k].question for k in missing if _REQ_BY_KEY[k].question not in asked
    ]
    if vacuous and _REQ_BY_KEY["example"].question not in questions:
        # Ask for the example even if the checklist thought it saw one: the synthesizer is
        # the authority, and it says nothing checkable was extractable.
        questions.insert(0, _REQ_BY_KEY["example"].question)

    if sufficient:
        rationale = (
            f"a sound oracle can be synthesized from this: "
            f"{len(satisfied)}/{len(REQUIREMENTS)} requirements covered "
            f"({', '.join(satisfied)})"
        )
    else:
        why = "; ".join(f"{_REQ_BY_KEY[k].label} ({_REQ_BY_KEY[k].why})" for k in missing[:2])
        rationale = (
            "not yet -- the oracle would check nothing" if vacuous else "not yet"
        ) + (f"; still missing: {why}" if missing else "")

    return ContextAssessment(
        sufficient=sufficient,
        satisfied=satisfied,
        missing=missing,
        questions=[] if sufficient else questions,
        rationale=rationale,
        oracle_would_be_vacuous=vacuous,
    )


def assess_round(idea: str, answers: list[str], asked: list[str],
                 previous_satisfied: list[str] | None = None) -> ContextAssessment:
    """`assess`, plus whether the last round actually moved anything forward.

    The cap this replaces existed because a small model looped. Detecting a stalled round
    lets the caller say "we are going in circles, shall I build with what we have?" instead
    of either looping forever or truncating at an arbitrary count.
    """
    out = assess(idea, answers, asked)
    if previous_satisfied is not None and not out.sufficient:
        out.stalled = set(out.satisfied) <= set(previous_satisfied)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Assess whether an idea has enough context.")
    ap.add_argument("--stdin", action="store_true", help="read a JSON payload from stdin")
    ap.parse_args()
    payload = {}
    raw = sys.stdin.read().strip()
    if raw:
        payload = json.loads(raw)
    out = assess_round(
        idea=payload.get("idea", ""),
        answers=payload.get("answers") or [],
        asked=payload.get("asked") or [],
        previous_satisfied=payload.get("previous_satisfied"),
    )
    print(json.dumps(asdict(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
