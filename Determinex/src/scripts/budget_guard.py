#!/usr/bin/env python3
"""Budget guard — hard caps on cloud spend during PB / SWE-bench mass runs.

Prevents accidental burn-through. Defaults are conservative; tune via env or
constructor args. State persisted to logs/budget_state/<run_name>.json so
restarts/parallel runs share the running total.

Pricing (cache-MISS, 2026-05; conservative):
  deepseek-chat:    $0.14/1M input tokens   $0.28/1M output tokens
  deepseek-reasoner: $0.55/1M input tokens   $2.19/1M output tokens
  claude-sonnet-4:  $3/1M input              $15/1M output (32× pricier!)
  claude-opus:      $15/1M input             $75/1M output (160× pricier!)

Public API:
    g = BudgetGuard(run_name="...", max_usd=1.50, max_calls=60, max_per_task=3)
    if not g.allow(instance_id):
        raise BudgetExceeded(...)
    # ... make the call ...
    g.charge(model, tokens_in, tokens_out, instance_id)
    print(g.status())
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DETERMINEX_ROOT = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
STATE_DIR = DETERMINEX_ROOT / "logs" / "budget_state"
LEDGER_DIR = DETERMINEX_ROOT / "logs" / "api_ledger"

# USD per 1M tokens (cache-miss). Add new models here as we use them.
PRICING: dict[str, tuple[float, float]] = {
    # DeepSeek API now only supports v4-flash and v4-pro (old names alias to flash).
    "deepseek-v4-flash": (0.14, 0.28),  # cheap fast variant (former deepseek-chat replacement)
    "deepseek-v4-pro": (0.55, 2.19),  # top-tier reasoning (former deepseek-reasoner replacement)
    # Legacy aliases (route to flash on backend) — kept for back-compat in budget tracking
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.14, 0.28),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (15.00, 75.00),
}

# Rate applied to a cloud model with no PRICING row. Non-zero on purpose -- see
# estimate_cost_usd. USD per 1M tokens (in, out).
UNKNOWN_CLOUD_RATE: tuple[float, float] = (8.00, 8.00)

# Prefixes that unambiguously name a locally-served model, plus this project's own
# Ollama tags, which are BARE names: hive/ctx_config.py assigns
# `determinex-engineer-v11-dsl` and friends as the DEFAULT role models, and those start
# with "determinex-", not "determinex/".
LOCAL_MODEL_PREFIXES: tuple[str, ...] = (
    "ollama/",
    "ollama_chat/",
    "hosted_vllm/",
    "text-completion-openai/",
    "determinex/",
    "local/",
    "determinex-",
)


def is_local_model(model: str) -> bool:
    """Is this model served locally, and therefore free?

    Deliberately does NOT infer locality from tag syntax. `name:tag` looks
    distinctively Ollama, but Bedrock ships `anthropic.claude-v2:1` -- colon, no
    slash. Reading that as local would price a real cloud call at zero and hide
    genuine spend, which is the worst direction this module can fail in.
    """
    return (model or "").strip().lower().startswith(LOCAL_MODEL_PREFIXES)


def price_per_1m(model: str) -> tuple[float, float] | None:
    """(input, output) $/1M rate for `model`, or None if it is not priced here.

    Matches by SUBSTRING, longest key first. PRICING's keys are bare
    (`deepseek-chat`), but the strings that reach a cost function usually carry a
    provider prefix -- `deepseek/deepseek-chat`,
    `openrouter/deepseek/deepseek-v4-flash`, `anthropic/claude-sonnet-4-6` -- because
    that is what litellm needs. An exact-key `.get()` misses every one of those.

    THE BUG THIS FIXES (2026-07-29). BudgetGuard.estimate_cost and .charge both did
    `PRICING.get(model, (0.0, 0.0))`: exact key, defaulting to FREE. So a prefixed
    cloud model cost $0, `spend_usd` never moved, and the USD cap never engaged --
    on the module whose entire job is refusing to overspend. The default PB
    configuration passes bare names and priced correctly, which is why this survived;
    `DETERMINEX_DEEPSEEK_MODEL` set to the OpenRouter-prefixed form (the form
    CLAUDE.md's .env implies) silently disables the cap.

    hive/budget.py already carried this exact fix, with a comment explaining it, for
    its own copy of the lookup. Both now call this one.
    """
    if not model:
        return None
    m = model.lower()
    for key in sorted(PRICING, key=len, reverse=True):
        if key.lower() in m:
            return PRICING[key]
    return None


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    """Canonical USD estimate for one call. The single cost function.

    Three cases, and the choice of default is the point:
      local     -> exactly 0.0
      priced    -> the real per-model rate
      unknown   -> UNKNOWN_CLOUD_RATE, never 0.0

    An unknown model must cost SOMETHING. Under-reporting spend overspends real
    money; over-reporting merely exhausts a cap early and falls back to local. Those
    outcomes are not symmetric, so the fallback deliberately errs toward the
    recoverable one.
    """
    if is_local_model(model):
        return 0.0
    in_rate, out_rate = price_per_1m(model) or UNKNOWN_CLOUD_RATE
    return (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate


class BudgetExceeded(RuntimeError):
    """Raised when a guard refuses a new call."""


@dataclass
class BudgetState:
    run_name: str
    max_usd: float
    max_calls: int
    max_per_task: int
    calls: int = 0
    spend_usd: float = 0.0
    started_at: float = field(default_factory=time.time)
    by_task: dict[str, int] = field(default_factory=dict)
    by_model: dict[str, dict] = field(default_factory=dict)  # model → {calls, in_tok, out_tok, usd}


class BudgetGuard:
    """Soft API around BudgetState — handles persistence, allow/charge gates.

    Defaults (when env vars not set):
      DETERMINEX_BUDGET_USD       = 2.50  (per run; with regression-stop most tasks won't max out)
      DETERMINEX_BUDGET_CALLS     = 200   (per run)
      DETERMINEX_BUDGET_PER_TASK  = 6     (max cloud calls per single instance — with regression-stop)
    """

    def __init__(
        self,
        run_name: str,
        max_usd: float | None = None,
        max_calls: int | None = None,
        max_per_task: int | None = None,
    ):
        self.run_name = run_name
        self.max_usd = float(
            max_usd if max_usd is not None else os.environ.get("DETERMINEX_BUDGET_USD", "2.50")
        )
        self.max_calls = int(
            max_calls if max_calls is not None else os.environ.get("DETERMINEX_BUDGET_CALLS", "200")
        )
        self.max_per_task = int(
            max_per_task
            if max_per_task is not None
            else os.environ.get("DETERMINEX_BUDGET_PER_TASK", "6")
        )
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._path = STATE_DIR / f"{run_name}.json"
        self.state = self._load()

    def _load(self) -> BudgetState:
        if self._path.exists():
            try:
                d = json.loads(self._path.read_text(encoding="utf-8"))
                return BudgetState(**d)
            except Exception:
                pass
        return BudgetState(
            run_name=self.run_name,
            max_usd=self.max_usd,
            max_calls=self.max_calls,
            max_per_task=self.max_per_task,
        )

    def _save(self) -> None:
        self._path.write_text(json.dumps(asdict(self.state), indent=2), encoding="utf-8")

    def allow(self, instance_id: str) -> tuple[bool, str]:
        """Check if a new cloud call is allowed. Returns (ok, reason_if_not)."""
        if self.state.spend_usd >= self.state.max_usd:
            return (
                False,
                f"global USD cap reached: ${self.state.spend_usd:.4f} ≥ ${self.state.max_usd}",
            )
        if self.state.calls >= self.state.max_calls:
            return False, f"global call cap reached: {self.state.calls} ≥ {self.state.max_calls}"
        per_task = self.state.by_task.get(instance_id, 0)
        if per_task >= self.state.max_per_task:
            return (
                False,
                f"per-task cap reached for {instance_id}: {per_task} ≥ {self.state.max_per_task}",
            )
        return True, ""

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Return estimated USD for a potential call."""
        return estimate_cost_usd(model, tokens_in, tokens_out)

    def allow_estimated(
        self,
        instance_id: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
    ) -> tuple[bool, str, float]:
        """Pre-call gate that includes the estimated cost of the next call."""
        ok, why = self.allow(instance_id)
        est = self.estimate_cost(model, tokens_in, tokens_out)
        if not ok:
            return False, why, est
        if self.state.spend_usd + est > self.state.max_usd:
            return (
                False,
                f"estimated call would exceed USD cap: "
                f"${self.state.spend_usd:.4f} + ${est:.4f} > ${self.state.max_usd}",
                est,
            )
        return True, "", est

    def charge(self, model: str, tokens_in: int, tokens_out: int, instance_id: str) -> float:
        """Record a call after it completes. Returns USD cost of this call."""
        cost = estimate_cost_usd(model, tokens_in, tokens_out)
        self.state.calls += 1
        self.state.spend_usd += cost
        self.state.by_task[instance_id] = self.state.by_task.get(instance_id, 0) + 1
        bm = self.state.by_model.setdefault(
            model, {"calls": 0, "in_tok": 0, "out_tok": 0, "usd": 0.0}
        )
        bm["calls"] += 1
        bm["in_tok"] += tokens_in
        bm["out_tok"] += tokens_out
        bm["usd"] += cost
        self._save()
        return cost

    def status(self) -> str:
        s = self.state
        elapsed = time.time() - s.started_at
        lines = [
            f"=== Budget guard: {self.run_name} ===",
            f"Spent: ${s.spend_usd:.4f} of ${s.max_usd:.2f}  ({100 * s.spend_usd / max(s.max_usd, 1e-9):.1f}%)",
            f"Calls: {s.calls} of {s.max_calls}",
            f"Tasks that hit cloud: {len(s.by_task)}",
            f"Elapsed: {elapsed:.0f}s ({elapsed / 60:.1f}m)",
        ]
        if s.by_model:
            lines.append("By model:")
            for m, d in s.by_model.items():
                lines.append(
                    f"  {m}: {d['calls']} calls, in={d['in_tok']:,} out={d['out_tok']:,} cost=${d['usd']:.4f}"
                )
        return "\n".join(lines)

    def ledger(
        self,
        *,
        instance_id: str,
        attempt: int,
        model: str,
        purpose: str,
        tokens_in_est: int = 0,
        tokens_out_est: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        allowed: bool = True,
        reason: str = "",
        outcome: dict | None = None,
    ) -> Path:
        """Append an API decision/call record for audit and corpus extraction."""
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        out_path = LEDGER_DIR / f"{self.run_name}.jsonl"
        rec = {
            "ts": time.time(),
            "run_name": self.run_name,
            "instance_id": instance_id,
            "attempt": attempt,
            "model": model,
            "purpose": purpose,
            "tokens_in_est": tokens_in_est,
            "tokens_out_est": tokens_out_est,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "estimated_usd": self.estimate_cost(model, tokens_in_est, tokens_out_est),
            "cost_usd": cost_usd,
            "allowed": allowed,
            "reason": reason,
            "running_spend_usd": self.state.spend_usd,
            "max_usd": self.state.max_usd,
            "running_calls": self.state.calls,
            "max_calls": self.state.max_calls,
            "outcome": outcome or {},
        }
        line = json.dumps(rec, default=str) + "\n"
        fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8", errors="replace"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return out_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--status", help="Run name to show status for")
    args = ap.parse_args()
    if args.status:
        g = BudgetGuard(args.status)
        print(g.status())
    else:
        ap.print_help()
