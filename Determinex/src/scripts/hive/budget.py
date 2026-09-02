"""
scripts/hive/budget.py — API cost tracking and training queue
==============================================================
Moved from determinex_hive.py (lines ~1460-1539).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from hive.compiler import classify_training_quality
from hive.manifest import ManifestSession, StepRecord, save_manifest

log = logging.getLogger("hive")

# scripts/budget_guard.py owns the canonical per-model $/1M-token PRICING
# table (kept current with real vendor pricing). Reuse it here rather than
# duplicating a second, drifting copy — this module previously used a single
# flat $8/1M blended rate for every call regardless of model, which silently
# undercounted premium models by up to ~9x (e.g. Claude Opus output at
# $75/1M) while also overcounting free local Ollama calls as costing real
# money. That gap meant a session could blow through real dollars while
# session.budget_exhausted still read comfortably under the cap.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
try:
    # Re-exported, not used directly here any more (price_per_1m owns the lookup):
    # tests/test_hive_budget.py reads budget._MODEL_PRICING to derive expected costs
    # from the real table rather than restating rates. Do not "clean up" as unused.
    from budget_guard import PRICING as _MODEL_PRICING  # noqa: E402,F401
    from budget_guard import is_local_model as _bg_is_local_model  # noqa: E402
    from budget_guard import price_per_1m as _bg_price_per_1m  # noqa: E402
except ImportError:  # pragma: no cover — budget_guard.py always ships alongside this file
    _MODEL_PRICING = {}

    def _bg_is_local_model(model: str) -> bool:
        """Degraded stand-in. Still recognises the bare `determinex-` tags, because
        getting those wrong is the bug this whole path exists to avoid."""
        return (
            (model or "")
            .strip()
            .lower()
            .startswith(
                (
                    "ollama/",
                    "ollama_chat/",
                    "hosted_vllm/",
                    "text-completion-openai/",
                    "determinex/",
                    "local/",
                    "determinex-",
                )
            )
        )

    def _bg_price_per_1m(model: str) -> tuple[float, float] | None:
        return None

    log.warning(
        "[budget] Could not import budget_guard.PRICING — falling back to flat-rate cost estimate for every call"
    )

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT = (
    Path(os.environ["DETERMINEX_ROOT"]).resolve()
    if os.environ.get("DETERMINEX_ROOT")
    else Path(__file__).resolve().parent.parent.parent
)
_RETRAIN_Q = _ROOT / "logs" / "retrain_queue.jsonl"
_HUMAN_Q = _ROOT / "logs" / "human_review_queue.jsonl"

# ── L12-B: SWE-bench decontamination ─────────────────────────────────────────
# SWE-bench tasks always reference their source repo as "owner__repo-NNNNN".
# If that pattern appears in either the instruction or the generated code,
# the example has leaked benchmark data and must not enter the training pool.
_SWEBENCH_FINGERPRINT_RE = re.compile(
    r"\b(?:django|scikit[_-]learn|matplotlib|sympy|pandas|xarray|astropy|"
    r"pylint|sphinx|requests|seaborn|flask|sqlalchemy|pyramid|twisted|"
    r"scrapy|celery|pytest|numpy|scipy|statsmodels|tornado|aiohttp|"
    r"psf|pydata|mwaskom|pallets)__[a-z][\w.-]*-\d+\b",
    re.IGNORECASE,
)

# ── L11-A: Synthetic rot spiral guard ────────────────────────────────────────
# Without human anchor data, each training run compounds the model's drift
# toward its own dialect.  We warn aggressively when the auto-queue grows
# without any human-reviewed examples.
_SYNTHETIC_ROT_WARN_EVERY = 100  # warn every N auto-ingested examples
_synthetic_rot_counter = 0  # module-level counter, reset on daemon restart
_synthetic_rot_lock = threading.Lock()

# G17: Serialises concurrent JSONL appends — open()+write() is not atomic.
_queue_write_lock = threading.Lock()

# ── API budget constants ──────────────────────────────────────────────────────
APPROX_TOKENS_PER_STEP = 1500
APPROX_COST_PER_1K_TOKENS = 0.008
BUDGET_WARN_FRACTION = 0.80

# Protects session.api_cost_usd / session.budget_exhausted when multiple steps
# execute concurrently inside run_session() (Tier 1+ wavefront execution).
_cost_lock = threading.Lock()


def estimate_session_cost(step_count: int) -> float:
    """Rough estimate of total API cost for a session given DAG step count."""
    total_tokens = step_count * APPROX_TOKENS_PER_STEP
    return (total_tokens / 1000) * APPROX_COST_PER_1K_TOKENS


# Fraction of an unsplit token count assumed to be completion (output) tokens
# when the caller only has a total_tokens figure, not a prompt/completion
# split. Coding-agent calls are output-heavy (the model writes code, DAGs,
# verdicts back), and output tokens are consistently priced higher than
# input across every vendor in PRICING — biasing this estimate toward
# completion is the conservative direction for a cost *guard* (better to
# overcount and warn early than undercount and blow through real spend).
_ASSUMED_COMPLETION_FRACTION = 0.7


def _price_per_1m(model: str) -> tuple[float, float] | None:
    """Look up (input, output) $/1M-token rate for a model string.

    Delegates to budget_guard.price_per_1m. This function used to hold its own copy of
    the substring match -- correct, but a copy, and the original in BudgetGuard stayed
    an exact-key `.get()` that silently priced prefixed cloud models at $0. Having the
    right answer in one module and the wrong one in another is how a spend cap ends up
    disabled while the tests are green. One lookup now.

    Local models are free and never need a rate; callers short-circuit via
    is_local_model first.
    """
    return _bg_price_per_1m(model)


# Prefixes that unambiguously name a locally-served model. Kept in sync with
# determinex_providers._is_local_litellm_model, which enforces the same distinction for
# the offline network policy -- the two must agree or a model is free to one and paid to
# the other.
_LOCAL_MODEL_PREFIXES = (
    "ollama/",
    "ollama_chat/",
    "hosted_vllm/",
    "text-completion-openai/",
    "determinex/",
    "local/",
)

# This project's own Ollama tags, which are BARE names with no provider prefix:
# `determinex-engineer-v11-dsl`, `determinex-observer-v6-dsl`, `determinex-sentinel-v5-dsl`.
# See hive/ctx_config.py, where those exact strings are the DEFAULT role assignments.
_LOCAL_MODEL_FAMILY_PREFIX = "determinex-"


def is_local_model(model: str) -> bool:
    """Is this model served locally, and therefore free?

    Delegates to budget_guard, which is the canonical leaf: BudgetGuard (the cloud
    spend cap), this pricer, and determinex_providers' usage ledger all decide cost
    from the same table and the same locality rule. They previously each had their own
    -- three implementations, three different wrong answers.

    THE BUG THIS FIXES (found 2026-07-29). The check used to be
    `model.startswith("ollama/") or model.startswith("determinex/")`. Both need a
    provider prefix, and hive/ctx_config.py assigns the roles BARE Ollama tags by
    default -- `determinex-engineer-v11-dsl` starts with "determinex-", not
    "determinex/". So every call to the project's own local models was priced at the
    $0.008/1K blended fallback: $0.012 per builder step, on a $2.00 default session
    budget. A fully local session accrued entirely fictional spend, showed it in the
    UI, and after enough steps tripped `budget_exhausted` and logged "API BUDGET
    EXHAUSTED - switching to local-only mode" while it had never left local.

    It is the same defect api_client._resolve_model already carries a comment about:
    "bare model names ... have no slash - but they ARE local Ollama models." That
    resolver only handles the ones present in litellm_config.yaml's alias map, and the
    bare tags are not in it (checked: 23 aliases, none of the three).

    WHAT THIS DELIBERATELY DOES NOT DO: guess from tag syntax. `name:tag` looks
    distinctively Ollama, but Bedrock ships `anthropic.claude-v2:1` -- colon, no
    slash. Treating that as local would price a real cloud call at $0 and hide
    genuine spend, which is far worse than the bug being fixed here. Unrecognised
    names keep the conservative blended fallback: over-reporting cost fails toward
    not spending money, under-reporting fails toward overspending.
    """
    return _bg_is_local_model(model)


def _estimate_cost_usd(
    model: str,
    tokens_used: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float:
    """Real per-model cost when the model is in PRICING; local models are always $0;
    anything else falls back to the old flat blended rate, logged so the gap stays
    visible rather than silently assumed accurate."""
    if is_local_model(model):
        return 0.0

    rate = _price_per_1m(model)
    if rate is None:
        if model:
            log.warning(
                "[budget] No pricing entry for model '%s' — using flat $%.3f/1K blended-rate "
                "estimate (add it to budget_guard.PRICING for an accurate figure)",
                model,
                APPROX_COST_PER_1K_TOKENS,
            )
        return (tokens_used / 1000) * APPROX_COST_PER_1K_TOKENS

    in_rate, out_rate = rate
    if prompt_tokens is None or completion_tokens is None:
        completion_tokens = round(tokens_used * _ASSUMED_COMPLETION_FRACTION)
        prompt_tokens = tokens_used - completion_tokens
    return (prompt_tokens / 1_000_000) * in_rate + (completion_tokens / 1_000_000) * out_rate


def record_api_call_cost(
    session: ManifestSession,
    tokens_used: int,
    model: str = "",
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> bool:
    """
    Record API call cost. Returns True if budget is still available, False if exhausted.
    Thread-safe: protected by _cost_lock for concurrent wavefront execution.

    model: the exact string passed to litellm.completion for this call.
    Omitting it (legacy callers) falls back to the old flat blended-rate
    estimate — pass it whenever the caller has it (every current call site
    does) so premium/local models are priced accurately instead of at one
    shared blended rate.
    """
    cost = _estimate_cost_usd(model, tokens_used, prompt_tokens, completion_tokens)
    with _cost_lock:
        session.api_cost_usd += cost
        fraction = (
            session.api_cost_usd / session.session_budget_usd if session.session_budget_usd else 0.0
        )
        if fraction >= 1.0:
            session.budget_exhausted = True
            log.warning(
                "API BUDGET EXHAUSTED ($%.2f / $%.2f) — switching to local-only mode",
                session.api_cost_usd,
                session.session_budget_usd,
            )
            return False
        if fraction >= BUDGET_WARN_FRACTION:
            log.warning(
                "API BUDGET WARNING: $%.2f of $%.2f used (%.0f%%)",
                session.api_cost_usd,
                session.session_budget_usd,
                fraction * 100,
            )
        return True


def api_budget_preflight(session: ManifestSession) -> tuple[bool, float, float]:
    """
    Estimate total session cost from DAG step count before Step 1 executes.
    Returns (budget_ok, estimated_cost, remaining_budget).
    """
    remaining = session.session_budget_usd - session.api_cost_usd
    step_count = len([s for s in session.steps if s.status in ("pending", "stale_instruction")])
    estimated = estimate_session_cost(step_count)
    budget_ok = estimated <= remaining
    return budget_ok, estimated, remaining


def queue_for_training(session: ManifestSession, step: StepRecord) -> None:
    """
    Append a completed or failed step to the training queue.
    quality: training_ready → automatic ingestion.
    quality: inconclusive   → human review queue, NOT automatic ingestion.

    Guards applied before queuing:
      L12-B: SWE-bench fingerprint denylist — routes to human review on match.
      L11-A: Synthetic rot spiral counter — warns every 100 auto-ingested steps.
    """
    global _synthetic_rot_counter

    quality = classify_training_quality(step)
    step.quality = quality
    save_manifest(session)

    # L12-B: Decontamination — block SWE-bench leaked examples from auto-ingestion.
    _haystack = f"{step.instruction} {step.builder_output_path}"
    if _SWEBENCH_FINGERPRINT_RE.search(_haystack):
        log.warning(
            "[L12-B] SWE-bench fingerprint detected in step %d — routing to human review "
            "instead of auto-ingestion to prevent benchmark contamination.",
            step.id,
        )
        quality = "inconclusive"  # override — never auto-ingest contaminated examples

    # L10-B: recover reasoning prose saved alongside the code output
    _reasoning_text = ""
    if step.builder_output_path:
        _rp = Path(step.builder_output_path).with_suffix(".reasoning")
        if _rp.exists():
            try:
                _reasoning_text = _rp.read_text(encoding="utf-8")
            except OSError:
                pass

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "session_id": session.session_id,
        "step_id": step.id,
        "lang": session.lang,
        "instruction": step.instruction,
        "builder_output_path": step.builder_output_path,
        "builder_reasoning": _reasoning_text,  # L10-B
        "compiler_result": step.compiler_result,
        "monitor_verdict": step.monitor_verdict,
        "quality": quality,
        "retries": step.retries,
        "escalations": step.escalations,
        "source": "ai_generated",  # L11-A
    }

    if quality == "training_ready":
        _RETRAIN_Q.parent.mkdir(parents=True, exist_ok=True)
        with _queue_write_lock:  # G17: serialise open()+write() — not atomic otherwise
            with _RETRAIN_Q.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        log.info("Step %d queued → training (quality: training_ready)", step.id)

        # L11-A: Synthetic rot spiral guard — warn every N consecutive AI-only examples.
        with _synthetic_rot_lock:
            _synthetic_rot_counter += 1
            if _synthetic_rot_counter % _SYNTHETIC_ROT_WARN_EVERY == 0:
                log.warning(
                    "[L11-A] SYNTHETIC ROT WARNING: %d consecutive AI-generated examples "
                    "in retrain_queue with no human anchor data.  "
                    "Inject ≥30%% human-reviewed examples before next fine-tune to prevent "
                    "dialect drift. (Set entry['source']='human' to reset this counter.)",
                    _synthetic_rot_counter,
                )
    else:
        _HUMAN_Q.parent.mkdir(parents=True, exist_ok=True)
        with _queue_write_lock:  # G17: serialise open()+write()
            with _HUMAN_Q.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        # L11-A: human-review examples break the synthetic streak.
        with _synthetic_rot_lock:
            _synthetic_rot_counter = 0
        log.warning("Step %d queued → human review (quality: inconclusive)", step.id)
