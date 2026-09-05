"""Autotune tuning cycle state machine (tune-loop plan, Todo 5).

Pure stdlib, fully injectable so it is unit-testable WITHOUT a real GPU /
llama-server / relay. The cycle owns the closed loop:

    idle -> consult -> plan -> apply -> restart -> collect -> score
         -> decide -> (rollback | keep) -> loop

Design contract:
  * It NEVER calls subprocess / kills a process directly. All restarts go
    through the injected ``lifecycle`` (duck-typed: ``start_argv(argv, takeover)``
    -> ``(ok, to_serve)`` and ``health_ok()``).
  * Benchmark traffic generation and event collection are injected as callables
    (``benchmark_generator(n)`` and ``event_collector()``) so the relay layer
    (Todo 6) can wire real X-Benchmark:1 requests without coupling this module
    to HTTP.
  * State is persisted at every decision point to ``state_path`` so a relay
    restart can recover ("last interrupted run") and so an ABORT leaves an
    auditable trail (including server_may_be_down).
  * Hard-failure escalation: a restart failure rolls back to last_good_argv; if
    that also fails, it restores original_argv; if THAT also fails it ABORTs with
    server_may_be_down=True. We never silently stop on a dead server.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable

# State constants
IDLE = "idle"
CONSULT = "consult"
PLAN = "plan"
APPLY = "apply"
RESTART = "restart"
COLLECT = "collect"
SCORE = "score"
DECIDE = "decide"
ROLLBACK = "rollback"
KEEP = "keep"
DONE = "done"
ABORT = "abort"

# Simple -> complex single-param tuning order (plan §4.3).
PARAM_ORDER = [
    "ctx", "cache-type", "flash-attn", "parallel",
    "n-batch", "threads", "n-gpu-layers", "reasoning-budget",
]

# Convergence / safety constants (plan decisions).
MIN_RESTART_INTERVAL_S = 60.0
MAX_ROUNDS = 8
CONVERGE_NO_IMPROVE = 0.05          # |new - old| < 5% counts as "no improvement"
CONVERGE_STREAK = 2                 # 2 consecutive no-improve rounds -> converge
REGRESS_THRESHOLD = 0.05            # new < old * (1 - 0.05) -> rollback

MIN_N = 16                          # benchmark events required before scoring


@dataclass
class CycleHistoryEntry:
    step: str
    param: str
    status: str
    score: float | None = None
    ts: float = 0.0
    note: str = ""


class TuneCycle:
    def __init__(self, lifecycle, scorer: Callable, planner: Callable,
                 benchmark_generator: Callable[[int], None],
                 event_collector: Callable[[], list[dict]],
                 state_path: str = "tune_state.json",
                 max_rounds: int = MAX_ROUNDS,
                 min_restart_interval_s: float = MIN_RESTART_INTERVAL_S):
        self.lifecycle = lifecycle
        self.scorer = scorer
        self.planner = planner
        self.benchmark_generator = benchmark_generator
        self.event_collector = event_collector
        self.state_path = state_path
        self.max_rounds = max_rounds
        self.min_restart_interval_s = min_restart_interval_s

        # live state
        self.status = IDLE
        self.applied_spec: dict = {}
        self.last_good_argv: list[str] | None = None
        self.original_argv: list[str] | None = None
        self.history: list[CycleHistoryEntry] = []
        self.server_may_be_down = False
        self._stop_requested = False
        self._last_restart_ts = 0.0

        self._restore_state()

    # ----------------------------- state persistence -----------------------------

    def _snapshot(self) -> dict:
        return {
            "step": self.status,
            "applied_spec": self.applied_spec,
            "last_good_argv": self.last_good_argv,
            "original_argv": self.original_argv,
            "history": [vars(h) for h in self.history],
            "status": self.status,
            "server_may_be_down": self.server_may_be_down,
        }

    def _persist(self) -> None:
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self._snapshot(), f, indent=2)
        except Exception:
            pass  # best-effort; do not let IO failure abort the cycle

    def _restore_state(self) -> None:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        self.status = data.get("status", IDLE)
        self.applied_spec = data.get("applied_spec", {})
        self.last_good_argv = data.get("last_good_argv")
        self.original_argv = data.get("original_argv")
        self.server_may_be_down = bool(data.get("server_may_be_down", False))
        self.history = [CycleHistoryEntry(**h) for h in data.get("history", [])]

    # ----------------------------- public control -----------------------------

    def stop(self) -> None:
        """Request an early stop; the loop checks this each step."""
        self._stop_requested = True

    def _throttle_restart(self) -> None:
        elapsed = time.time() - self._last_restart_ts
        if self._last_restart_ts and elapsed < self.min_restart_interval_s:
            time.sleep(self.min_restart_interval_s - elapsed)

    @staticmethod
    def _assert_iron_rules(argv: list[str]) -> None:
        joined = " ".join(argv)
        if "--jinja" not in argv:
            raise ValueError("iron rule violated: argv missing --jinja")
        # reasoning-budget must be present and not -1
        if "--reasoning-budget" in argv:
            i = argv.index("--reasoning-budget")
            val = argv[i + 1] if i + 1 < len(argv) else ""
            if val == "-1":
                raise ValueError("iron rule violated: reasoning-budget is -1")
        else:
            raise ValueError("iron rule violated: argv missing --reasoning-budget")

    # ----------------------------- main loop -----------------------------

    def run(self, preset: str, current_spec: dict, argv_builder: Callable[[dict], list[str]]) -> str:
        """Drive the closed loop. Returns the terminal status (DONE / ABORT).

        ``argv_builder`` maps a spec dict -> argv list (relay wires this to
        ServerConfig.to_argv). ``current_spec`` is the baseline the cycle mutates.
        """
        # Capture the production argv ONCE so we can always restore it.
        if self.original_argv is None:
            self.original_argv = list(argv_builder(current_spec))
        if self.last_good_argv is None:
            self.last_good_argv = list(self.original_argv)

        self.applied_spec = dict(current_spec)
        self.status = CONSULT
        self._persist()

        no_improve_streak = 0
        rounds = 0

        for param in PARAM_ORDER:
            rounds += 1
            if rounds > self.max_rounds:
                self.status = DONE
                self._persist()
                return self.status

            if self._stop_requested:
                self.status = DONE          # keep current applied config
                self._persist()
                return self.status

            # ---- plan ----
            self.status = PLAN
            goal = self.planner(preset, dict(self.applied_spec), param)
            if goal is None or getattr(goal, "param", "__none__") == "__none__":
                # planner says no change for this param -> skip
                self.history.append(CycleHistoryEntry(
                    step=PLAN, param=param, status="skip",
                    ts=time.time(), note="planner returned no-op"))
                continue

            # apply the goal into the spec
            self.applied_spec = self._apply_goal(self.applied_spec, goal)
            new_argv = argv_builder(self.applied_spec)
            try:
                self._assert_iron_rules(new_argv)
            except ValueError as e:
                self.status = ABORT
                self.server_may_be_down = False
                self.history.append(CycleHistoryEntry(
                    step=APPLY, param=param, status="abort",
                    ts=time.time(), note=str(e)))
                self._persist()
                return self.status

            # ---- restart ----
            self.status = RESTART
            self._throttle_restart()
            ok, _ = self.lifecycle.start_argv(list(new_argv), takeover=True)
            self._last_restart_ts = time.time()
            if not ok:
                # hard failure -> rollback to last_good
                self.status = ROLLBACK
                rolled = self._rollback(self.last_good_argv)
                if not rolled:
                    return self._hard_abort("rollback restart failed")
                self.history.append(CycleHistoryEntry(
                    step=ROLLBACK, param=param, status="rolled-back",
                    ts=time.time(), note="restart failed; restored last_good"))
                continue

            # ---- collect (benchmark traffic + score) ----
            self.status = COLLECT
            self.benchmark_generator(MIN_N)
            events = self.event_collector()
            new_score = self.scorer(events) if len(events) >= MIN_N else None

            # ---- decide ----
            self.status = DECIDE
            old_score = self._last_kept_score()
            if new_score is None:
                # insufficient samples -> cannot judge; keep (conservative)
                self.history.append(CycleHistoryEntry(
                    step=SCORE, param=param, status="no-score",
                    score=None, ts=time.time(), note="insufficient benchmark samples"))
                self._persist()
                continue

            improved = old_score is None or new_score >= old_score * (1 - REGRESS_THRESHOLD)
            if improved:
                self.last_good_argv = list(new_argv)
                self.history.append(CycleHistoryEntry(
                    step=KEEP, param=param, status="kept",
                    score=new_score, ts=time.time()))
                # convergence check
                if old_score is not None and abs(new_score - old_score) < CONVERGE_NO_IMPROVE:
                    no_improve_streak += 1
                else:
                    no_improve_streak = 0
                if no_improve_streak >= CONVERGE_STREAK:
                    self.status = DONE
                    self._persist()
                    return self.status
            else:
                # regression -> rollback to last_good
                self.status = ROLLBACK
                rolled = self._rollback(self.last_good_argv)
                if not rolled:
                    return self._hard_abort("rollback after regression failed")
                self.history.append(CycleHistoryEntry(
                    step=ROLLBACK, param=param, status="rolled-back",
                    score=new_score, ts=time.time(), note="regression; restored last_good"))
            self._persist()

        self.status = DONE
        self._persist()
        return self.status

    # ----------------------------- helpers -----------------------------

    def _apply_goal(self, spec: dict, goal) -> dict:
        """Apply a TuneGoal to a copy of the spec (mutates the named param)."""
        out = dict(spec)
        out[goal.param] = goal.target
        return out

    def _last_kept_score(self) -> float | None:
        # scan history for the most recent KEEP score
        for h in reversed(self.history):
            if h.step == KEEP and h.score is not None:
                return h.score
        return None

    def _rollback(self, argv: list[str]) -> bool:
        """Re-apply a known-good argv via the lifecycle. Returns True if ok."""
        try:
            self._assert_iron_rules(argv)
        except ValueError:
            return False
        self._throttle_restart()
        ok, _ = self.lifecycle.start_argv(list(argv), takeover=True)
        self._last_restart_ts = time.time()
        if ok:
            self.applied_spec = {}  # spec is stale; relay rebuilds from /props next run
        return ok

    def _hard_abort(self, note: str) -> str:
        """Escalate: restore original_argv; if that fails, ABORT + server down."""
        if self.original_argv is not None and self._rollback(self.original_argv):
            self.status = ABORT
            self.server_may_be_down = False
            self.history.append(CycleHistoryEntry(
                step=ABORT, param="", status="abort-restored-original",
                ts=time.time(), note=note + "; restored original_argv"))
            self._persist()
            return self.status
        # even the original won't come back up -> mark server down, do NOT
        # silently leave a dead server.
        self.status = ABORT
        self.server_may_be_down = True
        self.history.append(CycleHistoryEntry(
            step=ABORT, param="", status="abort-server-down",
            ts=time.time(), note=note + "; original_argv also failed -> server_may_be_down"))
        self._persist()
        return self.status

