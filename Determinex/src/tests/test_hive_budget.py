"""
Tests for scripts/hive/budget.py's model-aware cost tracking.

Regression coverage for the bug found 2026-07-01: record_api_call_cost()
used one flat blended rate ($8/1M tokens) for every call regardless of
which model was actually hit, silently undercounting premium models
(Claude Opus output alone is $75/1M — ~9x the flat rate) while overcounting
genuinely free local Ollama calls as costing real money. A session could
blow through real dollars while session.budget_exhausted still read
comfortably under the $2 default cap.
"""

from __future__ import annotations

import hive.budget as budget
import pytest
from hive.manifest import ManifestSession


def _session(budget_usd: float = 2.0) -> ManifestSession:
    return ManifestSession(
        session_id="test-session",
        lang="rust",
        md_spec_path="spec.md",
        project_root=".",
        session_budget_usd=budget_usd,
    )


# ── _estimate_cost_usd: pricing correctness ─────────────────────────────────


def test_local_ollama_model_is_free():
    assert budget._estimate_cost_usd("ollama/qwen2.5-coder:14b", 50_000, None, None) == 0.0


def test_local_determinex_model_is_free():
    assert budget._estimate_cost_usd("determinex/rosetta-local", 50_000, None, None) == 0.0


def test_unknown_cloud_model_falls_back_to_flat_rate(caplog):
    cost = budget._estimate_cost_usd("some-brand-new-model", 10_000, None, None)
    assert cost == pytest.approx((10_000 / 1000) * budget.APPROX_COST_PER_1K_TOKENS)


def test_known_model_uses_real_pricing_not_flat_rate():
    flat_rate_cost = (10_000 / 1000) * budget.APPROX_COST_PER_1K_TOKENS
    real_cost = budget._estimate_cost_usd("anthropic/claude-opus-4-6", 10_000, None, None)
    # This is the regression this whole fix exists to prevent: Opus is far
    # more expensive than the old blended flat rate assumed.
    assert real_cost > flat_rate_cost * 5


def test_pricing_lookup_matches_provider_prefixed_model_string():
    # PRICING keys are bare ('claude-opus-4-6'); real litellm model strings
    # carry a provider prefix. Substring match must still find it.
    bare = budget._price_per_1m("claude-opus-4-6")
    prefixed = budget._price_per_1m("anthropic/claude-opus-4-6")
    assert bare == prefixed
    assert bare is not None


def test_exact_prompt_completion_split_is_used_when_available():
    in_rate, out_rate = budget._MODEL_PRICING["claude-opus-4-6"]
    cost = budget._estimate_cost_usd(
        "claude-opus-4-6", 10_000, prompt_tokens=3000, completion_tokens=7000
    )
    expected = (3000 / 1_000_000) * in_rate + (7000 / 1_000_000) * out_rate
    assert cost == pytest.approx(expected)


def test_missing_split_falls_back_to_completion_heavy_assumption():
    in_rate, out_rate = budget._MODEL_PRICING["claude-opus-4-6"]
    cost = budget._estimate_cost_usd("claude-opus-4-6", 10_000, None, None)
    completion = round(10_000 * budget._ASSUMED_COMPLETION_FRACTION)
    prompt = 10_000 - completion
    expected = (prompt / 1_000_000) * in_rate + (completion / 1_000_000) * out_rate
    assert cost == pytest.approx(expected)


# ── record_api_call_cost: session-level integration ─────────────────────────


def test_record_api_call_cost_accumulates_real_cost():
    session = _session(budget_usd=2.0)
    ok = budget.record_api_call_cost(session, 10_000, model="anthropic/claude-opus-4-6")
    assert ok
    assert session.api_cost_usd == pytest.approx(0.57, abs=0.01)
    assert not session.budget_exhausted


def test_record_api_call_cost_exhausts_budget_on_premium_model_faster_than_flat_rate_would():
    session = _session(budget_usd=0.5)
    # Old flat-rate math for this call would have been $0.08 * 4 = $0.32 —
    # under a $0.50 budget. Real Opus cost blows through it in one call.
    ok = budget.record_api_call_cost(session, 10_000, model="anthropic/claude-opus-4-6")
    assert not ok
    assert session.budget_exhausted


def test_record_api_call_cost_local_model_never_exhausts_budget():
    session = _session(budget_usd=0.01)  # tiny budget
    for _ in range(50):
        ok = budget.record_api_call_cost(session, 100_000, model="ollama/qwen2.5-coder:14b")
        assert ok
    assert session.api_cost_usd == 0.0
    assert not session.budget_exhausted


def test_record_api_call_cost_legacy_no_model_call_still_works():
    """Backward compatibility: existing callers that don't pass model= at all
    must not crash — they get the old flat-rate estimate."""
    session = _session()
    ok = budget.record_api_call_cost(session, 1500)
    assert ok
    assert session.api_cost_usd == pytest.approx((1500 / 1000) * budget.APPROX_COST_PER_1K_TOKENS)
