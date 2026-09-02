"""An oracle-backed claim is only as good as the oracle. These pin the cases where it was not.

The correctness amplifier's stated contract is that correct output follows from a SOUND oracle --
"garbage oracle in, confident garbage out". Each test below corresponds to a path that reported
`solved` / `oracle-verified` while the oracle behind it established nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_an_idea_with_no_derivable_ground_truth_yields_a_vacuous_oracle_marker():
    """The synthesizer's fallback is `assert callable(f)`, which `def f(s): return None` satisfies.

    That is legitimate as a smoke test; what was not legitimate is that it was indistinguishable
    from a real oracle downstream. validate_oracle only counts `def test_` occurrences, so it
    returned ok with n=1.
    """
    from determinex_synthesize import oracle_is_vacuous, parse_spec, synthesize_oracle_tests

    spec = parse_spec(
        "Write a function rle that run-length encodes text. It should be efficient and "
        "handle unicode."
    )
    tests = synthesize_oracle_tests(spec)

    assert spec.examples == [], "this idea is expected to yield no extractable examples"
    assert oracle_is_vacuous(tests), "the callable-only fallback must be detectable as vacuous"
    assert "assert callable" in tests


def test_a_concrete_example_is_not_treated_as_vacuous():
    """The marker must be narrow. If a real example-backed oracle were flagged, the check would be
    removed rather than fixed."""
    from determinex_synthesize import oracle_is_vacuous, parse_spec, synthesize_oracle_tests

    spec = parse_spec(
        "Write a function double that doubles a number.\n\nExamples:\n- double(2) -> 4\n"
    )
    tests = synthesize_oracle_tests(spec)

    assert spec.examples, "expected one extracted example"
    assert not oracle_is_vacuous(tests)


def test_build_from_idea_refuses_to_claim_verification_on_a_vacuous_oracle():
    """Source-level, because exercising it end to end needs a live model.

    `build_from_idea` used to return solved=True with the proof "program PASSES all 1 synthesized
    checks (oracle-verified, N samples)" off the callable-only oracle -- and it was the ONLY case
    that shipped with no caveat, because `caveat` fires for model-PROPOSED examples, which are
    strictly stronger than this.
    """
    src = (ROOT / "scripts" / "determinex_build_from_idea.py").read_text(encoding="utf-8")
    assert "oracle_is_vacuous" in src, (
        "build_from_idea does not check for a vacuous oracle before claiming verification"
    )
    # The guard has to run BEFORE the search, not merely be imported.
    guard_at = src.index("oracle_is_vacuous(tests)")
    search_at = src.index("VerifiedSearch(")
    assert guard_at < search_at, (
        "the vacuous-oracle guard must precede the verified search that produces the claim"
    )


def test_a_ceiling_certificate_requires_proof_not_a_count():
    """`pb_certify_ceiling` wrote "ALL proven IMPOSSIBLE / This is the maximum attainable score"
    into a locked archive on `impossible > 0 and reopen == 0` alone, and with --update-index --apply
    set eval_index status to ceiling_certified -- the file the public catalog is generated from.

    The only reachable IMPOSSIBLE verdict comes from a regex over pytest skip messages; the
    identical-context-conflict branch that emits a real "PROOF:" rationale is dead code (it builds
    `distinct` by excluding peers whose test_id equals f.test_id, then requires that equality).
    So a count of IMPOSSIBLE units is not evidence of a proof.
    """
    src = (ROOT / "scripts" / "determinex_pb_certify_ceiling.py").read_text(encoding="utf-8")
    assert "DEMOTE_UNPROVEN" in src, "the certifier does not distinguish proven from classified"
    assert 'startswith("PROOF:")' in src, "the certifier does not require a proof rationale"


def test_the_adjudication_field_the_certifier_reads_actually_exists():
    """Guard against the mistake I made writing the check above: reading a non-existent attribute
    with a getattr default would mark every unit unproven -- conservative by accident, and wrong as
    documentation. Adjudication carries `remediation`, not `rationale`."""
    import dataclasses

    from determinex_adjudicator import Adjudication

    names = {f.name for f in dataclasses.fields(Adjudication)}
    assert "remediation" in names, names
    src = (ROOT / "scripts" / "determinex_pb_certify_ceiling.py").read_text(encoding="utf-8")
    assert 'getattr(a, "remediation"' in src, (
        "the certifier must read the field that carries the adjudicator's explanation"
    )
