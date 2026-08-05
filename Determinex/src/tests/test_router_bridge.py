"""The Model Router wired into the hive build loop.

`amplifier_bridge` samples ONE model K times against the Compiler Oracle.
`router_bridge` walks a LADDER cheapest-first and escalates only when verified
search on the cheap tier exhausts. Both existed; only the amplifier was wired into
`executor.execute_step`, so the router was unit-tested machinery with no live caller.

The load-bearing property is that routing changes WHO ATTEMPTS a step and never what
counts as passing: `verify` is the same `apply_step_output` + `validate_project`
closure either way. A router that could turn a failing step into a pass would defeat
the oracle, which is the one thing in this system that is allowed to say "correct".

No model, no network and no Ollama: the generators here are deterministic fakes, so
these run in milliseconds.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from hive.router_bridge import (  # noqa: E402
    build_entries,
    env_k,
    load_ladder,
    route_decision,
    route_enabled,
    routed_build,
    tier_and_cost,
)

GOOD = "def f():\n    return 5\n"
BAD = "def f():\n    return 4\n"


def _flat(text: str) -> str:
    """Collapse whitespace runs so a source grep survives the formatter.

    These guards match exact source text. `ruff format` changed the exact whitespace they
    keyed on -- three spaces before a comment became two, two after a comma became one, a
    one-line argument pair got split across two -- and every one of them went silently
    vacuous, reporting "found in no files", which is also what they print when the thing they
    guard has been DELETED. A guard whose blind mode is indistinguishable from the condition
    it guards against is not guarding.

    Comparing flattened text keeps the check identical -- same tokens, same order -- while
    dropping a dependency on spacing that a formatter is entitled to change at any time.
    """
    return re.sub(r"\s+", " ", text)


def _oracle():
    """A verifier that accepts exactly one answer, and records every attempt."""
    seen: list[str] = []

    def apply_and_validate(code: str) -> tuple[bool, str]:
        seen.append(code)
        return (code == GOOD), ("ok" if code == GOOD else "assert 4 == 5")

    return apply_and_validate, seen


def _model(answer: str):
    """A model that always returns `answer`, ignoring prompt and temperature."""
    return lambda _prompt, _temp: answer


# ── tier and cost are DERIVED, not invented ──────────────────────────────────


@pytest.mark.parametrize(
    "model,tier",
    [
        ("determinex/engineer", 1),  # local Ollama, DSL fine-tuned
        ("local/coder", 1),  # local Ollama, base
        ("free/qwen3-coder", 2),  # free endpoint: no spend, real latency
        ("cloud/deepseek-chat", 3),  # paid
    ],
)
def test_tier_follows_the_config_naming_convention(model, tier):
    assert tier_and_cost(model)[0] == tier


def test_local_and_free_tiers_cost_nothing_and_paid_tiers_do_not():
    assert tier_and_cost("determinex/engineer")[1] == 0.0
    assert tier_and_cost("free/qwen3-coder")[1] == 0.0
    assert tier_and_cost("cloud/deepseek-chat")[1] > 0.0


def test_an_unrecognised_model_is_assumed_PAID_not_free():
    """Defaulting an unknown model to cost 0 is how a router quietly picks the
    most expensive option while believing it chose the cheapest."""
    tier, cost = tier_and_cost("some-new-vendor/whatever")
    assert cost > 0.0
    assert tier >= 3


def test_determinex_prefix_is_not_shadowed_by_a_shorter_match():
    """`determinex/` and `local/` are both tier 1, but the table is order-sensitive
    and a regression here would silently reprice the default builder."""
    assert tier_and_cost("determinex/engineer") == tier_and_cost("local/coder")


# ── the ladder is explicit, never guessed ────────────────────────────────────


def test_env_ladder_wins_and_is_parsed_in_order(monkeypatch):
    monkeypatch.setenv("DETERMINEX_ROUTE_LADDER", " determinex/engineer , cloud/claude-best ")
    assert load_ladder() == ["determinex/engineer", "cloud/claude-best"]


def test_ladder_comes_from_config_when_env_is_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("DETERMINEX_ROUTE_LADDER", raising=False)
    cfg = tmp_path / "litellm_config.yaml"
    cfg.write_text(
        "determinex:\n  builder_ladder:\n    - determinex/engineer\n    - cloud/deepseek-chat\n",
        encoding="utf-8",
    )
    assert load_ladder(cfg) == ["determinex/engineer", "cloud/deepseek-chat"]


def test_a_missing_config_yields_no_ladder_rather_than_a_guess(monkeypatch, tmp_path):
    """Inventing a ladder from whatever models happen to be assigned to other roles
    would be a routing decision nobody asked for -- the architect model is not
    necessarily a better BUILDER."""
    monkeypatch.delenv("DETERMINEX_ROUTE_LADDER", raising=False)
    assert load_ladder(tmp_path / "absent.yaml") == []


class TestTheRoutingDefaultIsDerivedNotAssumed:
    """`DETERMINEX_ROUTE` unset used to mean "off", full stop.

    That made routing a feature nobody turned on. The default is now derived from what the
    machine can do FOR FREE, and both halves of that are real constraints rather than caution:

      FREE   the shipped ladder is all-local, but a user who uncomments the `cloud/deepseek-chat`
             rung would otherwise start escalating to a PAID model without ever enabling routing.
      FITS   the ladder is a 1.5B kept resident plus a 7B, ~6.3 GB live, so on a 6 GB card Ollama
             offloads to CPU and prefill hits the 400-500 s that already causes builder timeouts.
             Escalation that reliably times out is worse than none.

    This test replaces `test_routing_is_off_by_default`, which asserted the old rule and would
    have become machine-dependent -- passing on the 6 GB dev box and failing on any tier-1 host.
    Every case here pins the tier explicitly for that reason.
    """

    @staticmethod
    def _tier(monkeypatch, tier: int, label: str = "stub"):
        import hive.hardware as H

        class _P:
            def __init__(self) -> None:
                self.tier, self.tier_label = tier, label

        monkeypatch.setattr(H, "get_hw_profile", lambda: _P())

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("ON", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
        ],
    )
    def test_an_explicit_setting_wins_in_both_directions(self, monkeypatch, value, expected):
        """It only ever forced ON before; `DETERMINEX_ROUTE=0` was indistinguishable from unset,
        so there was no way to say "not on this run" once a default existed."""
        # Tier chosen to contradict the env var, so only the env var can produce the result.
        self._tier(monkeypatch, 2 if not expected else -1)
        monkeypatch.setenv("DETERMINEX_ROUTE", value)
        assert route_enabled() is expected

    def test_an_unrecognised_value_is_off_and_says_so(self, monkeypatch):
        self._tier(monkeypatch, 2)
        monkeypatch.setenv("DETERMINEX_ROUTE", "maybe")
        on, why = route_decision()
        assert on is False
        assert "not a recognised boolean" in why

    @pytest.mark.parametrize("tier,expected", [(-1, False), (0, False), (1, True), (2, True)])
    def test_the_default_follows_whether_both_rungs_fit(self, monkeypatch, tier, expected):
        monkeypatch.delenv("DETERMINEX_ROUTE", raising=False)
        monkeypatch.setenv("DETERMINEX_ROUTE_LADDER", "determinex/engineer,determinex/qwen7b")
        self._tier(monkeypatch, tier)
        assert route_enabled() is expected

    def test_a_paid_rung_blocks_the_default_even_on_the_biggest_rig(self, monkeypatch):
        """Memory is not the objection here -- money is. Tier 2 isolates that."""
        monkeypatch.delenv("DETERMINEX_ROUTE", raising=False)
        monkeypatch.setenv("DETERMINEX_ROUTE_LADDER", "determinex/engineer,cloud/deepseek-chat")
        self._tier(monkeypatch, 2)
        on, why = route_decision()
        assert on is False
        assert "cloud/deepseek-chat" in why
        assert "DETERMINEX_ROUTE=1" in why, "the reason must say how to opt in"

    def test_a_paid_rung_still_routes_when_explicitly_asked_for(self, monkeypatch):
        """The guard is about consent, not prohibition."""
        monkeypatch.setenv("DETERMINEX_ROUTE_LADDER", "determinex/engineer,cloud/deepseek-chat")
        monkeypatch.setenv("DETERMINEX_ROUTE", "1")
        self._tier(monkeypatch, 2)
        assert route_enabled() is True

    def test_a_one_rung_ladder_is_off_by_default(self, monkeypatch):
        monkeypatch.delenv("DETERMINEX_ROUTE", raising=False)
        monkeypatch.setenv("DETERMINEX_ROUTE_LADDER", "determinex/engineer")
        self._tier(monkeypatch, 2)
        on, why = route_decision()
        assert on is False
        assert "nothing to escalate to" in why

    def test_the_shipped_ladder_is_all_local_so_the_default_can_never_spend(self):
        """If someone adds a paid rung to litellm_config.yaml this fails, which is the point.

        The default-on path is only defensible while the shipped ladder is free.
        """
        from hive.budget import is_local_model

        ladder = load_ladder()
        assert len(ladder) >= 2, f"the shipped ladder should be routable: {ladder}"
        paid = [m for m in ladder if not is_local_model(m)]
        assert not paid, (
            f"the shipped builder_ladder now contains paid rung(s) {paid}. Either revert that or "
            "change route_decision -- a default-on router must not be able to spend money."
        )

    def test_an_unreadable_tier_fails_toward_off(self, monkeypatch):
        """Failing toward ON would thrash VRAM or spend money on the strength of a probe error."""
        import hive.hardware as H

        monkeypatch.delenv("DETERMINEX_ROUTE", raising=False)
        monkeypatch.setenv("DETERMINEX_ROUTE_LADDER", "determinex/engineer,determinex/qwen7b")

        def boom():
            raise OSError("no driver")

        monkeypatch.setattr(H, "get_hw_profile", boom)
        on, why = route_decision()
        assert on is False
        assert "could not be read" in why

    def test_the_decision_always_carries_a_reason(self, monkeypatch):
        """The executor logs this every session; an empty reason makes the log useless."""
        for tier in (-1, 0, 1, 2):
            monkeypatch.delenv("DETERMINEX_ROUTE", raising=False)
            self._tier(monkeypatch, tier)
            _on, why = route_decision()
            assert why and why.strip(), f"tier {tier} produced no reason"


def test_k_falls_back_to_the_default_on_a_junk_value(monkeypatch):
    monkeypatch.setenv("DETERMINEX_ROUTE_K", "not-a-number")
    assert env_k(6) == 6
    monkeypatch.setenv("DETERMINEX_ROUTE_K", "3")
    assert env_k(6) == 3


# ── escalation behaviour ─────────────────────────────────────────────────────


def test_a_ladder_shorter_than_two_is_a_no_op_and_says_so():
    """Returned as None rather than silently doing nothing, so the executor can log
    why and fall through to its normal single-model path. One model cannot escalate;
    that case is the amplifier's job."""
    verify, _ = _oracle()
    assert routed_build(lambda _m: _model(GOOD), verify, []) is None
    assert routed_build(lambda _m: _model(GOOD), verify, ["determinex/engineer"]) is None


def test_the_cheap_tier_solving_it_never_reaches_the_expensive_one():
    """The whole point: a step the local model can clear must cost nothing."""
    verify, _ = _oracle()
    asked: list[str] = []

    def gen_for(model: str):
        asked.append(model)
        return _model(GOOD if model.startswith("determinex/") else BAD)

    res = routed_build(gen_for, verify, ["determinex/engineer", "cloud/claude-best"], k=2, rounds=1)
    assert res is not None and res.passed
    assert res.model_used == "determinex/engineer"
    assert res.tier_used == 1
    assert res.escalations == 0
    assert res.est_cost == 0.0, "a local-only solve must not accrue cost"


def test_escalates_to_the_expensive_tier_when_the_cheap_one_cannot():
    verify, _ = _oracle()

    def gen_for(model: str):
        return _model(GOOD if model.startswith("cloud/") else BAD)

    res = routed_build(gen_for, verify, ["determinex/engineer", "cloud/claude-best"], k=2, rounds=1)
    assert res is not None and res.passed
    assert res.model_used == "cloud/claude-best"
    assert res.escalations >= 1
    assert res.est_cost > 0.0, "a solve that used a paid tier must record cost"


def test_an_exhausted_ladder_reports_failure_not_the_last_guess():
    """The failure mode that would matter most: dressing up a model's best attempt
    as a pass. `passed` must stay False when the oracle never accepted anything."""
    verify, seen = _oracle()

    res = routed_build(
        lambda _m: _model(BAD), verify, ["determinex/engineer", "cloud/claude-best"], k=2, rounds=1
    )
    assert res is not None
    assert res.passed is False
    assert seen, "the oracle should have been consulted"
    assert all(c == BAD for c in seen)


def test_the_winning_code_is_re_applied_so_the_workspace_ends_passing():
    """Later ladder entries overwrite the same target file, so the winner has to be
    re-applied or the workspace is left holding a losing candidate."""
    verify, seen = _oracle()

    def gen_for(model: str):
        return _model(GOOD if model.startswith("cloud/") else BAD)

    res = routed_build(gen_for, verify, ["determinex/engineer", "cloud/claude-best"], k=2, rounds=1)
    assert res is not None and res.passed
    assert seen[-1] == GOOD, "the last thing applied must be the passing candidate"


def test_routing_cannot_turn_a_failing_step_into_a_pass():
    """`verify` is the Compiler Oracle. Routing decides who attempts a step, never
    what counts as correct -- if it could, the oracle would no longer be the only
    thing in the system allowed to say 'correct'."""

    def reject_everything(code: str) -> tuple[bool, str]:
        return False, "compile error"

    res = routed_build(
        lambda _m: _model(GOOD),
        reject_everything,
        ["determinex/engineer", "cloud/claude-best"],
        k=3,
        rounds=1,
    )
    assert res is not None and res.passed is False


def test_entries_are_ordered_cheapest_first_regardless_of_ladder_order():
    """A ladder written expensive-first must not spend the expensive model first;
    ModelRouter sorts by (tier, cost) and this pins that we rely on it."""
    entries = build_entries(lambda _m: _model(GOOD), ["cloud/claude-best", "determinex/engineer"])
    from determinex_router import ModelRouter

    ordered = ModelRouter(entries, k=1, rounds=1).models
    assert [m.name for m in ordered] == ["determinex/engineer", "cloud/claude-best"]


# ── provenance: a logged-only result cannot be measured afterwards ────────────


def _result(**kw):
    from hive.router_bridge import RoutedBuildResult

    base = dict(
        passed=True,
        code=GOOD,
        output="ok",
        model_used="cloud/claude-best",
        tier_used=3,
        escalations=1,
        est_cost=2.5,
        samples=7,
    )
    base.update(kw)
    return RoutedBuildResult(**base)


def test_provenance_dict_carries_what_a_cost_comparison_needs():
    from hive.router_bridge import provenance_dict

    d = provenance_dict(_result())
    assert d == {
        "model": "cloud/claude-best",
        "tier": 3,
        "escalations": 1,
        "samples": 7,
        "est_cost": 2.5,
        "passed": True,
    }


def test_route_decision_is_appended_beside_the_spend_ledger(monkeypatch, tmp_path):
    """It lands next to logs/api_ledger/providers.jsonl on purpose: the cost join is
    then a single read rather than a correlation across two trees."""
    import json

    import hive.router_bridge as rb

    monkeypatch.setattr(rb, "_ROOT", tmp_path)
    rb.record_route_decision("sess-1", 3, _result())

    path = tmp_path / "logs" / "api_ledger" / "route_decisions.jsonl"
    assert path.is_file(), "route decision was not recorded"
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["session_id"] == "sess-1" and row["step_id"] == 3
    assert row["model_used"] == "cloud/claude-best" and row["tier_used"] == 3
    assert row["est_cost"] == 2.5 and row["passed"] is True
    assert row["ts"]


def test_recording_never_raises_even_on_an_unwritable_root(monkeypatch, tmp_path):
    """Same discipline as determinex_providers._ledger_append: accounting must not be
    able to break a build. A file where the directory should be makes mkdir fail."""
    import hive.router_bridge as rb

    blocker = tmp_path / "logs"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(rb, "_ROOT", tmp_path)
    rb.record_route_decision("sess-2", 1, _result())  # must not raise


def test_step_record_round_trips_route_provenance():
    """The step record is where a cost belongs -- it answers 'what produced THIS
    step'. Safe to add because load_manifest's G23 migration defaults missing keys."""
    from dataclasses import asdict

    from hive.manifest import StepRecord
    from hive.router_bridge import provenance_dict

    step = StepRecord(id=1, instruction="x")
    assert step.route_provenance is None, "routing off must leave this unset"

    step.route_provenance = provenance_dict(_result())
    revived = StepRecord(**asdict(step))
    assert revived.route_provenance["model"] == "cloud/claude-best"
    assert revived.route_provenance["tier"] == 3


def test_an_old_step_record_without_the_field_still_loads():
    """G23 in action: a session written before this field existed must load cleanly
    rather than crash on a missing key."""
    from hive.manifest import StepRecord

    legacy = {"id": 2, "instruction": "y", "status": "complete"}
    known = {k: v for k, v in legacy.items() if k in StepRecord.__dataclass_fields__}
    assert StepRecord(**known).route_provenance is None


# ── role override: needed so an A/B arm can pin a builder without editing config ──


def test_role_override_pins_one_role_and_leaves_the_others(monkeypatch):
    """The A/B has to run the same specs with the builder pinned (always-frontier
    arm) and then with a ladder (routed arm). Rewriting litellm_config.yaml between
    arms would mutate shared state mid-experiment and leave the repo dirty if a run
    died partway."""
    from hive.api_client import _apply_role_overrides

    base = {"oracle": "a", "architect": "b", "builder": "c", "monitor": "d"}
    monkeypatch.setenv("DETERMINEX_ROLE_BUILDER", "determinex/qwen7b")
    out = _apply_role_overrides(base)
    assert out["builder"] == "determinex/qwen7b"
    assert (out["oracle"], out["architect"], out["monitor"]) == ("a", "b", "d")


def test_role_override_ignores_an_unknown_role(monkeypatch):
    """Only the four known roles are honoured, so a typo cannot silently invent one
    that nothing reads."""
    from hive.api_client import _apply_role_overrides

    monkeypatch.setenv("DETERMINEX_ROLE_BILDER", "typo/model")
    out = _apply_role_overrides({"builder": "c"})
    assert out == {"builder": "c"}


def test_an_empty_role_override_is_not_applied(monkeypatch):
    """An exported-but-empty variable must not blank out a configured role -- the
    same present-but-empty trap that broke local-ollama's --model flag."""
    from hive.api_client import _apply_role_overrides

    monkeypatch.setenv("DETERMINEX_ROLE_BUILDER", "   ")
    assert _apply_role_overrides({"builder": "c"})["builder"] == "c"


# ── repo-root resolution: the bug that sent sessions into another checkout ────


def test_no_env_var_uses_the_derived_root(monkeypatch):
    from hive.manifest import resolve_repo_root

    monkeypatch.delenv("DETERMINEX_ROOT", raising=False)
    assert resolve_repo_root() == REPO_ROOT


def test_a_valid_env_root_is_honoured(monkeypatch, tmp_path):
    """The sidecar's whole purpose: its __file__ is a temp extraction dir, so the
    caller must be able to name the real root."""
    from hive.manifest import resolve_repo_root

    (tmp_path / "litellm_config.yaml").write_text("determinex: {}\n", encoding="utf-8")
    monkeypatch.setenv("DETERMINEX_ROOT", str(tmp_path))
    assert resolve_repo_root() == tmp_path.resolve()


def test_a_wrong_env_root_is_ignored_when_the_derived_one_is_real(monkeypatch, tmp_path, capsys):
    r"""The live bug: DETERMINEX_ROOT=C:\Dev\Citadel -- a directory that EXISTS but is
    the pre-rename checkout with no config. Sessions went there for two days. An
    existence check could never have caught it."""
    from hive.manifest import resolve_repo_root

    wrong = tmp_path / "other-checkout"
    wrong.mkdir()
    monkeypatch.setenv("DETERMINEX_ROOT", str(wrong))

    assert resolve_repo_root() == REPO_ROOT
    err = capsys.readouterr().err
    assert "not a Determinex checkout" in err and "litellm_config.yaml" in err


def test_when_neither_looks_like_a_checkout_the_env_var_still_wins(monkeypatch, tmp_path):
    """Do NOT fall back in this case. Under PyInstaller the derived path is a temp
    extraction dir, so preferring it over the caller's explicit value would be
    strictly worse than trusting them."""
    import hive.manifest as mf

    wrong = tmp_path / "neither"
    wrong.mkdir()
    monkeypatch.setenv("DETERMINEX_ROOT", str(wrong))
    monkeypatch.setattr(mf, "_looks_like_repo", lambda _p: False)
    assert mf.resolve_repo_root() == wrong.resolve()


def test_api_client_and_manifest_resolve_the_same_root():
    """One resolver, not two. Two copies of the same fact is how the argv builders
    and the audit docs drifted apart earlier in this campaign."""
    import hive.api_client as ac
    import hive.manifest as mf

    assert ac._ROOT == mf._ROOT


# ── telemetry: latency and per-call tokens, which nothing recorded before ─────


_CALLS = [
    {
        "model": "determinex/engineer",
        "temp": 0.1,
        "ms": 41200,
        "tokens_in": 1800,
        "tokens_out": 320,
    },
    {
        "model": "determinex/engineer",
        "temp": 0.3,
        "ms": 38900,
        "tokens_in": 1800,
        "tokens_out": 290,
    },
    {"model": "cloud/deepseek-chat", "temp": 0.1, "ms": 6100, "tokens_in": 1850, "tokens_out": 410},
]


def test_telemetry_totals_per_model():
    from hive.router_bridge import summarise_calls

    t = summarise_calls(_CALLS)
    assert t["calls"] == 3
    assert t["ms_total"] == 86200
    eng = t["by_model"]["determinex/engineer"]
    assert (eng["calls"], eng["ms"], eng["tokens_in"], eng["tokens_out"]) == (2, 80100, 3600, 610)
    assert t["by_model"]["cloud/deepseek-chat"]["calls"] == 1


def test_telemetry_makes_the_latency_cost_of_escalation_visible():
    """The point of recording ms at all. Routing cost 27% and 31% more wall clock than
    always-frontier in the A/B, and nothing anywhere could attribute that: the usage
    ledger records tokens and dollars, never milliseconds. Here the cheap rung burns
    80s over two failed attempts so the paid rung can spend 6s -- which is the tradeoff
    routing actually makes, and it was previously invisible."""
    from hive.router_bridge import summarise_calls

    by = summarise_calls(_CALLS)["by_model"]
    assert by["determinex/engineer"]["ms"] > by["cloud/deepseek-chat"]["ms"] * 10


def test_telemetry_handles_no_calls_and_missing_fields():
    from hive.router_bridge import summarise_calls

    assert summarise_calls(None) == {"calls": 0, "ms_total": 0, "by_model": {}}
    assert summarise_calls([])["calls"] == 0
    # a row missing ms/tokens must not raise -- telemetry is never allowed to break a build
    t = summarise_calls([{"model": "x"}])
    assert t["calls"] == 1 and t["ms_total"] == 0


def test_provenance_and_recording_still_work_without_telemetry(tmp_path, monkeypatch):
    """Both signatures gained an optional `calls` argument. Callers that do not pass it
    must behave exactly as before, or the amplifier path breaks."""
    import hive.router_bridge as rb

    d = rb.provenance_dict(_result())
    assert "telemetry" not in d, "absent telemetry must not add an empty key"

    monkeypatch.setattr(rb, "_ROOT", tmp_path)
    rb.record_route_decision("s", 1, _result())  # no calls arg
    rb.record_route_decision("s", 2, _result(), _CALLS)  # with calls
    rows = (
        (tmp_path / "logs" / "api_ledger" / "route_decisions.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    import json as _json

    assert _json.loads(rows[0])["telemetry"]["calls"] == 0
    assert _json.loads(rows[1])["telemetry"]["by_model"]["cloud/deepseek-chat"]["ms"] == 6100


def test_provenance_carries_telemetry_when_given():
    from hive.router_bridge import provenance_dict

    d = provenance_dict(_result(), _CALLS)
    assert d["telemetry"]["ms_total"] == 86200
    assert d["model"] == "cloud/claude-best", "the existing fields must survive"


# ── sidecar helper dispatch: why the packaged app could not run the panels ─────


def test_helper_allowlist_covers_every_script_the_rust_backend_calls():
    """The desktop backend shells to a fixed set of scripts. Each must be dispatchable
    from the bundled engine, or that panel is dev-checkout-only in an installed copy --
    which is exactly what it was: hive_command had been bundled-first for a while, and
    every other script went through a repo-path helper that does not exist in a build.
    """
    import re

    from determinex_hive import _HELPER_MODULES

    rust = REPO_ROOT / "frontend" / "src-tauri" / "src"
    declared: set[str] = set()
    for f in rust.glob("*.rs"):
        for m in re.finditer(
            r'SCRIPT[A-Z_]*: &str = "(scripts/[^"]+\.py)"', f.read_text(encoding="utf-8")
        ):
            declared.add(m.group(1))
        for m in re.finditer(
            r'PYTHON_DRIVER: &str = "(scripts/[^"]+\.py)"', f.read_text(encoding="utf-8")
        ):
            declared.add(m.group(1))

    assert declared, "found no script constants in the Rust backend -- did they move?"

    def module_of(path: str) -> str:
        return path.removeprefix("scripts/").removesuffix(".py").replace("/", ".")

    missing = sorted(module_of(p) for p in declared if module_of(p) not in _HELPER_MODULES)
    assert not missing, (
        "these scripts are invoked by the Rust backend but are NOT dispatchable from the "
        f"bundled engine, so they only work in a dev checkout: {missing}. Add them to "
        "determinex_hive._HELPER_MODULES and to the bundler's --hidden-import list."
    )


def test_every_allowlisted_helper_is_a_bundler_hidden_import():
    """cmd_helper reaches these via importlib, which PyInstaller cannot trace. Without a
    matching --hidden-import the sidecar exposes `helper <name>` and then fails at import
    -- and the backend silently falls back to a repo script that is not there."""
    from determinex_hive import _HELPER_MODULES

    bundler = (REPO_ROOT / "bundler" / "build_hive_sidecar.py").read_text(encoding="utf-8")
    flat = _flat(bundler)
    missing = [m for m in _HELPER_MODULES if _flat(f'"--hidden-import", "{m}"') not in flat]
    assert not missing, f"allowlisted but not bundled: {missing}"


def test_helper_rejects_anything_not_allowlisted():
    """This dispatches into arbitrary module main()s, so the allowlist is the security
    boundary -- `helper os` must never resolve."""
    import subprocess

    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "determinex_hive.py"), "helper", "os"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode != 0
    assert "invalid choice" in (r.stderr + r.stdout)
