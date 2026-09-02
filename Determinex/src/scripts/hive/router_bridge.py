"""
hive/router_bridge.py -- wires the Model-Agnostic Router into the hive build loop
================================================================================
`amplifier_bridge` samples ONE model K times against the Compiler Oracle. This
bridge does the other half: it walks a LADDER of models, cheapest first, and only
escalates to a more expensive one when verified search on the cheap tier exhausts
without a pass. A step a 1.5B local model can clear costs nothing; a step it cannot
escalates with its error trace intact.

Correctness does not depend on the routing. `verify` is the same Compiler Oracle
either way -- routing only decides who gets to try, never whether the answer is
accepted. A ladder that exhausts returns `solved=False` rather than the last
model's best guess dressed up as a pass.

    generate_for_model(model: str) -> (prompt, temp) -> str   # the real Builder, per model
    apply_and_validate(code: str) -> (bool, str)              # apply_step_output + validate_project

    result = routed_build(generate_for_model, apply_and_validate, load_ladder())
    if result.passed:
        code = result.code            # oracle already PASSED on this

`DETERMINEX_ROUTE` controls it and wins in both directions. Unset, the default is derived
from what the machine can do FOR FREE: on only when the ladder is entirely local (so routing
never starts spending money nobody authorised) and the hardware tier can hold both rungs
without offloading to CPU. See `route_decision` for why each of those is a real constraint
rather than caution. Every session logs which way it went and why.

WHERE TIER AND COST COME FROM
-----------------------------
Both are DERIVED, not invented. `litellm_config.yaml` already encodes the tiers in
its own naming convention -- `local/*` and `determinex/*` are local Ollama, `free/*`
are free OpenRouter endpoints, `cloud/*` are paid -- and real per-million-token
prices already live in `determinex_providers._LEDGER_PRICING`, which is what the
usage ledger bills against. Making up a second set of relative "cost" numbers would
have meant two sources of truth for the same fact.

Note the cost this module reports is an ESTIMATE for routing decisions. Actual spend
is recorded independently: every cloud call through the litellm lane already appends
real token counts and est_usd to logs/api_ledger/providers.jsonl, so a route-on vs
route-off comparison is measured from the ledger, not from this number.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPTS = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
from determinex_adjudicator import Failure  # noqa: E402
from determinex_router import ModelEntry, ModelRouter  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent.parent

GenerateFn = Callable[[str, float], str]
GenerateForModel = Callable[[str], GenerateFn]
ApplyValidate = Callable[[str], "tuple[bool, str]"]

# Prefix -> (tier, is_paid). The convention is litellm_config.yaml's own; see the
# module docstring. Longest prefix wins so `determinex/` is not shadowed by a
# shorter match.
_TIER_BY_PREFIX: tuple[tuple[str, int, bool], ...] = (
    ("determinex/", 1, False),  # local Ollama, DSL fine-tuned
    # The SAME models under their bare Ollama tag, which is how hive/ctx_config.py
    # actually assigns the roles by default: `determinex-engineer-v11-dsl`. Without this
    # row those three names missed every prefix and fell to _UNKNOWN_TIER, so the router
    # rated the free local default builder as its most expensive tier-3 option -- exactly
    # inverting the ladder it exists to climb, and inflating the cost figures the A/B
    # measures. Same root cause as the budget mispricing fixed in hive/budget.py: a bare
    # tag has no slash, so every prefix test silently misses it.
    ("determinex-", 1, False),
    ("local/", 1, False),  # local Ollama, base models
    ("free/", 2, False),  # free OpenRouter endpoints: no spend, real latency
    ("cloud/", 3, True),  # paid APIs
)
_UNKNOWN_TIER = 3  # an unrecognised name is assumed paid, never free


@dataclass
class RoutedBuildResult:
    passed: bool
    code: str
    output: str  # last compiler output (proof on pass, diagnosis on miss)
    model_used: str
    tier_used: int
    escalations: int
    est_cost: float
    samples: int
    next_moves: list[str] = field(default_factory=list)


class _OracleResult:
    """Duck-typed for VerifiedSearch (.passed, .failures) -- same shape the
    amplifier bridge uses, for the same reason: neither module should import the
    oracle's internals."""

    __slots__ = ("passed", "failures", "output")

    def __init__(self, passed: bool, output: str):
        self.passed = passed
        self.output = output
        self.failures = (
            [] if passed else [Failure(test_id="compile", name="compile", text=output[:1500])]
        )


def tier_and_cost(model: str) -> tuple[int, float]:
    """Derive (tier, relative cost per sample) for a configured model name."""
    name = (model or "").strip().lower()
    for prefix, tier, is_paid in _TIER_BY_PREFIX:
        if name.startswith(prefix):
            return tier, (_price_of(name) if is_paid else 0.0)
    return _UNKNOWN_TIER, _price_of(name)


def _price_of(model: str) -> float:
    """Per-million-token input price from the ledger's own table, as the routing
    cost signal. Falls back to the table's default rather than 0.0 -- treating an
    unpriced model as free is how a router quietly picks the expensive option."""
    try:
        from determinex_providers import _LEDGER_PRICING, _LEDGER_PRICING_DEFAULT

        pin, _pout = _LEDGER_PRICING.get(model, _LEDGER_PRICING_DEFAULT)
        return float(pin)
    except Exception:
        return 1.0


def load_ladder(config_path: Path | None = None) -> list[str]:
    """The escalation ladder, cheapest first.

    Order of precedence, all explicit -- this never guesses a ladder:
      1. DETERMINEX_ROUTE_LADDER (comma-separated model names)
      2. determinex.builder_ladder in litellm_config.yaml
      3. [] -- routing is a no-op and says so, rather than inventing a ladder out
         of whatever models happen to be configured for other roles. The architect
         model is not necessarily a better BUILDER, and silently promoting it would
         be a routing decision nobody asked for.
    """
    env = os.environ.get("DETERMINEX_ROUTE_LADDER", "").strip()
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]

    path = config_path or (_ROOT / "litellm_config.yaml")
    if not path.is_file():
        return []
    try:
        import yaml

        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ladder = (cfg.get("determinex") or {}).get("builder_ladder") or []
        return [str(m).strip() for m in ladder if str(m).strip()]
    except Exception:
        return []


def build_entries(generate_for_model: GenerateForModel, ladder: list[str]) -> list[ModelEntry]:
    """Turn configured model names into router entries, tier/cost derived."""
    entries: list[ModelEntry] = []
    for model in ladder:
        tier, cost = tier_and_cost(model)
        entries.append(
            ModelEntry(
                name=model,
                tier=tier,
                cost=cost,
                generate=generate_for_model(model),
                capability_hint=model,
            )
        )
    return entries


def routed_build(
    generate_for_model: GenerateForModel,
    apply_and_validate: ApplyValidate,
    ladder: list[str] | None = None,
    k: int | None = None,
    rounds: int = 2,
) -> RoutedBuildResult | None:
    """Route one build step up the ladder. Returns None when routing is not
    usable (no ladder configured), so the caller can fall through to its normal
    single-model path instead of silently doing nothing."""
    ladder = ladder if ladder is not None else load_ladder()
    if len(ladder) < 2:
        # A one-model "ladder" cannot escalate; that is the amplifier's job, not
        # this one. Reported as None rather than run, so the log says why.
        return None

    k = k or env_k()
    last_output = ""

    def verify(code: str) -> _OracleResult:
        nonlocal last_output
        passed, output = apply_and_validate(code)
        last_output = output
        return _OracleResult(passed, output)

    router = ModelRouter(build_entries(generate_for_model, ladder), k=k, rounds=rounds)
    res = router.solve_leaf(verify=verify, prompt="", start_tier=1)

    search = res.search
    best = getattr(search, "best", None)
    samples = int(getattr(search, "total_samples", 0) or 0)
    if res.solved and best is not None:
        # Re-apply the winner so the workspace ends in the state the oracle passed.
        apply_and_validate(best.text)
        return RoutedBuildResult(
            True,
            best.text,
            last_output,
            res.model_used,
            res.tier_used,
            res.escalations,
            res.total_cost,
            samples,
        )
    return RoutedBuildResult(
        False,
        best.text if best else "",
        last_output,
        res.model_used,
        res.tier_used,
        res.escalations,
        res.total_cost,
        samples,
        list(getattr(search, "next_moves", []) or []),
    )


_TRUTHY = ("1", "true", "yes", "on")
_FALSEY = ("0", "false", "no", "off")


def route_decision() -> tuple[bool, str]:
    """(enabled, reason). `DETERMINEX_ROUTE` wins in BOTH directions when set.

    Unset, the default is derived from what this machine can actually do for free, because a
    feature nobody turns on may as well not exist -- and the two reasons it was left off are
    both checkable rather than assumed:

    IT MUST BE FREE. The shipped `builder_ladder` is all-local, but a user who uncomments the
    `cloud/deepseek-chat` rung would otherwise start escalating to a PAID model without ever
    having enabled routing. So a default-on ladder must be entirely local; one paid rung and
    routing waits to be asked for explicitly. `is_local_model` is the canonical locality
    decision and it resolves the `determinex/*` aliases, so this is not a prefix guess.

    IT MUST FIT IN MEMORY. The ladder is engineer (1.5B, ~1.6 GB, kept resident with
    keep_alive=-1) then a 7B (~4.7 GB). That is ~6.3 GB live on a card advertising 6 GB, so on
    tier 0 Ollama offloads layers to CPU and prefill goes to the 400-500 s that
    `api_client._ollama_extra` already documents as the cause of builder timeouts. Escalation
    that reliably times out is worse than no escalation, so tier 0 and below stay off.

    Anything unreadable fails toward OFF -- the previous behaviour -- rather than toward
    spending money or thrashing VRAM.
    """
    explicit = os.environ.get("DETERMINEX_ROUTE", "").strip().lower()
    if explicit in _TRUTHY:
        return True, "DETERMINEX_ROUTE set explicitly"
    if explicit in _FALSEY:
        return False, "DETERMINEX_ROUTE disabled explicitly"
    if explicit:
        return False, f"DETERMINEX_ROUTE={explicit!r} is not a recognised boolean; treating as off"

    try:
        ladder = load_ladder()
    except Exception as exc:
        return False, f"ladder could not be read ({type(exc).__name__})"
    if len(ladder) < 2:
        return False, "no 2+ model ladder configured, so there is nothing to escalate to"

    try:
        from hive.budget import is_local_model

        paid = [m for m in ladder if not is_local_model(m)]
    except Exception as exc:
        return False, f"ladder locality could not be determined ({type(exc).__name__})"
    if paid:
        return False, (
            f"ladder contains paid rung(s) {', '.join(paid)}; "
            "set DETERMINEX_ROUTE=1 to opt in to spending"
        )

    try:
        from hive.hardware import get_hw_profile

        hw = get_hw_profile()
    except Exception as exc:
        return False, f"hardware tier could not be read ({type(exc).__name__})"
    if hw.tier < 1:
        return False, (
            f"tier {hw.tier} ({hw.tier_label}) cannot hold both rungs without "
            "offloading to CPU, which times the builder out"
        )

    return True, (
        f"all-local ladder ({' -> '.join(ladder)}) on tier {hw.tier} "
        f"({hw.tier_label}) -- free and it fits"
    )


def route_enabled() -> bool:
    return route_decision()[0]


def env_k(default: int = 6) -> int:
    try:
        return max(1, int(os.environ.get("DETERMINEX_ROUTE_K", default)))
    except ValueError:
        return default


def record_route_decision(
    session_id: str, step_id: int, result: RoutedBuildResult, calls: list[dict] | None = None
) -> None:
    """Append one route decision to the ledger directory. NEVER raises.

    A side channel next to the spend rows rather than the only record: the same
    provenance also lands on the StepRecord (manifest.route_provenance). Two homes
    on purpose --

      * the step record answers "what produced THIS step's code", which is where a
        reader looking at a session expects it;
      * this file answers "what did routing do across many sessions", which is what a
        cost comparison needs, and it sits beside logs/api_ledger/providers.jsonl so
        the join against real est_usd is a single read.

    Same never-raise discipline as determinex_providers._ledger_append: accounting
    must not be able to break a build.
    """
    try:
        import datetime as _dt
        import json as _json

        ledger_dir = _ROOT / "logs" / "api_ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        with open(ledger_dir / "route_decisions.jsonl", "a", encoding="utf-8") as f:
            f.write(
                _json.dumps(
                    {
                        "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
                        "session_id": session_id,
                        "step_id": step_id,
                        "passed": bool(result.passed),
                        "model_used": result.model_used,
                        "tier_used": result.tier_used,
                        "escalations": result.escalations,
                        "samples": result.samples,
                        "est_cost": round(float(result.est_cost), 6),
                        # per-call latency and tokens, so a later cost comparison can
                        # attribute spend to a RUNG instead of inferring it from a session total
                        "telemetry": summarise_calls(calls),
                    }
                )
                + "\n"
            )
    except Exception:
        pass


def summarise_calls(calls: list[dict] | None) -> dict:
    """Per-model latency and token totals for the generations a step made.

    Closes two gaps recorded as unprobed in the 2026-07-28 probe notes. LATENCY had no
    home anywhere -- the usage ledger records tokens and dollars, never milliseconds --
    while routing measurably cost 27% and 31% more wall clock than always-frontier. And
    PER-CALL TOKENS were never captured, only per-session totals, so cost could not be
    attributed to a rung: exactly why the paid A/B could not explain 2 paid calls (vs
    the baseline's 3) yielding 1.6% instead of the ~33% that predicts.
    """
    out: dict = {"calls": len(calls or []), "ms_total": 0, "by_model": {}}
    for c in calls or []:
        m = str(c.get("model", "?"))
        slot = out["by_model"].setdefault(m, {"calls": 0, "ms": 0, "tokens_in": 0, "tokens_out": 0})
        slot["calls"] += 1
        slot["ms"] += int(c.get("ms", 0) or 0)
        slot["tokens_in"] += int(c.get("tokens_in", 0) or 0)
        slot["tokens_out"] += int(c.get("tokens_out", 0) or 0)
        out["ms_total"] += int(c.get("ms", 0) or 0)
    return out


def provenance_dict(result: RoutedBuildResult, calls: list[dict] | None = None) -> dict:
    """The subset of a route result worth persisting on the step record."""
    d = {
        "model": result.model_used,
        "tier": result.tier_used,
        "escalations": result.escalations,
        "samples": result.samples,
        "est_cost": round(float(result.est_cost), 6),
        "passed": bool(result.passed),
    }
    if calls:
        d["telemetry"] = summarise_calls(calls)
    return d
