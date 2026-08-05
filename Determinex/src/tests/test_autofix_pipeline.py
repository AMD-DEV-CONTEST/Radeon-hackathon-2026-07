"""
test_autofix_pipeline.py -- The self-eval / meta-benchmark
==========================================================
"How do we ensure the system is all of that?"

This is the regression net for the SYSTEM's reasoning, not for any single tool.
It scores the five components of the self-correcting loop (Adjudicator, Test
Validator, Explainer, Remediation Executor, Ingester) against held-out cases
that each exercise one verdict path. If any component starts copping out --
calling unfinished work a ceiling, blaming the code for an environment mismatch,
or declaring a test slop without proof -- a test here goes red.

Run:  python -m pytest tests/test_autofix_pipeline.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from determinex_adjudicator import (  # noqa: E402
    Failure,
    Verdict,
    adjudicate_eval_report,  # noqa: E402
    classify_failure,
)
from determinex_explainer import explain_eval_report  # noqa: E402
from determinex_remediation import remediations_for  # noqa: E402
from determinex_test_validator import (  # noqa: E402
    ReferenceCheck,
    TestVerdict,
    reference_cross_check,
    validate_eval_report,
)


# ---------------------------------------------------------------------------
# 1. Adjudicator: every escalation signature maps to the right move,
#    and only a proven upstream skip is allowed to be IMPOSSIBLE.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "f,expect",
    [
        (Failure("t", "t", "", status="not_run"), Verdict.UNBLOCK),
        (Failure("t", "t", "Error: Screen.Init(): open /dev/tty: no such device"), Verdict.MATCH),
        (
            Failure(
                "t", "t", "requires age-plugin-batchpass which is not available", status="skipped"
            ),
            Verdict.MATCH,
        ),
        (Failure("t", "t", "assert not os.access(f, X_OK) -- all files executable"), Verdict.MATCH),
        (Failure("t", "t", "AVX2 symbols_output rendering differs"), Verdict.MATCH),
        (Failure("t", "t", "assert output == 'hello' but got 'helo'"), Verdict.NEEDS_WORK),
        (Failure("t", "t", '@pytest.mark.skip("Too slow")', status="skipped"), Verdict.IMPOSSIBLE),
    ],
)
def test_adjudicator_maps_signature_to_move(f, expect):
    assert classify_failure(f).verdict == expect


def test_adjudicator_never_impossible_without_proof():
    """A plain behavioral bug must NEVER be called impossible."""
    f = Failure("t", "t", "assert result == 42 but got 41")
    assert classify_failure(f).verdict != Verdict.IMPOSSIBLE


# ---------------------------------------------------------------------------
# 2. Test Validator: slop only with a deterministic proof.
# ---------------------------------------------------------------------------
def _eval_report(tmp_path: Path, results: list[dict]) -> Path:
    p = tmp_path / "eval.json"
    p.write_text(json.dumps({"test_results": results}), encoding="utf-8")
    return p


def test_validator_flags_env_baked_slop(tmp_path):
    rep = _eval_report(
        tmp_path,
        [
            {
                "status": "failed",
                "classname": "tests.t",
                "name": "test_force_screen",
                "extra": {
                    "text": "assert rc==0 -- Error: open /dev/tty force-screen len(result.stdout) > 15"
                },
            },
        ],
    )
    js = validate_eval_report(rep)
    assert js[0].verdict == TestVerdict.SLOP
    assert js[0].check == "environment-baked"
    assert js[0].proof  # proof is mandatory


def test_validator_flags_tautology_with_source(tmp_path):
    rep = _eval_report(
        tmp_path,
        [
            {
                "status": "failed",
                "classname": "tests.test_x",
                "name": "test_trivial",
                "extra": {"text": "some failure"},
            },
        ],
    )
    sources = {"test_x": "def test_trivial():\n    assert True\n"}
    js = validate_eval_report(rep, sources)
    assert js[0].verdict == TestVerdict.SLOP
    assert js[0].check == "tautology"


def test_validator_detects_contradiction(tmp_path):
    """Two tests, same base nodeid, conflicting goldens -> at least one is slop."""
    rep = _eval_report(
        tmp_path,
        [
            {
                "status": "failed",
                "classname": "tests.test_v",
                "name": "test_version",
                "extra": {"text": "assert out == '1.0'"},
            },
            {
                "status": "failed",
                "classname": "eval.tests.test_v",
                "name": "test_version",
                "extra": {"text": "assert out == '2.0'"},
            },
        ],
    )
    js = validate_eval_report(rep)
    # bidir twins collapse to one base; if goldens differ it's a contradiction
    assert any(j.check == "contradiction" for j in js)


def test_validator_presumes_correct_without_signature(tmp_path):
    """No slop signature -> the CODE is at fault, not the test."""
    rep = _eval_report(
        tmp_path,
        [
            {
                "status": "failed",
                "classname": "tests.t",
                "name": "test_real",
                "extra": {"text": "assert add(2,2) == 4 but got 5"},
            },
        ],
    )
    js = validate_eval_report(rep)
    assert js[0].verdict == TestVerdict.CORRECT


def test_reference_cross_check_proves_slop(tmp_path):
    """If the REFERENCE binary also fails the golden, the test is slop."""
    if sys.platform.startswith("win"):
        ref = tmp_path / "ref.bat"
        ref.write_text("@echo off\necho REFOUT\n", encoding="utf-8")
    else:
        ref = tmp_path / "ref.sh"
        ref.write_text("#!/bin/sh\necho REFOUT\n", encoding="utf-8")
        ref.chmod(0o755)
    j = reference_cross_check(
        ReferenceCheck(binary=ref, argv=[], golden_rc=0, golden_stdout="DIFFERENT\n")
    )
    assert j.verdict == TestVerdict.SLOP
    assert "REFERENCE BINARY ALSO FAILS" in j.proof


# ---------------------------------------------------------------------------
# 3. Explainer: honest blame assignment.
# ---------------------------------------------------------------------------
def test_explainer_blames_environment_for_tty(tmp_path):
    rep = _eval_report(
        tmp_path,
        [
            {
                "status": "failed",
                "classname": "tests.t",
                "name": "test_force_screen",
                "extra": {"text": "Error: open /dev/tty force-screen"},
            },
        ],
    )
    exps = explain_eval_report(rep)
    assert exps[0].responsible == "ENVIRONMENT"


def test_explainer_blames_code_for_plain_bug(tmp_path):
    rep = _eval_report(
        tmp_path,
        [
            {
                "status": "failed",
                "classname": "tests.t",
                "name": "test_add",
                "extra": {"text": "assert add(2,2) == 4 but got 5"},
            },
        ],
    )
    exps = explain_eval_report(rep)
    assert exps[0].responsible == "CODE"


# ---------------------------------------------------------------------------
# 4. Remediation Executor: each reopenable verdict yields a concrete fix;
#    IMPOSSIBLE yields none.
# ---------------------------------------------------------------------------
def test_remediation_generates_for_reopenable(tmp_path):
    rep = _eval_report(
        tmp_path,
        [
            {
                "status": "not_run",
                "classname": "tests.t",
                "name": "test_capped",
                "extra": {"text": ""},
            },
            {
                "status": "failed",
                "classname": "tests.t",
                "name": "test_dep",
                "extra": {"text": "requires foo-plugin which is not available"},
            },
        ],
    )
    adjs = adjudicate_eval_report(rep)
    rems = remediations_for(adjs)
    strategies = {r.strategy for r in rems}
    assert "remove-collection-cap" in strategies
    assert any("install" in s for s in strategies)


def test_remediation_empty_for_genuine_ceiling(tmp_path):
    rep = _eval_report(
        tmp_path,
        [
            {
                "status": "skipped",
                "classname": "tests.t",
                "name": "test_net",
                "extra": {"text": '@pytest.mark.skip("requires network")'},
            },
        ],
    )
    adjs = adjudicate_eval_report(rep)
    assert remediations_for(adjs) == []


# ---------------------------------------------------------------------------
# 5. Ingester: detects language/build/oracle.
# ---------------------------------------------------------------------------
def test_ingester_detects_python(tmp_path):
    from determinex_ingest import ingest

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    tdir = tmp_path / "tests"
    tdir.mkdir()
    (tdir / "test_x.py").write_text(
        'def test_round(self):\n    """round-trips input."""\n    assert encode(decode(x)) == x\n',
        encoding="utf-8",
    )
    u = ingest(tmp_path)
    assert u.language == "python"
    assert u.harness == "pytest"
    assert u.has_tests


# ---------------------------------------------------------------------------
# 6. End-to-end: a mixed report partitions honestly, 0 false ceilings.
# ---------------------------------------------------------------------------
def test_pipeline_partitions_mixed_report(tmp_path):
    rep = _eval_report(
        tmp_path,
        [
            {"status": "not_run", "classname": "tests.t", "name": "test_a", "extra": {"text": ""}},
            {
                "status": "failed",
                "classname": "tests.t",
                "name": "test_b",
                "extra": {"text": "Error: open /dev/tty"},
            },
            {
                "status": "failed",
                "classname": "tests.t",
                "name": "test_c",
                "extra": {"text": "assert x == 1 but got 2"},
            },
            {
                "status": "skipped",
                "classname": "tests.t",
                "name": "test_d",
                "extra": {"text": '@pytest.mark.skip("Too slow")'},
            },
        ],
    )
    adjs = adjudicate_eval_report(rep)
    verdicts = {a.failure.name: a.verdict for a in adjs}
    assert verdicts["test_a"] == Verdict.UNBLOCK
    assert verdicts["test_b"] == Verdict.MATCH
    assert verdicts["test_c"] == Verdict.NEEDS_WORK
    assert verdicts["test_d"] == Verdict.IMPOSSIBLE
    # exactly one genuine ceiling, three reopenable
    impossible = sum(1 for v in verdicts.values() if v == Verdict.IMPOSSIBLE)
    assert impossible == 1


# ---------------------------------------------------------------------------
# 7. Verified Search: a WEAK model is converted to CORRECT by the oracle.
#    This is the "any LLM, however small, works anything and is right" guarantee.
# ---------------------------------------------------------------------------
def test_verified_search_converts_weak_model():
    import random
    from dataclasses import dataclass

    from determinex_verified_search import VerifiedSearch, expected_solve_probability

    @dataclass
    class _Oracle:
        passed: bool
        failures: list

    target = "CORRECT"

    def verify(text):
        return _Oracle(
            text.strip() == target, [] if text.strip() == target else [Failure("t", "eq", "wrong")]
        )

    # weak generator: right only ~15% of the time
    def weak(prompt, temperature):
        return target if random.random() < 0.15 else "WRONG"

    random.seed(1)
    solved = sum(
        VerifiedSearch(verify=verify, k=20, rounds=2).solve(weak, "x").solved for _ in range(50)
    )
    # with K=20 the floor is 1-(1-.15)^20 ~ 0.96; over 50 trials nearly all solve
    assert solved >= 45
    # and the math the module is built on holds
    assert expected_solve_probability(0.15, 20) > 0.95


def test_verified_search_proof_requires_oracle_pass():
    """'solved' is never claimed without a passing oracle (soundness contract)."""
    from dataclasses import dataclass

    from determinex_verified_search import VerifiedSearch

    @dataclass
    class _Oracle:
        passed: bool
        failures: list

    # an oracle that NEVER passes -> must never report solved, must escalate honestly
    def never(text):
        return _Oracle(False, [Failure("t", "x", "assert output == 'hi' but got junk")])

    r = VerifiedSearch(verify=never, k=5, rounds=2).solve(lambda p, t: "junk", "x")
    assert r.solved is False
    assert r.escalated
    assert r.best is not None  # still returns the best partial + next moves


# ---------------------------------------------------------------------------
# 8. The remaining 6 amplifier pieces.
# ---------------------------------------------------------------------------
def test_contract_rejects_malformed_before_oracle():
    from determinex_contract import json_contract, patch_contract, py_contract

    assert json_contract('{"a":1}')[0] is True
    assert json_contract("{not json")[0] is False
    assert py_contract("def f():\n    return 1\n")[0] is True
    assert py_contract("def f(:\n")[0] is False
    assert patch_contract("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n")[0] is True
    assert patch_contract("just prose")[0] is False


def test_progress_detects_loop_and_plateau():
    from determinex_progress import Directive, ProgressTracker

    pt = ProgressTracker(plateau_patience=3, loop_patience=2)
    assert pt.observe("a", -9) == Directive.CONTINUE  # first, improving
    assert pt.observe("b", -7) == Directive.CONTINUE  # improving
    pt.observe("c", -7)  # plateau begins
    pt.observe("d", -7)
    # repeating the same candidate -> loop -> escalate
    pt.observe("d", -7)
    assert pt.observe("d", -7) == Directive.ESCALATE


def test_decompose_sizes_leaves_to_capability():
    from determinex_decompose import Capability, decompose

    checks = [f"tests.mod_{i // 3}.test_{i}" for i in range(9)]
    tiny = decompose(checks, Capability.TINY)
    assert all(leaf.size == 1 for leaf in tiny)  # 1 check/leaf for a tiny model
    whole = decompose(checks, Capability.WHOLE)
    assert len(whole) == 1  # no split for a capable model


def test_case_memory_refuses_unverified(tmp_path):
    from determinex_case_memory import CaseMemory

    mem = CaseMemory(tmp_path / "cases.jsonl")
    assert mem.add("sig", "sol", oracle_passed=False) is False  # refused
    assert mem.add("error: foo undefined", "fix foo", oracle_passed=True) is True
    hits = mem.retrieve("error: foo undefined in bar", k=1)
    assert hits and hits[0].solution == "fix foo"


def test_router_escalates_tiny_to_strong():
    import random
    from dataclasses import dataclass

    from determinex_router import ModelEntry, ModelRouter

    @dataclass
    class _O:
        passed: bool
        failures: list

    def verify(t):
        from determinex_adjudicator import Failure

        return _O(t.strip() == "OK", [] if t.strip() == "OK" else [Failure("t", "x", "no")])

    def weak(p):
        return lambda prompt, temp: "OK" if random.random() < p else "NO"

    random.seed(5)
    router = ModelRouter(
        [
            ModelEntry("tiny", tier=1, cost=0.0, generate=weak(0.10)),
            ModelEntry("strong", tier=4, cost=5.0, generate=weak(0.95)),
        ],
        k=6,
        rounds=1,
    )
    solved = sum(router.solve_leaf(verify, "x").solved for _ in range(40))
    assert solved >= 38  # escalation rescues what the tiny model misses


def test_amplified_solve_beats_one_shot_for_tiny_model():
    """A tiny model solves a multi-check task it could never one-shot."""
    import random
    from dataclasses import dataclass

    from determinex_amplified_solve import amplified_solve
    from determinex_decompose import Capability, _unit_of
    from determinex_router import ModelEntry

    @dataclass
    class _O:
        passed: bool
        failures: list

    checks = [f"tests.mod_{i // 2}.test_{i}" for i in range(6)]

    def slice_verify(candidate, ids):
        from determinex_adjudicator import Failure

        want = {f"FIX:{_unit_of(c)}" for c in (ids or checks)}
        ok = candidate.strip() in want and len(want) == 1
        return _O(ok, [] if ok else [Failure("t", "leaf", "wrong")])

    def weak(prompt, temp):
        unit = prompt.split("UNIT=")[-1].strip()
        return f"FIX:{unit}" if random.random() < 0.15 else "WRONG"

    models = [
        ModelEntry("tiny", tier=1, cost=0.0, generate=weak, capability_hint="qwen2.5-coder:1.5b")
    ]
    random.seed(11)
    solved = sum(
        amplified_solve(
            checks,
            slice_verify,
            models,
            lambda lf: f"Fix. UNIT={lf.unit}",
            capability=Capability.TINY,
            k=20,
            rounds=2,
        ).solved
        for _ in range(30)
    )
    # one-shot would be ~0.15^6 ~ 1e-5; amplified must be vastly better
    assert solved >= 12  # >40%, vs ~0.001% one-shot


# ---------------------------------------------------------------------------
# 9. Governance: the no-overclaim guardrails (consolidated from the apparatus).
#    Same "no claim without proof" discipline, applied to product/release claims.
# ---------------------------------------------------------------------------
def test_authority_anchors_stay_closed():
    """Every authority anchor must remain False until genuinely earned + proven.
    This single test replaces the 1,175 generated lane guard tests."""
    from governance import AUTHORITY_FALSE, assert_authority_closed

    assert len(AUTHORITY_FALSE) >= 12
    violations = {k: v for k, v in AUTHORITY_FALSE.items() if v is not False}
    assert violations == {}, f"authority overclaim: {violations}"
    assert_authority_closed()  # must not raise


def test_overclaim_scanner_detects_a_flipped_anchor():
    """The scanner catches a REAL JSON overclaim but not rule-description strings."""
    from governance import scan_text_for_anchor_true

    # real structured overclaim -> caught
    assert scan_text_for_anchor_true('{"release_ready": true}') == ["release_ready"]
    assert scan_text_for_anchor_true('{"a":1,"release_ready":1,"b":2}') == ["release_ready"]
    # closed value -> not caught
    assert scan_text_for_anchor_true('{"release_ready": false}') == []
    # guard-rule description string (the anti-overclaim rule itself) -> NOT a false alarm
    assert scan_text_for_anchor_true('"release_ready=True -> BLOCKED_AUTHORITY_CONFUSION"') == []
    assert scan_text_for_anchor_true("release_ready remains closed (False)") == []


def test_blocker_taxonomy_aligned_with_adjudicator():
    """The project blocker taxonomy maps cleanly onto Adjudicator verdicts."""
    from determinex_adjudicator import Verdict
    from governance import ADJUDICATOR_VERDICT_HINT, BLOCKER_ORDER

    valid = {v.value for v in Verdict}
    for blocker, hint in ADJUDICATOR_VERDICT_HINT.items():
        assert blocker in BLOCKER_ORDER
        assert hint in valid, f"{blocker} -> unknown verdict {hint}"


# ---------------------------------------------------------------------------
# 10. Greenfield: idea -> synthesized SOUND oracle -> verified program.
#     The last capability gap. The oracle must be sound or nothing is claimed.
# ---------------------------------------------------------------------------
def test_synthesizer_extracts_examples_and_validates():
    from determinex_synthesize import parse_spec, synthesize_oracle_tests, validate_oracle

    idea = "Write a function add(a, b). Examples: add(2, 3) == 5, add(0, 0) == 0."
    spec = parse_spec(idea)
    assert spec.name == "add"
    assert ("add(2, 3)", "5") in spec.examples
    tests = synthesize_oracle_tests(spec)
    assert "def test_example_0" in tests
    ok, why = validate_oracle(tests, spec)
    assert ok, why


def test_synthesizer_skips_wrongtyped_property_no_slop():
    """A string function tagged idempotent must NOT emit int-fuzzed property tests
    (that would fail a correct impl). Type-aware fuzz or skip -- never slop.
    Checked path-agnostically: whichever of the static/Hypothesis backends is
    active (determined by whether hypothesis is installed), it must never
    emit an int- or list-only fuzz construct for a string-typed function."""
    from determinex_synthesize import _HYPOTHESIS_AVAILABLE, parse_spec, synthesize_oracle_tests

    idea = "Write rle(s) that is idempotent. Example: rle('aaa') == 'a3'."
    spec = parse_spec(idea)
    tests = synthesize_oracle_tests(spec)
    if "test_invariant_idempotent" in tests:
        # never wrong-typed int/list fuzz for a string-only function, on
        # either backend
        assert "randint(-50" not in tests
        assert "st.integers(" not in tests
        assert "st.lists(" not in tests
        assert "st.one_of(" not in tests
        if _HYPOTHESIS_AVAILABLE:
            assert "st.text(" in tests
        else:
            assert "random.choice" in tests


def test_build_from_idea_solves_with_correct_model(tmp_path):
    """End-to-end greenfield with a mock model: a correct impl passes the
    synthesized oracle; a stub does not. Uses the REAL pytest oracle."""
    from determinex_build_from_idea import build_from_idea

    idea = "Write add(a, b). Examples: add(2, 3) == 5, add(10, 5) == 15."

    def correct_model(prompt, temperature):
        return "def add(a, b):\n    return a + b\n"

    r = build_from_idea(idea, correct_model, k=2, rounds=1)
    assert r.solved and r.n_checks >= 2 and "PASSES" in r.proof

    def wrong_model(prompt, temperature):
        return "def add(a, b):\n    return a - b\n"

    r2 = build_from_idea(idea, wrong_model, k=2, rounds=1)
    assert r2.solved is False  # oracle catches the wrong program


def test_ide_commands_delegate_no_duplication():
    """The IDE greenfield commands must DELEGATE to the one canonical module --
    no synthesis/solve logic reimplemented in the command surface."""
    import sys as _s

    _s.path.insert(0, str(SCRIPTS / "ide"))
    from ide.backend_command_surface import IDEBackendCommandSurface, commands

    assert "synthesize_oracle_preview" in commands()
    assert "build_from_idea_opt_in" in commands()
    bcs = IDEBackendCommandSurface()
    # preview is deterministic, read-only, sound, and never mutates source
    r = bcs.call("synthesize_oracle_preview", idea_text="Write add(a,b). Examples: add(2,3)==5.")
    assert r.payload.get("oracle_sound") is True
    assert r.payload.get("source_mutation") is False
    # the build command refuses to run live without opt-in (governance held)
    r2 = bcs.call("build_from_idea_opt_in", idea_text="x", opt_in=False)
    assert r2.status == "IDE_COMMAND_BLOCKED_NOT_OPTED_IN"


# ---------------------------------------------------------------------------
# 11. Brownfield repair: ONE canonical engine (the dual of build_from_idea).
# ---------------------------------------------------------------------------
def test_repair_engine_diagnoses_and_fixes(tmp_path):
    """The canonical repair engine: diagnose blame, then amplified-fix to oracle pass."""
    from determinex_repair import repair_workspace

    (tmp_path / "solution.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "test_solution.py").write_text(
        "from solution import add\ndef test_a(): assert add(2,3)==5\n", encoding="utf-8"
    )
    # diagnosis only -> blames CODE, no slop
    r = repair_workspace(tmp_path)
    assert not r.healthy and r.language == "python"
    assert r.blame.get("CODE", 0) >= 1 and r.proven_slop == 0
    # amplified fix with a correct model -> passes the oracle
    r2 = repair_workspace(
        tmp_path, generate=lambda p, t: "def add(a, b):\n    return a + b\n", opt_in=True, k=3
    )
    assert r2.fixed is True


def test_repair_diagnose_command_uses_canonical_engine(tmp_path):
    """The Repo Clinic IDE command delegates to the same engine (no duplication)."""
    import sys as _s

    _s.path.insert(0, str(SCRIPTS / "ide"))
    from ide.backend_command_surface import IDEBackendCommandSurface, commands

    assert "repair_diagnose" in commands()
    (tmp_path / "solution.py").write_text("def f():\n    return 0\n", encoding="utf-8")
    (tmp_path / "test_f.py").write_text(
        "from solution import f\ndef test_f(): assert f()==1\n", encoding="utf-8"
    )
    r = IDEBackendCommandSurface().call("repair_diagnose", workspace=tmp_path)
    assert r.status == "IDE_COMMAND_OK"
    assert r.payload.get("source_mutation") is False
    nf = r.payload.get("n_failures")
    assert isinstance(nf, int) and nf >= 1


def test_vague_idea_uses_model_proposed_consensus_oracle():
    """An example-free idea gets a model-proposed CONSENSUS oracle, flagged so the
    user confirms it (no slop: proposed != confirmed)."""
    from determinex_build_from_idea import build_from_idea

    def model(prompt, temperature):
        if "input/output examples" in prompt:
            return "square(2) == 4\nsquare(3) == 9\nsquare(0) == 0\nsquare(5) == 25"
        return "def square(n):\n    return n * n\n"

    r = build_from_idea("Write square(n) returning n squared.", model, k=2, rounds=1)
    assert r.solved and r.oracle_proposed is True and r.n_checks >= 2
    assert "MODEL-PROPOSED" in r.proof


# ---------------------------------------------------------------------------
# 12. Universal providers + extensions: bring in ANY AI / addon.
# ---------------------------------------------------------------------------
def test_provider_registry_universal_contract():
    """Every provider -- Claude/Codex/Gemini/local/addon -- exposes the same
    generate(prompt, temp) contract and feeds the router."""
    from determinex_providers import available, get_generator, register_provider, to_router_entries

    avail = available()
    assert "claude" in avail and "codex" in avail and "gemini" in avail and "local" in avail
    # register an addon provider with a custom factory (no key needed)
    register_provider(
        "unittest_fake", tier=1, env_key="", factory=lambda model: lambda p, t: "FAKE:" + p[:5]
    )
    gen = get_generator("unittest_fake")
    assert gen("hello world", 0.0) == "FAKE:hello"
    # it joins the router ladder
    names = {e.name for e in to_router_entries()}
    assert "unittest_fake" in names


def test_extension_protocol_hosts_addons():
    """A plugin module's register(api) adds a provider + an oracle -- the host pattern."""
    from determinex_extensions import ExtensionAPI

    class _FakeMod:
        @staticmethod
        def register(api):
            api.register_provider(
                "plugin_prov", tier=2, env_key="", factory=lambda m: lambda p, t: "P"
            )
            api.register_oracle_hint("zig", "zig build test")

    api = ExtensionAPI()
    _FakeMod.register(api)
    assert "plugin_prov" in api.loaded_providers
    assert "zig" in api.loaded_oracles
    from determinex_providers import available

    assert available().get("plugin_prov") is True


# ---------------------------------------------------------------------------
# 13. Agent-CLI sub-agents: host any coding agent, VERIFIED through the oracle.
# ---------------------------------------------------------------------------
def test_agent_registry_verifies_through_oracle(tmp_path):
    """A hosted agent's edits are accepted ONLY if the oracle passes -- the
    correctness boundary applied to agents (a hallucinating agent is rejected)."""
    from determinex_agents import available_agents, register_agent, run_agent

    # the registry knows the real coding agents
    names = set(available_agents())
    assert {"claude-code", "codex", "gemini-cli"} <= names

    def _broken(d):
        (d / "solution.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (d / "test_solution.py").write_text(
            "from solution import add\ndef test_a(): assert add(2,3)==5\n", encoding="utf-8"
        )

    # a good agent fixes it -> oracle VERIFIES
    ws_good = tmp_path / "good"
    ws_good.mkdir()
    _broken(ws_good)

    def good(task, ws, timeout, model=None):
        (ws / "solution.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        return "fixed", 0

    register_agent("ut-good", probe="python", runner=good)
    r = run_agent("ut-good", "fix", ws_good)
    assert r.ran and r.verified is True

    # a hallucinating agent that changes nothing -> oracle REJECTS (caught)
    ws_bad = tmp_path / "bad"
    ws_bad.mkdir()
    _broken(ws_bad)

    def bad(task, ws, timeout, model=None):
        return "claimed success but did nothing", 0

    register_agent("ut-bad", probe="python", runner=bad)
    r2 = run_agent("ut-bad", "fix", ws_bad)
    assert r2.ran and r2.verified is False  # the oracle catches the no-op agent


# ---------------------------------------------------------------------------
# 14. Rotating, auto-establishing per-model rate limiter.
# ---------------------------------------------------------------------------
def test_rate_limiter_rotates_and_learns():
    from determinex_ratelimit import AdaptiveLimiter, RotatingGenerator, is_rate_limit_error

    assert is_rate_limit_error(RuntimeError("HTTP 429 Too Many Requests"))
    assert is_rate_limit_error(RuntimeError("RESOURCE_EXHAUSTED"))
    assert not is_rate_limit_error(RuntimeError("syntax error"))

    calls = {"n": 0}

    def flaky(prompt, temperature):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("429 rate limit")
        return "flaky-ok"

    def backup(prompt, temperature):
        return "backup-ok"

    lim = AdaptiveLimiter(cooldown_seconds=0.0)  # no sleeping in the test
    rg = RotatingGenerator([("flaky", flaky), ("backup", backup)], limiter=lim)
    # on 429, work continues by rotating to the backup
    assert rg.generate("hi", 0.0) == "backup-ok"
    # the limiter auto-established a non-zero interval for the rate-limited model
    assert lim.learned().get("flaky", 0.0) > 0.0
    # the healthy model carries no learned penalty
    assert lim.learned().get("backup", 0.0) == 0.0


def test_go_build_provenance_fix_not_downgrade(tmp_path):
    """The atlas lesson, locked: a Go tool whose go.mod needs a newer Go than the
    container base must be made to build FROM SOURCE (GOTOOLCHAIN=auto fetches the
    right toolchain) -- NOT downgraded to the old container Go, which defeats the
    build and silently falls back to a bundled answer-key binary (atlas: 62 fake
    version/license failures; the 'lock' was the official ELF, not the source)."""
    from determinex_pb_autofix import _ensure_go_toolchain

    (tmp_path / "compile.sh").write_text(
        "#!/bin/sh\nset -e\n"
        'sed -i "s/^go [0-9.]*/go 1.21/" go.mod\n'  # the harmful lowering hack
        "go build -o /usr/local/bin/x .\n",
        encoding="utf-8",
    )
    (tmp_path / "go.mod").write_text("module x\ngo 1.21\ntoolchain go1.24.11\n", encoding="utf-8")

    changed, note = _ensure_go_toolchain(tmp_path)
    assert changed, note
    csh = (tmp_path / "compile.sh").read_text(encoding="utf-8")
    gomod = (tmp_path / "go.mod").read_text(encoding="utf-8")
    # from-source, not downgrade:
    assert "GOTOOLCHAIN=auto" in csh  # fetch the real toolchain
    assert "[determinex] disabled go.mod-lowering" in csh  # neutralized the harmful sed
    assert "go 1.24" in gomod  # go.mod restored, NOT left at 1.21
    # idempotent: a second pass makes no further change
    changed2, _ = _ensure_go_toolchain(tmp_path)
    assert not changed2


def test_provenance_gate_flags_shipped_binary_clears_with_proof(tmp_path, monkeypatch):
    """Build-provenance gate (the atlas lesson, locked): a lock whose tracked source/ or
    submission ships a prebuilt ELF is a credibility risk (could pass via the answer key,
    not a from-source build) -> flagged, UNLESS a from-source proof is on record."""
    import determinex_pb_provenance_guard as PG

    # synthetic locked tool with an answer-key ELF in its tracked source/
    locked = tmp_path / "locked"
    tool = "synthtool"
    src = locked / tool / "source"
    src.mkdir(parents=True)
    (src / "main.rs").write_text("fn main(){}", encoding="utf-8")
    (src / tool).write_bytes(b"\x7fELF" + b"\x00" * 3_000_000)  # 3MB answer-key ELF
    monkeypatch.setattr(PG, "LOCKED", locked)
    proofs_file = tmp_path / "proofs.json"
    monkeypatch.setattr(PG, "PROOFS", proofs_file)

    hits = PG.scan_tool(tool)
    assert any(h["kind"] == "ships-prebuilt-binary" for h in hits), "must flag the shipped ELF"
    assert tool not in PG.load_proofs(), "no proof yet"
    # a from-source proof clears it
    PG.record_proof(tool, {"verified": "now", "method": "from-source-build"})
    assert tool in PG.load_proofs()


def test_pb_amplified_fix_locks_with_weak_model_against_sound_oracle():
    """Stage-1 autonomous loop: when deterministic autofix can't lock the behavioral tail,
    verified-search fix-generation does -- a weak model sampled K times vs a SOUND oracle
    is driven to a lock (1-(1-p)^K). Composes VerifiedSearch (no new engine)."""
    from determinex_pb_amplified_fix import amplified_fix

    GOLDEN = "#!/bin/sh\nexport GOTOOLCHAIN=auto\ngo build -o /usr/local/bin/x .\n"
    calls = {"n": 0}

    def sound_oracle(candidate):
        ok = "GOTOOLCHAIN=auto" in candidate
        return {
            "test_results": [
                {"status": "passed" if ok else "failed", "name": f"t{i}"} for i in range(50)
            ]
        }

    def weak_model(prompt, temp):  # deterministic: right only on the 4th distinct try
        calls["n"] += 1
        return GOLDEN if calls["n"] >= 4 else f"#!/bin/sh\ngo build . # try{calls['n']}\n"

    r = amplified_fix(
        "t__x", "#!/bin/sh\ngo build .\n", [], weak_model, sound_oracle, k=8, rounds=2
    )
    assert r.solved, f"best-of-K should lock; got {r.proof}"
    assert "GOTOOLCHAIN=auto" in r.best.text


def test_pb_amplified_fix_never_false_locks():
    """Soundness contract: if the model NEVER produces a passing fix, the loop must NOT
    claim solved (no lock without a passing oracle result -- garbage in, no false lock out)."""
    from determinex_pb_amplified_fix import amplified_fix

    def sound_oracle(candidate):
        return {
            "test_results": [{"status": "failed", "name": "t0"}, {"status": "passed", "name": "t1"}]
        }

    def hopeless_model(prompt, temp):
        return "#!/bin/sh\ngo build . # always wrong\n"

    r = amplified_fix(
        "t__x", "#!/bin/sh\ngo build .\n", [], hopeless_model, sound_oracle, k=5, rounds=2
    )
    assert not r.solved, "must never claim a lock without a passing oracle"


def test_drive_auto_chains_autofix_then_amplify():
    """The autonomous loop: deterministic autofix is tried first; if it already locks, no
    model is sampled; if not, amplified verified-search takes over -- both vs a SOUND oracle.
    Composes existing stages (determinex_pb_drive.drive_auto), injectable for the test."""
    from determinex_pb_drive import drive_auto

    # Path A: deterministic autofix produces a compile.sh the oracle locks -> no amplify needed.
    def oracle(c):
        ok = "GOTOOLCHAIN=auto" in c
        return {
            "test_results": [
                {"status": "passed" if ok else "failed", "name": f"t{i}"} for i in range(30)
            ]
        }

    def never_called_gen(prompt, temp):
        raise AssertionError("generator must NOT be called when autofix already locks")

    vA = drive_auto(
        "t__a",
        oracle,
        never_called_gen,
        apply_autofix=lambda s: "#!/bin/sh\nexport GOTOOLCHAIN=auto\ngo build .\n",
    )
    assert vA["verdict"] == "LOCKED_BY_AUTOFIX", vA

    # Path B: deterministic autofix is NOT enough -> amplify finds the fix.
    calls = {"n": 0}

    def weak_gen(prompt, temp):
        calls["n"] += 1
        return (
            "#!/bin/sh\nexport GOTOOLCHAIN=auto\ngo build .\n"
            if calls["n"] >= 2
            else "#!/bin/sh\ngo build .\n"
        )

    vB = drive_auto(
        "t__b", oracle, weak_gen, k=5, rounds=2, apply_autofix=lambda s: "#!/bin/sh\ngo build .\n"
    )  # autofix output still fails
    assert vB["verdict"] == "LOCKED_BY_AMPLIFY", vB
    assert "GOTOOLCHAIN=auto" in vB["compile_sh"]


def test_amplified_fix_cleans_fenced_model_output():
    """Output-contract: small models wrap compile.sh in markdown fences / prose, which made
    every amplify candidate a malformed build (the pipr ~0s live bug). clean_candidate must
    recover a valid shell script so candidates actually evaluate."""
    from determinex_pb_amplified_fix import clean_candidate

    fenced = "```sh\n#!/bin/sh\nexport GOTOOLCHAIN=auto\ngo build .\n```"
    c = clean_candidate(fenced)
    assert c.startswith("#!/bin/sh") and "```" not in c and "GOTOOLCHAIN=auto" in c
    prose = "Here is the fix:\n```bash\n#!/bin/sh\nexport TZ=UTC\n```\nDone!"
    c2 = clean_candidate(prose)
    assert (
        c2.startswith("#!/bin/sh") and "```" not in c2 and "Here is" not in c2 and "Done" not in c2
    )
    # a bare script (no fence) is preserved + gets a shebang if missing
    assert clean_candidate("export X=1\ngo build .\n").startswith("#!/bin/sh")


def test_pty_sidecar_installs_and_gates(tmp_path):
    """The pty + anti-hang sidecar (tty-stdin -> pty-allocate): installs as a pip pytest11
    plugin (survives branch-conftest overlay, like droppriv/hermetic), is idempotent, and
    fires on TUI/interactive failure signatures (the gdu/pipr hang class)."""
    from determinex_pb_pty import inject_pty, pty_candidate

    out, ch = inject_pty("#!/bin/sh\nset -e\ngo build .\n")
    assert ch and "determinex_pty_plugin" in out and "pytest11" in out
    assert "DETERMINEX_PTY_TIMEOUT" in out and "killpg" in out  # the real anti-hang mechanism
    _, ch2 = inject_pty(out)
    assert not ch2, "must be idempotent"
    # candidate fires on a TUI test failure, not on a plain assertion failure
    rep = tmp_path / "r.json"
    rep.write_text(
        '{"test_results":[{"status":"failed","name":"test_tui_render"}]}', encoding="utf-8"
    )
    ok, _ = pty_candidate(rep)
    assert ok
    rep.write_text(
        '{"test_results":[{"status":"failed","name":"test_add_numbers"}]}', encoding="utf-8"
    )
    ok2, _ = pty_candidate(rep)
    assert not ok2


# ── synthesized-oracle element typing (found live on a Radeon GPU, 2026-08-02) ──────────


def test_a_list_of_pairs_is_not_typed_as_a_list_of_ints():
    """THE BUG. `_infer_input_type` returned bare "list" for every list literal, so an
    interval merger taking list[tuple[int,int]] got the list-of-INTS fuzz strategy and the
    emitted property test called merge([1, 2, 3]). Every correct implementation fails that.
    Measured live: 16 sampled candidates all failed exactly one check and the run reported
    'not solved' about a task the model may well have solved.

    This is the same slop the 2026-07-20 fix was written for -- but a guard cannot be more
    precise than the type lattice it compares against, and list[int] and list[tuple[int,int]]
    were the same type as far as inference was concerned.
    """
    from determinex_synthesize import _infer_input_type, parse_spec

    spec = parse_spec("merge([(1,3),(2,6)]) == [(1,6)]", "python")
    assert _infer_input_type(spec) == "list[tuple2]"


def test_a_plain_list_of_ints_is_still_a_plain_list():
    """Negative control: refining the lattice must not reclassify what already worked."""
    from determinex_synthesize import _infer_input_type, parse_spec

    spec = parse_spec("dedupe([3,1,3]) == [1,3]", "python")
    assert _infer_input_type(spec) == "list"


def test_an_untypeable_element_yields_no_type_rather_than_a_wrong_one():
    """`merge([])` is a real example that carries no element evidence, and a list of
    strings has no strategy here. Both must return None so the caller SKIPS the property
    test -- emitting one is precisely the slop this module exists to prevent."""
    from determinex_synthesize import _infer_input_type, parse_spec

    assert _infer_input_type(parse_spec("f([]) == []", "python")) is None
    assert _infer_input_type(parse_spec("f(['a','b']) == ['a']", "python")) is None


def test_the_sorted_template_uses_the_typed_strategy_not_a_hardcoded_one():
    """The 2026-07-20 type-aware-strategy fix reached every template EXCEPT this one, which
    kept a literal `st.lists(st.integers(-100, 100), max_size=20)`. A per-type strategy
    table is worthless if a template ignores it, and nothing asserted the templates use it."""
    from determinex_synthesize import _PROPERTY_TEMPLATES_HYPOTHESIS

    for name, entry in _PROPERTY_TEMPLATES_HYPOTHESIS.items():
        _types, body = entry
        assert "st.integers(-100, 100)" not in body, (
            f"template {name!r} hardcodes a strategy instead of using {{strategy}}"
        )
        if "@given(" in body:
            assert "@given({strategy})" in body, f"template {name!r} must parameterise @given"


def test_a_correct_interval_merger_passes_its_own_synthesized_oracle():
    """End-to-end soundness. The oracle is only ground truth if a known-correct program
    passes it; before the fix this failed 1 of 5 for every correct implementation, which is
    an oracle rejecting the truth."""
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    from determinex_synthesize import parse_spec, synthesize_oracle_tests

    idea = (
        "merge(intervals) takes a list of (start, end) integer tuples, drops any where "
        "start > end, merges overlapping and touching intervals, and returns them sorted "
        "ascending by start.\n\n"
        "merge([(1,3),(2,6),(8,10),(15,18)]) == [(1,6),(8,10),(15,18)]\n"
        "merge([(1,4),(4,5)]) == [(1,5)]\n"
        "merge([(5,1),(2,3)]) == [(2,3)]\n"
        "merge([]) == []\n"
    )
    code = synthesize_oracle_tests(parse_spec(idea, "python"))
    impl = (
        "def merge(intervals):\n"
        "    xs = sorted((a, b) for a, b in intervals if a <= b)\n"
        "    out = []\n"
        "    for a, b in xs:\n"
        "        if out and a <= out[-1][1]:\n"
        "            out[-1] = (out[-1][0], max(out[-1][1], b))\n"
        "        else:\n"
        "            out.append((a, b))\n"
        "    return out\n"
    )
    with tempfile.TemporaryDirectory() as d:
        Path(d, "solution.py").write_text(impl, encoding="utf-8")
        Path(d, "test_oracle.py").write_text(code, encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_oracle.py"],
                           cwd=d, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"a correct implementation failed its own oracle:\n{r.stdout[-1500:]}"
