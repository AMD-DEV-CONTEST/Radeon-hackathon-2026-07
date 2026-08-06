"""End-to-end wiring.

Tests marked `live` need vLLM running and are skipped by default — CI and a
sleep-deprived teammate at hour 19 both need `pytest` to pass without a GPU.
Everything else here checks that the pieces fit together: registry dispatch,
tool allowlists and budgets, the scoring axes, and a full orchestrator loop
against a stub client.

Run the live ones deliberately:  pytest -m live
"""
from __future__ import annotations

import asyncio
import json

import pytest

from veil.agents.personas import ALL_PERSONAS, BY_NAME
from veil.tools.registry import REGISTRY, ToolBudgetExceeded, ToolNotPermitted
from veil.types import Finding, Span, Tier
import veil.tools  # noqa: F401  — registers everything


class TestRegistry:
    def test_every_persona_tool_is_registered(self):
        registered = {name for name in REGISTRY._tools}
        for persona in ALL_PERSONAS:
            missing = set(persona.tools) - registered
            assert not missing, f"{persona.name} references unregistered tools: {missing}"

    def test_schemas_are_valid_openai_function_specs(self):
        for spec in REGISTRY.schemas_for(tuple(REGISTRY._tools)):
            fn = spec["function"]
            assert spec["type"] == "function"
            assert fn["name"] and fn["description"]
            assert fn["parameters"]["type"] == "object"
            json.dumps(spec)   # must be serialisable for the request body

    @pytest.mark.asyncio
    async def test_allowlist_blocks_an_unpermitted_tool(self):
        tools = REGISTRY.for_persona("Stylometrist", (), budget=6)
        with pytest.raises(ToolNotPermitted, match="corpus_search"):
            await tools.call("corpus_search", {"query": "anything"})

    @pytest.mark.asyncio
    async def test_budget_is_enforced(self):
        tools = REGISTRY.for_persona("Data-Broker", ("date_math",), budget=2)
        for _ in range(2):
            await tools.call("date_math", {"operation": "resolve", "date_a": "2019-03-14"})
        with pytest.raises(ToolBudgetExceeded):
            await tools.call("date_math", {"operation": "resolve", "date_a": "2019-03-14"})

    @pytest.mark.asyncio
    async def test_calls_are_recorded_for_evidence(self):
        REGISTRY.calls.clear()
        tools = REGISTRY.for_persona("Data-Broker", ("date_math",), budget=3)
        await tools.call("date_math", {"operation": "precision", "date_a": "14 March 2019"})
        assert REGISTRY.calls[-1].tool == "date_math"
        assert REGISTRY.calls[-1].persona == "Data-Broker"
        assert REGISTRY.calls[-1].error is None


class TestPersonaDefinitions:
    def test_five_personas_with_distinct_names(self):
        assert len(ALL_PERSONAS) == 5
        assert len(BY_NAME) == 5

    def test_stylometrist_has_no_tools_and_owns_tier_s(self):
        s = BY_NAME["Stylometrist"]
        assert s.tools == ()
        assert s.primary_tier is Tier.STYLISTIC

    def test_only_the_forensicist_owns_tier_m(self):
        mechanical = [p for p in ALL_PERSONAS if p.primary_tier is Tier.MECHANICAL]
        assert [p.name for p in mechanical] == ["Layout-Forensicist"]

    def test_every_instruction_states_its_evidential_burden(self):
        for p in ALL_PERSONAS:
            text = p.instruction.lower()
            if p.primary_tier is Tier.CORRELATIONAL:
                assert "candidate" in text
            if p.primary_tier is Tier.STYLISTIC:
                assert "caveat" in text or "unreliable" in text


class TestToolBehaviour:
    def test_candidate_set_flags_uniqueness(self):
        from veil.tools.candidate_set import candidate_set_size

        out = candidate_set_size(
            ["job_title_specific", "city", "exact_date", "tenure_year"],
            base_population="organisation",
        )
        assert out["candidate_set_size"] >= 1
        assert "UNIQUE" in out["verdict"] or "CRITICAL" in out["verdict"]
        assert out["assumptions"]

    def test_candidate_set_reports_unrecognised_attributes(self):
        from veil.tools.candidate_set import candidate_set_size

        out = candidate_set_size(["job_title_broad", "favourite_biscuit"])
        assert out["attributes_unrecognised"] == ["favourite_biscuit"]

    def test_date_math_precision_suggests_generalisations(self):
        from veil.tools.date_math import date_math

        out = date_math("precision", "14 March 2019")
        assert out["ok"]
        assert "March 2019" in out["suggested_generalisations"]
        assert "2019" in out["suggested_generalisations"]

    def test_date_math_rejects_unparseable_input_without_crashing(self):
        from veil.tools.date_math import date_math

        assert date_math("resolve", "sometime last spring")["ok"] is False

    def test_cooccurrence_requires_two_terms(self):
        from veil.tools.cooccurrence import cooccurrence_count

        assert cooccurrence_count(["Bristol"])["ok"] is False


class TestScoring:
    def test_one_mechanical_finding_dominates_the_score(self):
        from veil.scoring.risk import score

        m = Finding(persona="Layout-Forensicist", tier=Tier.MECHANICAL,
                    claim="name recovered", reasoning="r", severity=0.95)
        assert score([m]).band == "CRITICAL"

    def test_resolved_findings_do_not_count(self):
        from veil.scoring.risk import score

        m = Finding(persona="p", tier=Tier.MECHANICAL, claim="c", reasoning="r",
                    severity=0.95)
        m.resolved = True
        result = score([m])
        assert result.value == 0.0 and result.band == "MINIMAL"

    def test_stylistic_findings_cannot_reach_critical(self):
        from veil.scoring.risk import score

        findings = [
            Finding(persona="Stylometrist", tier=Tier.STYLISTIC, claim=f"c{i}",
                    reasoning="r", caveat="short text", severity=1.0)
            for i in range(6)
        ]
        assert score(findings).value < 0.6

    def test_utility_headline_is_the_minimum_of_its_axes(self):
        from veil.scoring.utility import score

        doc = "The team shipped 4 features in Q3 2024 across 12 markets."
        gutted = "The team shipped [REDACTED] features in [REDACTED] across [REDACTED] markets."
        u = score(doc, gutted)
        axes = [u.token_retention, u.structure_intact] + (
            [u.semantic_fidelity] if u.semantic_fidelity is not None else []
        )
        assert u.value == min(axes)

    def test_unchanged_document_retains_full_utility(self):
        from veil.scoring.utility import score

        doc = "Nothing was removed from this sentence."
        assert score(doc, doc).token_retention == 1.0


class _StubClient:
    """Deterministic stand-in for vLLM so the loop is testable without a GPU."""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls = 0

    async def complete(self, prefix, suffix, max_tokens=None, temperature=None):
        from veil.inference.client import CallMetrics

        self.calls += 1
        text = self.script.pop(0) if self.script else "[]"
        return text, CallMetrics(prompt_tokens=100, completion_tokens=20, latency_s=0.1)

    async def prefix_cache_stats(self):
        return {"available": False}


class TestOrchestratorLoop:
    @pytest.mark.asyncio
    async def test_clean_document_terminates_immediately(self):
        from veil.agents.orchestrator import Orchestrator

        orch = Orchestrator()
        orch.client = _StubClient(["[]"] * 20)
        orch.guardian.client = orch.client

        doc = "Nothing identifying here at all."
        report = await orch.run(doc, [Span(0, len(doc), doc)], max_iterations=2)

        assert report.curve[0]["residual_risk"] == 0.0
        assert "No findings" in report.stopped_because or report.curve[0]["risk_band"] == "MINIMAL"
        assert report.final_text == doc

    @pytest.mark.asyncio
    async def test_progress_events_are_emitted_in_order(self):
        from veil.agents.orchestrator import Orchestrator

        events: list[str] = []

        async def capture(payload):
            events.append(payload["event"])

        orch = Orchestrator(on_progress=capture)
        orch.client = _StubClient(["[]"] * 20)
        orch.guardian.client = orch.client

        doc = "A short document."
        await orch.run(doc, [Span(0, len(doc), doc)], max_iterations=1)

        assert events[0] == "planned"
        assert events[1] == "iteration_start"
        assert "persona_start" in events and "persona_done" in events
        assert "adjudicated" in events and "scored" in events
        assert events[-1] == "run_complete"

    @pytest.mark.asyncio
    async def test_a_failing_persona_does_not_kill_the_run(self):
        from veil.agents.orchestrator import Orchestrator

        class Exploding(_StubClient):
            async def complete(self, prefix, suffix, max_tokens=None, temperature=None):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("simulated GPU hiccup")
                return await super().complete(prefix, suffix, max_tokens, temperature)

        orch = Orchestrator()
        orch.client = Exploding(["[]"] * 20)
        orch.guardian.client = orch.client

        doc = "A short document."
        report = await orch.run(doc, [Span(0, len(doc), doc)], max_iterations=1)
        assert report.curve   # the run completed despite one persona dying

    @pytest.mark.asyncio
    async def test_personas_run_concurrently_not_serially(self):
        from veil.agents.orchestrator import Orchestrator

        class Slow(_StubClient):
            async def complete(self, prefix, suffix, max_tokens=None, temperature=None):
                await asyncio.sleep(0.2)
                return await super().complete(prefix, suffix, max_tokens, temperature)

        orch = Orchestrator()
        orch.client = Slow(["[]"] * 20)
        orch.guardian.client = orch.client

        doc = "A short document."
        started = asyncio.get_event_loop().time()
        await orch.run(doc, [Span(0, len(doc), doc)], max_iterations=1)
        elapsed = asyncio.get_event_loop().time() - started

        # Five personas at 0.2s each: ~1.0s serial, ~0.2s concurrent.
        assert elapsed < 0.7, f"personas appear to be running serially ({elapsed:.2f}s)"


@pytest.mark.live
class TestAgainstRealServer:
    """Skipped unless vLLM is up. These are the ones to run before the demo."""

    @pytest.mark.asyncio
    async def test_server_is_reachable(self):
        from veil.inference.client import VLLMClient

        if not await VLLMClient().health():
            pytest.skip("vLLM not running")

    @pytest.mark.asyncio
    async def test_prefix_cache_is_enabled_on_the_server(self):
        from veil.inference.client import VLLMClient

        client = VLLMClient()
        if not await client.health():
            pytest.skip("vLLM not running")
        stats = await client.prefix_cache_stats()
        assert stats.get("available"), "vLLM /metrics unreachable"
        assert "gpu_prefix_cache_hit_rate" in stats, (
            "Server was started without --enable-prefix-caching; the five-persona "
            "design will not fit."
        )
