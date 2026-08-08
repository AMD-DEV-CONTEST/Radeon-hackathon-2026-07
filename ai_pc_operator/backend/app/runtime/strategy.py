"""Dynamic Strategy Engine — adaptive command routing with retry, circuit breaker,
intent memory, and speculative prefetch.

Design philosophy: Don't just execute commands. Learn from every command.
Every success makes future similar commands faster. Every failure makes the
system more resilient.

Key components:
  - StrategyRouter: Adapts tool selection based on historical success rates
  - CircuitBreaker: Prevents cascading failures on broken tools
  - IntentMemory: Learns which tool sequences work for which intents
  - SpeculativePrefetcher: Pre-warms tools before the command finishes planning
  - AdaptiveRetry: Retries with different strategies based on failure type
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
STRATEGY_PATH = ROOT / "ai_pc_operator" / "data" / "memory" / "strategy_state.json"


# ─── Circuit Breaker ──────────────────────────────────────────

@dataclass
class CircuitState:
    """State of a circuit breaker for a single tool."""
    failures: int = 0
    last_failure: float = 0.0
    last_success: float = 0.0
    is_open: bool = False
    open_until: float = 0.0

    def record_success(self) -> None:
        self.failures = 0
        self.is_open = False
        self.open_until = 0.0
        self.last_success = time.time()

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure = time.time()
        # Open circuit after 3 failures in 60 seconds
        if self.failures >= 3:
            self.is_open = True
            self.open_until = time.time() + 30.0  # 30s cooldown

    def is_available(self) -> bool:
        if not self.is_open:
            return True
        if time.time() > self.open_until:
            self.is_open = False
            self.failures = 0
            return True
        return False


class CircuitBreaker:
    """Prevents cascading failures. Each tool gets its own circuit."""

    def __init__(self) -> None:
        self._circuits: Dict[str, CircuitState] = defaultdict(CircuitState)

    def is_available(self, tool: str) -> bool:
        return self._circuits[tool].is_available()

    def record_success(self, tool: str) -> None:
        self._circuits[tool].record_success()

    def record_failure(self, tool: str) -> None:
        self._circuits[tool].record_failure()

    def status(self) -> Dict[str, Any]:
        return {
            tool: {
                "failures": state.failures,
                "open": state.is_open,
                "available": state.is_available(),
            }
            for tool, state in self._circuits.items()
            if state.failures > 0
        }


# ─── Intent Memory ────────────────────────────────────────────

@dataclass
class ToolSequence:
    """Recorded successful tool sequence for an intent."""
    tools: List[str]
    success_count: int = 0
    failure_count: int = 0
    avg_duration_ms: float = 0.0
    last_used: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5

    @property
    def reliability_score(self) -> float:
        """Bayesian weighted success rate — favors tools with more data."""
        total = self.success_count + self.failure_count
        prior = 0.5  # Uninformative prior
        if total == 0:
            return prior
        return (prior * 2 + self.success_count) / (2 + total)


class IntentMemory:
    """Learns which tool sequences succeed for each intent.

    Persists to disk. On next boot, previously successful paths
    are tried first — making the agent faster over time.
    """

    def __init__(self, path: Path = STRATEGY_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._intents: Dict[str, List[ToolSequence]] = defaultdict(list)
        self._load()

    def record_success(
        self, intent: str, tools: List[str], duration_ms: float
    ) -> None:
        seq = self._find_or_create(intent, tools)
        seq.success_count += 1
        # Exponential moving average of duration
        alpha = 0.3
        seq.avg_duration_ms = (
            alpha * duration_ms + (1 - alpha) * seq.avg_duration_ms
        ) if seq.avg_duration_ms > 0 else duration_ms
        seq.last_used = time.time()
        self._save()

    def record_failure(self, intent: str, tools: List[str]) -> None:
        seq = self._find_or_create(intent, tools)
        seq.failure_count += 1
        seq.last_used = time.time()
        self._save()

    def best_tools_for_intent(self, intent: str) -> Optional[List[str]]:
        """Return the most reliable tool sequence for this intent."""
        sequences = self._intents.get(intent, [])
        if not sequences:
            return None
        # Sort by reliability score, then by recency
        sequences.sort(
            key=lambda s: (s.reliability_score, s.last_used), reverse=True
        )
        best = sequences[0]
        if best.success_rate < 0.3 and (best.success_count + best.failure_count) >= 5:
            return None  # Too unreliable, don't recommend
        return best.tools

    def get_stats(self, intent: str) -> List[Dict[str, Any]]:
        return [
            {
                "tools": seq.tools,
                "success_count": seq.success_count,
                "failure_count": seq.failure_count,
                "success_rate": round(seq.success_rate, 3),
                "avg_duration_ms": round(seq.avg_duration_ms, 1),
                "reliability": round(seq.reliability_score, 3),
            }
            for seq in self._intents.get(intent, [])
        ]

    def _find_or_create(self, intent: str, tools: List[str]) -> ToolSequence:
        tool_key = json.dumps(tools, sort_keys=True)
        for seq in self._intents[intent]:
            if json.dumps(seq.tools, sort_keys=True) == tool_key:
                return seq
        seq = ToolSequence(tools=tools)
        self._intents[intent].append(seq)
        return seq

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for intent, sequences in data.items():
                for s in sequences:
                    self._intents[intent].append(ToolSequence(
                        tools=s["tools"],
                        success_count=s.get("success_count", 0),
                        failure_count=s.get("failure_count", 0),
                        avg_duration_ms=s.get("avg_duration_ms", 0.0),
                        last_used=s.get("last_used", 0.0),
                    ))
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        data = {}
        for intent, sequences in self._intents.items():
            data[intent] = [
                {
                    "tools": seq.tools,
                    "success_count": seq.success_count,
                    "failure_count": seq.failure_count,
                    "avg_duration_ms": seq.avg_duration_ms,
                    "last_used": seq.last_used,
                }
                for seq in sequences
            ]
        try:
            self.path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
        except OSError:
            pass


# ─── Adaptive Retry ───────────────────────────────────────────

@dataclass(frozen=True)
class RetryPolicy:
    """Configurable retry behavior per failure type."""
    max_retries: int = 1
    backoff_base_ms: int = 200
    backoff_max_ms: int = 5000
    retry_same: bool = True
    retry_simplified: bool = False


# Predefined retry strategies for different failure modes
RETRY_POLICIES: Dict[str, RetryPolicy] = {
    "timeout": RetryPolicy(max_retries=1, backoff_base_ms=500, retry_same=False),
    "connection": RetryPolicy(max_retries=2, backoff_base_ms=1000),
    "not_found": RetryPolicy(max_retries=0),  # Don't retry "element not found"
    "permission": RetryPolicy(max_retries=0),  # Don't retry permission errors
    "busy": RetryPolicy(max_retries=2, backoff_base_ms=2000),
    "unknown": RetryPolicy(max_retries=1, backoff_base_ms=500, retry_same=False),
}


def classify_failure(error: str) -> str:
    """Classify an error string into a failure category."""
    error_lower = error.lower()
    if any(w in error_lower for w in ["timeout", "timed out", "deadline"]):
        return "timeout"
    if any(w in error_lower for w in ["connect", "refused", "unreachable", "network"]):
        return "connection"
    if any(w in error_lower for w in ["not found", "no such", "missing", "not exist"]):
        return "not_found"
    if any(w in error_lower for w in ["permission", "denied", "forbidden", "unauthorized"]):
        return "permission"
    if any(w in error_lower for w in ["busy", "locked", "in use", "contended"]):
        return "busy"
    return "unknown"


# ─── Speculative Prefetcher ───────────────────────────────────

class SpeculativePrefetcher:
    """Predicts which tools the next command will need and pre-warms them.

    Uses two signals:
      1. IntentMemory: if we've seen this intent before, prefetch its tools
      2. Co-occurrence: if tool A was just used, prefetch tool B (learned pair)
    """

    def __init__(self) -> None:
        self._cooccurrence: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record_cooccurrence(self, tool_a: str, tool_b: str) -> None:
        """Record that tool_b was used after tool_a."""
        self._cooccurrence[tool_a][tool_b] += 1

    def predict_next_tools(self, last_tool: str, limit: int = 3) -> List[str]:
        """Given the last tool used, predict what comes next."""
        pairs = self._cooccurrence.get(last_tool, {})
        if not pairs:
            return []
        sorted_pairs = sorted(pairs.items(), key=lambda x: x[1], reverse=True)
        return [tool for tool, _ in sorted_pairs[:limit]]

    def get_prefetch_candidates(
        self, intent: str, intent_memory: IntentMemory, limit: int = 3
    ) -> List[str]:
        """Combine intent memory with co-occurrence for prefetch list."""
        candidates = []

        # From intent memory
        known_tools = intent_memory.best_tools_for_intent(intent)
        if known_tools:
            candidates.extend(known_tools)

        # From co-occurrence with already-known tools
        for tool in candidates[:2]:
            next_tools = self.predict_next_tools(tool, limit=2)
            for t in next_tools:
                if t not in candidates:
                    candidates.append(t)

        return candidates[:limit]


# ─── Strategy Router ──────────────────────────────────────────

class StrategyRouter:
    """Orchestrates adaptive routing for the full command pipeline.

    Integrates:
      - CircuitBreaker: skip broken tools
      - IntentMemory: prefer historically successful paths
      - SpeculativePrefetcher: pre-warm likely-needed tools
      - AdaptiveRetry: retry with backoff on transient failures
    """

    def __init__(self) -> None:
        self.circuit_breaker = CircuitBreaker()
        self.intent_memory = IntentMemory()
        self.prefetcher = SpeculativePrefetcher()
        self._last_tool_per_intent: Dict[str, str] = {}

    async def execute_with_strategy(
        self,
        tool_name: str,
        args: Dict[str, Any],
        execute_fn: Callable[..., Any],
        intent: str = "unknown",
        command_id: int = 0,
    ) -> Dict[str, Any]:
        """Execute a tool with circuit breaker, retry, and learning.

        execute_fn: async callable(tool_name, args) -> result dict
        """
        # Check circuit breaker
        if not self.circuit_breaker.is_available(tool_name):
            return {
                "status": "failed",
                "tool": tool_name,
                "error": f"Circuit breaker open for {tool_name} (too many recent failures)",
                "recovery": "Wait 30 seconds or use an alternative tool",
            }

        # Classify failure and apply retry policy
        failure_type = None
        last_error = None

        for attempt in range(3):  # Max 3 attempts
            start = time.time()
            try:
                result = await execute_fn(tool_name, args)
                duration_ms = (time.time() - start) * 1000

                if result.get("status") == "success":
                    # Record success
                    self.circuit_breaker.record_success(tool_name)

                    # Learn: record tool sequence for this intent
                    tools_so_far = [tool_name]
                    self.intent_memory.record_success(intent, tools_so_far, duration_ms)

                    # Learn: co-occurrence with previous tool
                    prev_tool = self._last_tool_per_intent.get(intent)
                    if prev_tool and prev_tool != tool_name:
                        self.prefetcher.record_cooccurrence(prev_tool, tool_name)
                    self._last_tool_per_intent[intent] = tool_name

                    return result

                # Tool returned a failure (not an exception)
                last_error = result.get("error", "Tool returned failure status")
                failure_type = classify_failure(last_error)
                break  # Don't retry tool-returned failures (they're deterministic)

            except Exception as e:
                last_error = str(e)
                failure_type = classify_failure(last_error)
                self.circuit_breaker.record_failure(tool_name)

                # Check retry policy
                policy = RETRY_POLICIES.get(failure_type, RETRY_POLICIES["unknown"])
                if attempt >= policy.max_retries:
                    break

                # Backoff
                backoff_ms = min(
                    policy.backoff_base_ms * (2 ** attempt),
                    policy.backoff_max_ms,
                )
                await asyncio.sleep(backoff_ms / 1000)

        # Record failure in intent memory
        self.intent_memory.record_failure(intent, [tool_name])

        return {
            "status": "failed",
            "tool": tool_name,
            "error": last_error or "Unknown error",
            "failure_type": failure_type,
            "attempts": attempt + 1,
        }

    def get_prefetch_list(self, intent: str) -> List[str]:
        """Get tools to prefetch for a given intent."""
        return self.prefetcher.get_prefetch_candidates(intent, self.intent_memory)

    def status(self) -> Dict[str, Any]:
        return {
            "circuit_breaker": self.circuit_breaker.status(),
            "intent_memory_intents": list(self.intent_memory._intents.keys()),
            "cooccurrence_pairs": sum(
                len(v) for v in self.prefetcher._cooccurrence.values()
            ),
        }
