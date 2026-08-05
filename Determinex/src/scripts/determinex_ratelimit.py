#!/usr/bin/env python3
"""
determinex_ratelimit.py -- auto-establishing, rotating per-model rate limiter
==========================================================================
Built because a live test hit a real Gemini 429. Two behaviors, per the ask:

  1. AUTO-ESTABLISH per model. Each model gets an adaptive minimum interval that
     LEARNS its own limit: start optimistic; on a 429 back off multiplicatively
     and record a cooldown; on sustained success relax back toward the floor. No
     hand-tuned RPM tables -- the limit is discovered from the provider's own
     429s and persists for the session (optionally to disk).

  2. ROTATE across models. When one model is cooling down (rate-limited), the
     pool routes the call to the next available model instead of stalling. So a
     429 on Gemini transparently falls over to Claude/DeepSeek/local and the work
     continues -- correctness is still oracle-bounded regardless of which model
     answered.

    from determinex_ratelimit import RotatingGenerator
    from determinex_providers import get_generator
    gen = RotatingGenerator([
        ("gemini", get_generator("gemini")),
        ("claude", get_generator("claude")),
        ("local",  get_generator("local")),
    ]).generate
    # gen(prompt, temperature) -> str, auto-throttled + auto-rotating on 429

Wires into determinex_providers.get_rotating_generator(...) and the amplifier/router.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

GenerateFn = Callable[[str, float], str]

_RATE_LIMIT_RE = re.compile(
    r"\b429\b|rate.?limit|too many requests|quota|RESOURCE_EXHAUSTED|overloaded|"
    r"throttl|capacity",
    re.I,
)


def is_rate_limit_error(exc: BaseException) -> bool:
    return bool(_RATE_LIMIT_RE.search(str(exc)))


@dataclass
class _ModelState:
    min_interval: float = 0.0  # learned min seconds between calls
    last_call: float = 0.0
    cooldown_until: float = 0.0  # hard pause after a 429
    successes: int = 0
    rate_limits: int = 0


@dataclass
class AdaptiveLimiter:
    """Per-model adaptive throttle that learns each model's limit from 429s."""

    floor: float = 0.0  # min interval we relax toward
    ceiling: float = 30.0  # max interval we back off to
    backoff: float = 2.0  # multiply interval on a 429
    relax_after: int = 5  # successes before relaxing
    cooldown_seconds: float = 20.0  # hard pause after a 429
    persist_path: Path | None = None
    _states: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        if self.persist_path and Path(self.persist_path).exists():
            try:
                d = json.loads(Path(self.persist_path).read_text(encoding="utf-8"))
                for k, v in d.items():
                    self._states[k] = _ModelState(min_interval=float(v.get("min_interval", 0.0)))
            except Exception:
                pass

    def _st(self, key: str) -> _ModelState:
        return self._states.setdefault(key, _ModelState())

    def cooling(self, key: str) -> bool:
        return time.time() < self._st(key).cooldown_until

    def wait_time(self, key: str) -> float:
        st = self._st(key)
        now = time.time()
        return max(0.0, st.cooldown_until - now, (st.last_call + st.min_interval) - now)

    def acquire(self, key: str, max_wait: float = 60.0) -> bool:
        """Block until `key` may be called, respecting learned interval + cooldown.
        Returns False if the wait would exceed max_wait (caller should rotate)."""
        with self._lock:
            w = self.wait_time(key)
            if w > max_wait:
                return False
            self._st(key).last_call = time.time() + w
        if w > 0:
            time.sleep(min(w, max_wait))
        return True

    def on_success(self, key: str) -> None:
        with self._lock:
            st = self._st(key)
            st.successes += 1
            st.last_call = time.time()
            if st.successes >= self.relax_after and st.min_interval > self.floor:
                st.min_interval = max(self.floor, st.min_interval / self.backoff)
                st.successes = 0

    def on_rate_limit(self, key: str) -> None:
        """Auto-establish: a 429 teaches this model its real limit."""
        with self._lock:
            st = self._st(key)
            st.rate_limits += 1
            st.successes = 0
            base = st.min_interval or 0.5
            st.min_interval = min(self.ceiling, base * self.backoff)
            st.cooldown_until = time.time() + self.cooldown_seconds
            self._save()

    def learned(self) -> dict:
        return {k: round(v.min_interval, 3) for k, v in self._states.items()}

    def _save(self) -> None:
        if not self.persist_path:
            return
        try:
            Path(self.persist_path).write_text(
                json.dumps(
                    {k: {"min_interval": v.min_interval} for k, v in self._states.items()}, indent=2
                ),
                encoding="utf-8",
            )
        except Exception:
            pass


class RotatingGenerator:
    """A generate(prompt, temperature) that auto-throttles per model and rotates
    to the next available model on a 429 -- so work continues through limits."""

    def __init__(
        self,
        providers: list[tuple[str, GenerateFn]],
        limiter: AdaptiveLimiter | None = None,
        max_rotations: int = 0,
    ):
        if not providers:
            raise ValueError("RotatingGenerator needs at least one provider")
        self.providers = providers
        self.limiter = limiter or AdaptiveLimiter()
        self.max_rotations = max_rotations or (len(providers) * 2)

    def generate(self, prompt: str, temperature: float) -> str:
        last_err: Exception | None = None
        n = len(self.providers)
        for attempt in range(self.max_rotations):
            name, fn = self.providers[attempt % n]
            if self.limiter.cooling(name):
                continue  # skip a model that's cooling down
            if not self.limiter.acquire(name, max_wait=8.0):
                continue  # would wait too long -> rotate
            try:
                out = fn(prompt, temperature)
                self.limiter.on_success(name)
                return out
            except Exception as e:  # noqa: BLE001
                last_err = e
                if is_rate_limit_error(e):
                    self.limiter.on_rate_limit(name)  # learn + cool down, rotate
                    continue
                continue  # other error -> try the next model
        raise RuntimeError(f"all models exhausted/rate-limited: {last_err}")


def main() -> int:
    # demo: a model that 429s twice then works; the limiter learns + a fallback rotates
    calls = {"flaky": 0}

    def flaky(prompt, temperature):
        calls["flaky"] += 1
        if calls["flaky"] <= 2:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return "flaky-ok"

    def backup(prompt, temperature):
        return "backup-ok"

    lim = AdaptiveLimiter(cooldown_seconds=0.0)  # no real sleeping in demo
    rg = RotatingGenerator([("flaky", flaky), ("backup", backup)], limiter=lim)
    print("rotating on 429:")
    for i in range(3):
        print(f"  call {i}: {rg.generate('hi', 0.0)}")
    print("learned per-model min_interval:", lim.learned())
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
