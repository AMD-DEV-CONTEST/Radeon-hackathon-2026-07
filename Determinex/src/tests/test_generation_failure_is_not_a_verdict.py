"""A model that was never reached must not be reported as a model that failed.

MEASURED 2026-07-31. Running the flagship greenfield path exactly as its own `--help` documents:

    determinex_build_from_idea.py --idea reverse_words.md --provider local \
        --model determinex-engineer-v11-dsl:latest --k 6

    result: not solved  samples=12
    proof: no program passed the 4 checks (12 samples).
    next moves: ['behavioral:semantic']

Nothing about that output is true. LiteLLM had raised `BadRequestError: LLM Provider NOT
provided` on all twelve calls, because a bare Ollama tag -- the tag exactly as `ollama list`
prints it -- reached the LiteLLM lane without its `ollama/` prefix. No model produced a single
candidate. The run nevertheless reported a correctness verdict, and the Adjudicator offered a
next move ("behavioral:semantic") derived from failures that did not exist, pointing the reader
at prompt tuning when the fix was a provider setting.

Two separate defects, and both are guarded here:

1. `VerifiedSearch.solve` turned a generator exception into the *string*
   `"__generation_error__: ..."`, which was then digested, deduped and handed to the oracle as
   if it were source code. Because every error string hashed identically, round 2 saw zero
   distinct candidates and diagnosed "model is looping" -- an actively wrong root cause.
2. `get_generator("local", "<bare tag>")` built a generator that raised on every call, rather
   than qualifying a name whose provider the caller had already declared.

After the fix the same command solves on sample 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from determinex_verified_search import VerifiedSearch  # noqa: E402


class _Oracle:
    """A sound-enough oracle for these tests: passes only on the exact target."""

    def __init__(self, target: str = "GOOD") -> None:
        self.target = target
        self.calls: list[str] = []

    def __call__(self, text: str):
        self.calls.append(text)

        class _R:
            passed = text.strip() == self.target
            failures = [] if text.strip() == self.target else [_Failure()]
            score = 1.0 if text.strip() == self.target else 0.0

        return _R()


class _Failure:
    test_id = "t"
    name = "eq"
    text = "wrong"


def _always_raises(msg: str = "LLM Provider NOT provided"):
    def gen(_prompt: str, _temp: float) -> str:
        raise ValueError(msg)

    return gen


class TestABrokenGeneratorIsNotAModelVerdict:
    def test_a_generator_that_always_raises_does_not_report_a_correctness_verdict(self):
        oracle = _Oracle()
        res = VerifiedSearch(verify=oracle, k=3, rounds=2).solve(_always_raises(), "p")
        assert res.solved is False
        assert res.generator_never_answered is True, (
            "the whole point: this result must be distinguishable from a model that tried"
        )

    def test_the_oracle_is_never_asked_to_verify_an_exception_message(self):
        """It used to be handed "__generation_error__: ..." as if it were a candidate."""
        oracle = _Oracle()
        VerifiedSearch(verify=oracle, k=3, rounds=2).solve(_always_raises(), "p")
        assert oracle.calls == [], f"oracle was called with {oracle.calls!r}"

    def test_no_candidate_is_recorded_in_history_for_a_failed_generation(self):
        res = VerifiedSearch(verify=_Oracle(), k=3, rounds=2).solve(_always_raises(), "p")
        assert res.history == []
        assert res.best is None

    def test_the_proof_says_not_attempted_and_carries_the_real_error(self):
        res = VerifiedSearch(verify=_Oracle(), k=2, rounds=1).solve(
            _always_raises("LLM Provider NOT provided"), "p"
        )
        assert "NOT ATTEMPTED" in res.proof
        assert "LLM Provider NOT provided" in res.proof, (
            "a misconfiguration must be diagnosable from the result, not by re-running with logs"
        )

    def test_the_proof_does_not_claim_candidates_failed_the_checks(self):
        """The old proof read "no program passed the 4 checks (12 samples)"."""
        res = VerifiedSearch(verify=_Oracle(), k=3, rounds=2).solve(_always_raises(), "p")
        lowered = res.proof.lower()
        assert "no program passed" not in lowered
        assert "not solved (" not in lowered

    def test_the_next_move_points_at_the_generator_not_at_prompt_tuning(self):
        """It offered ['behavioral:semantic'] -- advice derived from failures that never existed."""
        res = VerifiedSearch(verify=_Oracle(), k=3, rounds=2).solve(_always_raises(), "p")
        assert res.next_moves == ["fix:generator"]

    def test_a_broken_generator_is_not_diagnosed_as_a_looping_model(self):
        res = VerifiedSearch(verify=_Oracle(), k=3, rounds=2).solve(_always_raises(), "p")
        assert "looping" not in res.proof.lower()

    def test_the_error_count_is_recorded_so_a_caller_can_check_it(self):
        res = VerifiedSearch(verify=_Oracle(), k=4, rounds=1).solve(_always_raises(), "p")
        assert res.generation_errors == 4
        assert res.total_samples == 4


class TestPartialGenerationFailureIsStillVisible:
    def test_a_solve_still_succeeds_when_only_some_samples_error(self):
        """Robustness must not regress: one bad call should not sink a good run."""
        calls = {"n": 0}

        def flaky(_p: str, _t: float) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("first call died")
            return "GOOD"

        res = VerifiedSearch(verify=_Oracle(), k=3, rounds=1).solve(flaky, "p")
        assert res.solved is True
        assert res.generation_errors == 1
        assert res.generator_never_answered is False

    def test_a_partial_failure_is_disclosed_in_the_proof_of_a_failed_run(self):
        """Otherwise "4 samples" overstates how many attempts the model actually made."""
        calls = {"n": 0}

        def flaky(_p: str, _t: float) -> str:
            calls["n"] += 1
            if calls["n"] <= 2:
                raise TimeoutError("died")
            return f"BAD-{calls['n']}"

        res = VerifiedSearch(verify=_Oracle(), k=4, rounds=1).solve(flaky, "p")
        assert res.solved is False
        assert res.generation_errors == 2
        assert res.generator_never_answered is False
        assert "failed to generate" in res.proof, res.proof

    def test_a_healthy_run_reports_zero_generation_errors(self):
        res = VerifiedSearch(verify=_Oracle(), k=2, rounds=1).solve(lambda _p, _t: "GOOD", "p")
        assert res.solved is True
        assert res.generation_errors == 0
        assert res.generation_error_sample == ""
        assert res.generator_never_answered is False

    def test_generator_never_answered_is_false_on_an_empty_run(self):
        """0/0 must not read as "everything failed"."""
        res = VerifiedSearch(verify=_Oracle(), k=1, rounds=1).solve(lambda _p, _t: "GOOD", "p")
        assert res.total_samples > 0
        # And the property is guarded against a zero-sample division-style trap:
        from determinex_verified_search import SearchResult

        empty = SearchResult(solved=False, best=None, rounds_used=0, total_samples=0, proof="")
        assert empty.generator_never_answered is False


class TestABareOllamaTagIsQualifiedForTheLocalProvider:
    """Third occurrence of this footgun: budget.is_local_model and api_client._resolve_model
    both already carry comments about bare Ollama tags."""

    @staticmethod
    def _providers():
        try:
            import determinex_providers as P
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"determinex_providers unavailable: {exc}")
        return P

    def test_a_bare_tag_gets_the_ollama_prefix(self):
        P = self._providers()
        loc = P._PROVIDERS["local"]
        assert P._qualify_local_model(loc, "determinex-engineer-v11-dsl:latest") == (
            "ollama/determinex-engineer-v11-dsl:latest"
        )

    def test_an_already_qualified_name_is_untouched(self):
        P = self._providers()
        loc = P._PROVIDERS["local"]
        for name in ("ollama/x:latest", "openrouter/deepseek/deepseek-chat", "ollama_chat/y"):
            assert P._qualify_local_model(loc, name) == name

    def test_an_empty_name_is_untouched_so_the_default_still_applies(self):
        P = self._providers()
        assert P._qualify_local_model(P._PROVIDERS["local"], "") == ""

    def test_a_non_local_provider_is_never_rewritten(self):
        """`budget.is_local_model` refuses to infer locality from a name for good reason:
        Bedrock ships `anthropic.claude-v2:1` -- colon, no slash. Prefixing that would be the
        exact mistake this repo already documented. Here the caller DECLARED provider=local,
        which is why honouring it is not inference."""
        P = self._providers()
        # Skip by provider.NAME, not by dict key: _PROVIDERS is keyed by alias, so the key
        # "ollama" maps to the provider named "local" and is correctly rewritten. Writing this
        # test the other way flagged that as a violation -- the qualifier keys off provider.name
        # precisely so an alias resolves to the same decision.
        for key, provider in P._PROVIDERS.items():
            if provider.name in P._OLLAMA_BACKED_PROVIDERS:
                continue
            assert P._qualify_local_model(provider, "anthropic.claude-v2:1") == (
                "anthropic.claude-v2:1"
            ), f"provider {provider.name!r} (key {key!r}) rewrote a Bedrock-shaped model name"

    def test_an_alias_of_the_local_provider_is_qualified_too(self):
        """_PROVIDERS is keyed by alias; `ollama` is an alias for `local`. Both must behave
        identically, which is why the qualifier tests provider.name and not the lookup key."""
        P = self._providers()
        aliases = [k for k, v in P._PROVIDERS.items() if v.name in P._OLLAMA_BACKED_PROVIDERS]
        assert len(aliases) > 1, f"expected the local provider to have an alias: {aliases}"
        for key in aliases:
            assert P._qualify_local_model(P._PROVIDERS[key], "some-tag:latest") == (
                "ollama/some-tag:latest"
            ), f"alias {key!r} did not qualify a bare tag"

    def test_the_local_default_model_is_still_prefixed_in_config(self):
        """If the shipped default ever loses its prefix, the qualifier hides it. Assert it."""
        P = self._providers()
        default = P._PROVIDERS["local"].default_model
        assert "/" in default, f"local default_model should name its provider: {default!r}"


class TestTheDistinctionSurvivesToTheIdeBoundary:
    """A fix that stops at the first layer is a fix the UI never sees.

    `VerifiedSearch` learned to separate "the model answered and was wrong" from "the model was
    never reached". `BuildResult` then dropped both counts, so `_build_from_idea`'s IDE payload
    still rendered a wholly unreachable provider as `solved: false, samples: N` -- the same
    indistinguishable outcome, one boundary further out. Found by running the four governed backend
    commands end to end rather than by reading the code.
    """

    @staticmethod
    def _broken(_prompt, _temp):
        raise ValueError("LLM Provider NOT provided (simulated)")

    IDEA = (
        "Write a function double(x: int) -> int that returns x*2.\n"
        "Examples:\n- double(2) == 4\n- double(0) == 0\n- double(-3) == -6\n"
    )

    def test_build_result_carries_the_generation_error_counts(self):
        import determinex_build_from_idea as G

        res = G.build_from_idea(self.IDEA, self._broken, k=3)
        assert res.solved is False
        assert res.generation_errors == res.samples > 0
        assert res.generator_never_answered is True

    def test_build_result_proof_says_not_attempted_rather_than_no_program_passed(self):
        import determinex_build_from_idea as G

        res = G.build_from_idea(self.IDEA, self._broken, k=3)
        assert "NOT ATTEMPTED" in res.proof, res.proof
        assert "no program passed" not in res.proof.lower(), (
            "that phrasing asserts candidates existed"
        )
        assert res.next_moves == ["fix:generator"]

    def test_no_best_effort_code_is_returned_when_nothing_was_generated(self):
        """Returning a "best" candidate here would be returning an exception message as code."""
        import determinex_build_from_idea as G

        res = G.build_from_idea(self.IDEA, self._broken, k=3)
        assert res.code == ""

    def test_a_healthy_build_reports_zero_generation_errors(self):
        import determinex_build_from_idea as G

        good = "def double(x: int) -> int:\n    return x * 2\n"
        res = G.build_from_idea(self.IDEA, lambda _p, _t: f"```python\n{good}```", k=2)
        assert res.generation_errors == 0
        assert res.generator_never_answered is False

    def test_the_ide_payload_exposes_both_fields(self):
        """The gate is the payload, not the dataclass: the UI only sees what is serialised."""
        surface = (REPO_ROOT / "scripts" / "ide" / "backend_command_surface.py").read_text(
            encoding="utf-8"
        )
        assert '"generation_errors"' in surface
        assert '"generator_never_answered"' in surface

    def test_the_extension_sends_the_field_name_the_backend_reads(self):
        """Unrelated to generation errors, but the same class of boundary mismatch: I called this
        command with `idea` and got `n_checks: 0, note: "empty idea"` for a full idea. The backend
        reads `idea_text`. The shipped extension gets it right; assert it stays right."""
        ext = (REPO_ROOT / "frontend" / "vscode-extension" / "src" / "extension.ts").read_text(
            encoding="utf-8"
        )
        surface = (REPO_ROOT / "scripts" / "ide" / "backend_command_surface.py").read_text(
            encoding="utf-8"
        )
        assert "idea_text" in ext, "the extension must send idea_text"
        assert "idea_text" in surface, "the backend must read idea_text"


class TestADegenerateSamplerIsNotAModelVerdict:
    """A provider that ignores `temperature` silently reduces verified search to K=1.

    MEASURED 2026-07-31 against OpenRouter's free tier: four draws at t=0.0/0.5/1.0/1.0
    returned BYTE-IDENTICAL text (same sha256), and a k=8 x 2-round reimpl run logged 15
    "duplicate, skipped" out of 16 samples. The run then reported "238 fail" as though it
    had genuinely tried sixteen times.

    The old diagnosis was "no distinct candidates (model is looping)". That sends the
    reader at the prompt when the fix is the provider. Same class as the two faults already
    documented in this module -- a provider fault wearing a model verdict's clothes.
    """

    class _R:
        passed = False
        score = 0.0

        def __init__(self):
            self.failures = [type("F", (), {"test_id": "t", "name": "n", "text": "x"})()]

    def _search(self, gen, k=8, rounds=2):
        from determinex_verified_search import VerifiedSearch

        return VerifiedSearch(
            verify=lambda _t: self._R(), k=k, rounds=rounds, adjudicate=False
        ).solve(gen, "p")

    def test_a_temperature_ignoring_provider_is_named_as_such(self):
        res = self._search(lambda _p, _t: "IDENTICAL OUTPUT")
        assert res.solved is False
        assert "SAMPLER IGNORED TEMPERATURE" in res.proof, res.proof

    def test_it_is_not_misdiagnosed_as_a_looping_model(self):
        res = self._search(lambda _p, _t: "IDENTICAL OUTPUT")
        assert "looping" not in res.proof.lower(), (
            "the model is not looping; the provider is not sampling"
        )

    def test_the_proof_says_it_is_a_provider_fault_not_a_capability_verdict(self):
        res = self._search(lambda _p, _t: "IDENTICAL OUTPUT")
        low = res.proof.lower()
        assert "provider" in low and "not a model capability verdict" in low, res.proof

    def test_the_proof_reports_how_many_temperatures_were_actually_tried(self):
        """Without the counts a reader cannot tell this from an unlucky single draw."""
        res = self._search(lambda _p, _t: "IDENTICAL OUTPUT")
        assert "distinct temperatures" in res.proof
        assert "8 draws" in res.proof, res.proof

    def test_a_varying_sampler_is_never_flagged(self):
        """Negative control: the check must not fire on a healthy provider."""
        res = self._search(lambda _p, t: f"varies at {t}")
        assert "SAMPLER IGNORED TEMPERATURE" not in res.proof, res.proof

    def test_a_single_temperature_run_is_never_flagged(self):
        """With k=1 there is only one temperature, so identical output proves nothing."""
        res = self._search(lambda _p, _t: "IDENTICAL", k=1, rounds=1)
        assert "SAMPLER IGNORED TEMPERATURE" not in res.proof, res.proof

    def test_a_degenerate_sampler_that_solves_still_solves(self):
        """The check must not steal a win: one identical-but-correct answer is still a pass."""
        from determinex_verified_search import VerifiedSearch

        class _Pass:
            passed = True
            failures: list = []
            score = 1.0

        res = VerifiedSearch(verify=lambda _t: _Pass(), k=8, rounds=2, adjudicate=False).solve(
            lambda _p, _t: "IDENTICAL", "p"
        )
        assert res.solved is True


class TestAFencedCandidateIsNotAModelVerdict:
    """Same class as the module docstring, one provider further out.

    MEASURED 2026-07-31 against a Radeon-hosted vLLM (Qwen2.5-Coder-7B-Instruct):

        result: not solved  samples=12
        [vs] r1 s1/6 t=0.0 gen 9s verify 1s -> 1 fail (score 0.00)   (x12)

    The model was right. Every candidate was a correct RLE implementation wrapped in a
    ```python fence -- which the solve prompt itself demands ("Return ONLY the code in a
    ```python block"). `_strip_fence` was applied in exactly one place, inside
    `ollama_generator`, so the Ollama path was fence-safe and every other provider handed
    fenced markdown to the oracle, where `from solution import *` raised SyntaxError. The
    run reported a correctness verdict about a model that had answered correctly twelve times.

    `test_a_healthy_build_reports_zero_generation_errors` above already passed fenced code
    -- and asserted only that no generation error occurred, never that the build solved.
    That is why a green suite carried this. These tests assert the outcome instead.
    """

    IDEA = (
        "Write a function double(x: int) -> int that returns x*2.\n"
        "Examples:\n- double(2) == 4\n- double(0) == 0\n- double(-3) == -6\n"
    )
    GOOD = "def double(x: int) -> int:\n    return x * 2\n"

    def test_a_fenced_correct_candidate_solves(self):
        import determinex_build_from_idea as G

        res = G.build_from_idea(self.IDEA, lambda _p, _t: f"```python\n{self.GOOD}```", k=2)
        assert res.solved is True, (
            f"a correct program was rejected for wearing a fence: {res.proof}"
        )

    def test_an_unfenced_correct_candidate_still_solves(self):
        """The fix must not depend on a fence being present."""
        import determinex_build_from_idea as G

        res = G.build_from_idea(self.IDEA, lambda _p, _t: self.GOOD, k=2)
        assert res.solved is True, res.proof

    def test_a_bare_fence_without_a_language_tag_solves(self):
        import determinex_build_from_idea as G

        res = G.build_from_idea(self.IDEA, lambda _p, _t: f"```\n{self.GOOD}```", k=2)
        assert res.solved is True, res.proof

    def test_prose_around_the_fence_is_discarded(self):
        """Models narrate. "Here's the code:" is not Python."""
        import determinex_build_from_idea as G

        chatty = (
            f"Sure! Here's the implementation:\n\n```python\n{self.GOOD}```\n\nHope that helps!"
        )
        res = G.build_from_idea(self.IDEA, lambda _p, _t: chatty, k=2)
        assert res.solved is True, res.proof

    def test_the_returned_code_is_clean_source_not_markdown(self):
        """A caller writes result.code to a file; a fence there is a SyntaxError downstream."""
        import determinex_build_from_idea as G

        res = G.build_from_idea(self.IDEA, lambda _p, _t: f"```python\n{self.GOOD}```", k=2)
        assert "```" not in res.code, f"fence survived into returned code: {res.code!r}"
        compile(res.code, "<returned>", "exec")

    def test_a_fenced_wrong_candidate_still_fails(self):
        """The fix must not turn the oracle lenient -- stripping is not passing."""
        import determinex_build_from_idea as G

        wrong = "def double(x: int) -> int:\n    return x + 2\n"
        res = G.build_from_idea(self.IDEA, lambda _p, _t: f"```python\n{wrong}```", k=2)
        assert res.solved is False

    def test_fenced_and_unfenced_copies_are_one_candidate_not_two(self):
        """Dedup compares post-strip text, so the same program submitted both ways is not
        counted (and re-verified) as two distinct candidates."""
        import determinex_build_from_idea as G

        seen: list[str] = []

        def verify_counting(_p, _t):
            seen.append("x")
            return f"```python\n{self.GOOD}```" if len(seen) % 2 else self.GOOD

        res = G.build_from_idea(self.IDEA, verify_counting, k=4)
        assert res.solved is True, res.proof


class TestImportingAModuleDoesNotRewriteTheProviderRegistry:
    """A module that re-registers a provider at import must preserve its invariants.

    `determinex_pb_reimpl._register_raw_factories` deliberately replaces several providers so
    the whole system uses its proven raw-API generators instead of LiteLLM (documented there:
    LiteLLM degraded DeepSeek to 7/10 syntax errors). That is legitimate. Registering `local`
    with a BARE Ollama tag was not: the tag routes nowhere except that module's own factory,
    and the replacement is process-wide, so importing a ProgramBench helper silently changed
    which model every other caller's `local` provider would run.

    It surfaced as test pollution -- the prefix assertion above passed alone and failed
    whenever a PB test had imported first -- which is the signature of global state rewritten
    at import, not of a flaky test.
    """

    def test_the_pb_reimpl_registration_keeps_the_local_default_prefixed(self):
        import importlib
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import determinex_providers as dp

        reimpl = importlib.import_module("determinex_pb_reimpl")
        reimpl._register_raw_factories()

        default = dp._PROVIDERS["local"].default_model
        assert "/" in default, (
            f"importing determinex_pb_reimpl left the local provider with an unqualified "
            f"default: {default!r}"
        )
