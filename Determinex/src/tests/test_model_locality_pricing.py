"""Is a local model recognised as free -- by the pricer and by the router?

WHY THIS EXISTS
---------------
Found 2026-07-29. Both the budget guard and the router decided "is this local?" with
prefix tests that required a slash:

    model.startswith("ollama/") or model.startswith("determinex/")

hive/ctx_config.py assigns the roles BARE Ollama tags by default --
`determinex-engineer-v11-dsl` starts with "determinex-", not "determinex/" -- so the
project's own local models matched neither prefix. Consequences, both silent:

  * budget: priced at the $0.008/1K blended fallback, $0.012 per builder step against a
    $2.00 default session budget. A fully local session accrued fictional spend, showed
    it in the UI, and on a long enough run tripped `budget_exhausted` and logged
    "API BUDGET EXHAUSTED - switching to local-only mode" while never having left local.

  * router: no prefix matched, so the free local default builder was rated
    _UNKNOWN_TIER (3, paid) -- the top of the ladder the router exists to climb from the
    bottom, and a distortion of the cost figures the A/B reports.

api_client._resolve_model already carried a comment about this exact trap ("bare model
names ... have no slash - but they ARE local Ollama models"); it resolves via
litellm_config.yaml's alias map, and the three bare tags are not in it.

BOTH DIRECTIONS ARE TESTED. Pricing a local model as paid wastes budget; pricing a cloud
model as free hides real spend, which is strictly worse. So the cloud cases below are not
symmetry for its own sake -- they pin the direction that must never regress, including
the reason the fix refuses to guess from tag syntax: Bedrock's `anthropic.claude-v2:1`
has a colon and no slash, so any "looks like an Ollama tag" heuristic would price a real
cloud call at zero.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from hive.budget import _estimate_cost_usd, is_local_model  # noqa: E402
from hive.router_bridge import tier_and_cost  # noqa: E402


def _live_role_defaults() -> dict[str, str]:
    """The role->model map hive/ctx_config.py actually ships, read from the module
    rather than restated here -- a copy would keep passing after the defaults change,
    which is the failure mode this whole file is about."""
    import hive.ctx_config as ctx

    for value in vars(ctx).values():
        if (
            isinstance(value, dict)
            and isinstance(value.get("engineer"), str)
            and value["engineer"].startswith("determinex")
        ):
            return value
    pytest.fail("could not find the role->model defaults in hive/ctx_config.py")


def test_the_live_default_role_models_are_free():
    """THE regression. These three strings are what a default hive session bills."""
    roles = _live_role_defaults()
    assert roles, "no role defaults found"
    for role, model in roles.items():
        cost = _estimate_cost_usd(model, 1500, None, None)
        assert cost == 0.0, f"{role} model {model!r} billed ${cost} per step"


def test_the_live_default_role_models_route_as_cheapest_tier():
    """Same strings, the other consumer. Tier 1 is the bottom of the ladder."""
    for role, model in _live_role_defaults().items():
        tier, cost = tier_and_cost(model)
        assert (tier, cost) == (1, 0.0), f"{role} model {model!r} rated tier={tier} cost={cost}"


@pytest.mark.parametrize(
    "model",
    [
        "ollama/determinex-engineer-v11-dsl",
        "ollama_chat/qwen2.5-coder:14b",
        "hosted_vllm/some-model",
        "determinex/engineer",
        "determinex-engineer-v11-dsl",
        "determinex-observer-v6-dsl",
        "local/qwen",
        "DETERMINEX-ENGINEER-V11-DSL",  # case is not a locality signal
        "  determinex-engineer-v11-dsl  ",  # nor is surrounding whitespace
    ],
)
def test_local_forms_are_free(model):
    assert is_local_model(model) is True, f"{model!r} not recognised as local"
    assert _estimate_cost_usd(model, 10_000, 8_000, 2_000) == 0.0


@pytest.mark.parametrize(
    "model",
    [
        "deepseek/deepseek-chat",
        "claude-sonnet-4-6",
        "openrouter/deepseek/deepseek-v4-flash",
        "gpt-4o",
        "anthropic.claude-v2:1",  # colon, no slash: why we do not guess from tag syntax
    ],
)
def test_cloud_models_are_never_free(model):
    """The direction that must never regress. Under-reporting spend overspends real
    money; over-reporting merely exhausts the budget early and falls back to local."""
    assert is_local_model(model) is False, f"{model!r} misread as local"
    assert _estimate_cost_usd(model, 10_000, 8_000, 2_000) > 0.0


def test_an_unknown_model_is_assumed_paid():
    """The conservative fallback, stated as a requirement rather than an accident:
    an unrecognised name must cost something, so a mispriced model fails toward not
    spending instead of toward silent overspend."""
    assert is_local_model("some-model-nobody-has-heard-of") is False
    assert _estimate_cost_usd("some-model-nobody-has-heard-of", 10_000, None, None) > 0.0
    assert tier_and_cost("some-model-nobody-has-heard-of")[0] == 3


def test_budget_exhaustion_cannot_trigger_on_a_local_only_session():
    """The user-visible symptom, end to end: run a long local session's worth of
    billing through the real guard and assert the budget never moves. Before the fix
    this crossed a $2.00 budget after ~167 steps and flipped to 'local-only mode'
    while already local."""
    from hive.budget import record_api_call_cost

    class _Session:
        api_cost_usd = 0.0
        session_budget_usd = 2.0
        budget_exhausted = False

    session = _Session()
    builder = _live_role_defaults()["engineer"]
    for _ in range(500):
        assert record_api_call_cost(session, 1500, model=builder) is True
    assert session.api_cost_usd == 0.0
    assert session.budget_exhausted is False


# ── the cloud spend cap, which is the direction that costs real money ────────


def test_a_prefixed_cloud_model_is_priced_by_the_cap():
    """THE serious one. BudgetGuard.estimate_cost and .charge did
    `PRICING.get(model, (0.0, 0.0))` -- exact key, defaulting to FREE -- while PRICING's
    keys are bare (`deepseek-chat`) and the strings litellm needs carry a provider
    prefix. So a prefixed cloud model cost $0, `spend_usd` never moved, and the USD cap
    never engaged, on the module whose only job is refusing to overspend.

    It survived because the PB driver's defaults are bare names, which priced fine.
    `DETERMINEX_DEEPSEEK_MODEL` set to the OpenRouter-prefixed form -- the form
    CLAUDE.md's .env implies -- silently disabled the cap.
    """
    import budget_guard as bg

    bare = bg.estimate_cost_usd("deepseek-chat", 800_000, 200_000)
    assert bare > 0
    for prefixed in (
        "deepseek/deepseek-chat",
        "openrouter/deepseek/deepseek-v4-flash",
        "anthropic/claude-sonnet-4-6",
    ):
        cost = bg.estimate_cost_usd(prefixed, 800_000, 200_000)
        assert cost > 0, f"{prefixed} priced at $0 -- the cap cannot engage"


def test_the_cap_actually_stops_a_prefixed_model():
    """End to end through the real gate, not just the pricer: a prefixed model has to
    be able to exhaust the cap. Before the fix this loop ran forever at $0/call."""
    import budget_guard as bg

    guard = bg.BudgetGuard.__new__(bg.BudgetGuard)
    guard.state = bg.BudgetState(
        run_name="test-cap", max_usd=1.0, max_calls=10_000, max_per_task=10_000
    )
    guard._path = None  # _save is patched out below; never touch disk in a test
    guard._save = lambda: None  # type: ignore[method-assign]

    for _ in range(50):
        guard.charge("anthropic/claude-sonnet-4-6", 100_000, 20_000, "task-1")
        if not guard.allow("task-1")[0]:
            break
    assert guard.state.spend_usd > 0, "charging a prefixed cloud model recorded no spend"
    assert guard.allow("task-1")[0] is False, "the USD cap never engaged"


def test_an_unknown_cloud_model_consumes_the_cap_rather_than_being_free():
    """A model nobody added a rate for must still cost something. Free-by-default is
    how a cap silently stops existing."""
    import budget_guard as bg

    assert bg.estimate_cost_usd("some-model-shipped-next-week", 1_000_000, 0) > 0


def test_local_models_never_consume_the_cloud_cap():
    """The other side of the same coin: a local run must not exhaust a cloud budget."""
    import budget_guard as bg

    for model in (
        "ollama/determinex-engineer-v11-dsl",
        "determinex-engineer-v11-dsl",
        "local/qwen",
    ):
        assert bg.estimate_cost_usd(model, 5_000_000, 1_000_000) == 0.0


def test_all_three_cost_consumers_agree():
    """budget_guard (the cap), hive.budget (session pricing) and the usage ledger each
    used to own a locality rule and a price lookup -- three implementations, three
    different wrong answers. They now resolve from one table, so a model cannot be free
    to one and paid to another."""
    import budget_guard as bg
    import determinex_providers as prov
    from hive.budget import is_local_model as hive_is_local

    for model in (
        "deepseek/deepseek-chat",
        "anthropic/claude-sonnet-4-6",
        "ollama/determinex-engineer-v11-dsl",
        "determinex-engineer-v11-dsl",
        "local/qwen",
        "gpt-4o",
    ):
        assert bg.is_local_model(model) == hive_is_local(model), model
        assert prov._is_local_litellm_model(model) == bg.is_local_model(model), model


def test_the_ledger_uses_the_real_per_model_rate():
    """The gas gauge billed a flat $1/$1 for everything: it invented spend for free
    local calls and under-reported claude-sonnet (3.00/15.00) by roughly 10x. A gauge
    that under-reports the expensive model is worse than no gauge."""
    import budget_guard as bg
    import determinex_providers as prov

    assert prov._ledger_rate("anthropic/claude-sonnet-4-6") == bg.PRICING["claude-sonnet-4-6"]
    # The supplement dict still wins for models the canonical table does not carry.
    assert prov._ledger_rate("huggingface/qwen/qwen2.5-coder-32b-instruct") == (0.9, 0.9)
