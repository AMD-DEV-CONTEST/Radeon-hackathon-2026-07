"""Three-tier memory architecture for the trading agent.

Tier 1 — WorkingMemory:  Current conversation context (messages, tool calls,
    current strategy/backtest). RAM only, cleared per session.

Tier 2 — EpisodicMemory: All strategies generated, backtest results, user
    requests, and agent decision traces within a session. Persisted to a
    JSON file so context survives across turns and sessions.

Tier 3 — SemanticMemory: User preferences (risk tolerance, preferred
    indicators/timeframes), strategy performance statistics, and extracted
    experience rules. Persisted across sessions in a separate JSON file.

AgentMemory is the facade that combines all three tiers and provides a
unified interface for the agent loop and prompt builder.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── Helpers ─────────────────────────────────────────────────────────


def _summarize_result(result: dict, max_chars: int = 300) -> str:
    """Compact one-line summary of a tool result for prompt context."""
    if not result:
        return "empty"
    if "error" in result and result.get("success") is False:
        return f"error: {result['error']}"
    if "total_return" in result:
        return (
            f"return={result['total_return']:.2%}, "
            f"sharpe={result.get('sharpe_ratio', 0):.2f}, "
            f"max_dd={result.get('max_drawdown', 0):.2%}, "
            f"trades={result.get('total_trades', 0)}"
        )
    if "is_valid" in result:
        return f"valid={result['is_valid']}, errors={result.get('errors', [])}"
    if "last_price" in result:
        return f"price=${result.get('last_price', 0):,.2f}"
    if "is_robust" in result:
        return f"robust={result['is_robust']}, overfit_score={result.get('overfitting_score', 0):+.2%}"
    if "context" in result:
        return f"retrieved {len(result['context'])} chars of knowledge"
    if "success" in result:
        return f"success={result['success']}"
    s = str(result)
    return s[:max_chars] + "..." if len(s) > max_chars else s


def _truncate_result(result: dict, max_size: int = 2048) -> dict:
    """Truncate large tool results to prevent memory exhaustion.

    Removes large list fields (equity_curve, trades, candles) that
    are not needed for memory context but can be megabytes in size.
    """
    if not isinstance(result, dict):
        return result
    truncated = {}
    for k, v in result.items():
        if isinstance(v, list) and len(v) > 50:
            truncated[k] = f"[{len(v)} items, truncated]"
        elif isinstance(v, dict):
            truncated[k] = _truncate_result(v, max_size)
        else:
            truncated[k] = v
    return truncated


# ═══════════════════════════════════════════════════════════════════
#  Tier 1: WorkingMemory (工作记忆)
# ═══════════════════════════════════════════════════════════════════


@dataclass
class WorkingMemory:
    """Tier 1 — short-term context for the current conversation.

    Holds the last N message pairs, recent tool calls, and the current
    strategy/backtest being worked on. All data lives in RAM and is
    cleared when the session ends.
    """

    messages: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    max_messages: int = 40  # Keep last 20 pairs

    # ── Messages ───────────────────────────────────────────────────

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content, "ts": time.time()})
        self._trim()

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content, "ts": time.time()})
        self._trim()

    def get_context_window(self, n: int = 6) -> list[dict]:
        """Return the last *n* message pairs for LLM context."""
        return self.messages[-(n * 2):] if self.messages else []

    def get_recent_tools(self, n: int = 5) -> list[dict]:
        return self.tool_calls[-n:]

    def add_tool_call(self, tool: str, params: dict, result: dict) -> None:
        # Truncate large results to prevent memory exhaustion
        result_stored = _truncate_result(result, max_size=2048)
        self.tool_calls.append({
            "tool": tool,
            "params": params,
            "result_summary": _summarize_result(result),
            "result": result_stored,
            "ts": time.time(),
        })

    def _trim(self) -> None:
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def format_for_prompt(self) -> str:
        """Format working memory as prompt context."""
        parts: list[str] = []
        if self.tool_calls:
            parts.append("## Recent Actions")
            for tc in self.get_recent_tools(5):
                parts.append(f"- {tc['tool']} → {tc['result_summary']}")
        return "\n".join(parts) if parts else "No recent actions."


# ═══════════════════════════════════════════════════════════════════
#  Tier 2: EpisodicMemory (情景记忆)
# ═══════════════════════════════════════════════════════════════════


@dataclass
class EpisodicMemory:
    """Tier 2 — session-level episodic record.

    Stores all strategies generated, backtest results, user requests, and
    agent decision traces. Persists to a JSON file so the episode can be
    resumed or reviewed.
    """

    strategies: list[dict] = field(default_factory=list)
    backtest_results: list[dict] = field(default_factory=list)
    user_requests: list[str] = field(default_factory=list)
    agent_thoughts: list[str] = field(default_factory=list)
    session_id: str = ""
    _file_path: str | None = None

    # ── Recording ──────────────────────────────────────────────────

    def add_strategy(self, dsl: dict) -> None:
        name = dsl.get("strategy", {}).get("name", "Unknown")
        pair = dsl.get("strategy", {}).get("market", {}).get("pair", "Unknown")
        timeframe = dsl.get("strategy", {}).get("market", {}).get("timeframe", "Unknown")
        self.strategies.append({
            "name": name,
            "pair": pair,
            "timeframe": timeframe,
            "dsl": dsl,
            "ts": time.time(),
        })
        self._persist()

    def add_backtest_result(self, result: dict) -> None:
        self.backtest_results.append({"result": result, "ts": time.time()})
        self._persist()

    def add_user_request(self, request: str) -> None:
        self.user_requests.append(request)
        self._persist()

    def add_thought(self, thought: str) -> None:
        self.agent_thoughts.append(thought)

    # ── Access ─────────────────────────────────────────────────────

    @property
    def latest_strategy(self) -> dict | None:
        return self.strategies[-1]["dsl"] if self.strategies else None

    @property
    def latest_backtest(self) -> dict | None:
        return self.backtest_results[-1]["result"] if self.backtest_results else None

    @property
    def all_strategy_names(self) -> list[str]:
        return [s["name"] for s in self.strategies]

    # ── Persistence ────────────────────────────────────────────────

    def set_persistence(self, file_path: str) -> None:
        self._file_path = file_path
        # Load existing data if file exists
        if os.path.exists(file_path):
            try:
                with open(file_path) as f:
                    data = json.load(f)
                self.strategies = data.get("strategies", [])
                self.backtest_results = data.get("backtest_results", [])
                self.user_requests = data.get("user_requests", [])
                self.agent_thoughts = data.get("agent_thoughts", [])
            except (json.JSONDecodeError, IOError):
                pass  # Start fresh if file is corrupt

    def _persist(self) -> None:
        if not self._file_path:
            return
        try:
            data = {
                "session_id": self.session_id,
                "strategies": self.strategies,
                "backtest_results": self.backtest_results,
                "user_requests": self.user_requests,
                "agent_thoughts": self.agent_thoughts,
            }
            Path(self._file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (IOError, TypeError):
            pass  # Non-fatal: memory works without persistence

    def format_for_prompt(self) -> str:
        """Format episodic memory as prompt context."""
        parts: list[str] = []
        if self.strategies:
            parts.append("## Strategies Generated This Session")
            for s in self.strategies[-3:]:  # Last 3 strategies
                parts.append(f"- {s['name']} ({s['pair']}, {s['timeframe']})")

        if self.backtest_results:
            latest_bt = self.backtest_results[-1]["result"]
            parts.append(
                f"\n## Latest Backtest: "
                f"return={latest_bt.get('total_return', 0):.2%}, "
                f"sharpe={latest_bt.get('sharpe_ratio', 0):.2f}, "
                f"max_dd={latest_bt.get('max_drawdown', 0):.2%}"
            )
        return "\n".join(parts) if parts else "No strategies generated yet."


# ═══════════════════════════════════════════════════════════════════
#  Tier 3: SemanticMemory (语义记忆)
# ═══════════════════════════════════════════════════════════════════


@dataclass
class SemanticMemory:
    """Tier 3 — long-term knowledge extracted across sessions.

    Stores:
    - User preferences (risk tolerance, preferred indicators, timeframes)
    - Strategy performance statistics (which patterns work well)
    - Extracted experience rules (insights from past sessions)

    Persists across sessions in a separate JSON file, loaded at startup.
    """

    user_preferences: dict = field(default_factory=lambda: {
        "risk_tolerance": "moderate",  # conservative | moderate | aggressive
        "preferred_indicators": [],
        "preferred_timeframes": [],
        "preferred_pairs": [],
    })
    strategy_stats: list[dict] = field(default_factory=list)
    experience_rules: list[str] = field(default_factory=list)
    _file_path: str | None = None

    # ── Preference learning ─────────────────────────────────────────

    def update_preferences(self, key: str, value: str | list) -> None:
        """Update a user preference, merging list values."""
        if isinstance(value, list):
            existing = self.user_preferences.get(key, [])
            for v in value:
                if v not in existing:
                    existing.append(v)
            self.user_preferences[key] = existing
        else:
            self.user_preferences[key] = value
        self._persist()

    def remove_preference(self, key: str) -> bool:
        """Remove a user preference (rule cancellation). Returns True if removed.

        Added for the memory-consistency S8 scenario: a rule the user
        explicitly cancels must vanish from long-term memory, not linger.
        """
        if key in self.user_preferences:
            del self.user_preferences[key]
            self._persist()
            return True
        return False

    def learn_from_session(self, episodic: EpisodicMemory) -> None:
        """Extract insights from an episodic memory and store them.

        Called at the end of a session or when a backtest completes.
        Updates strategy stats and derives experience rules.
        """
        # Record strategy performance
        for i, bt in enumerate(episodic.backtest_results):
            result = bt["result"]
            strategy_name = ""
            pair = ""
            if i < len(episodic.strategies):
                strategy_name = episodic.strategies[i].get("name", "")
                pair = episodic.strategies[i].get("pair", "")

            self.strategy_stats.append({
                "strategy_name": strategy_name,
                "pair": pair,
                "total_return": result.get("total_return", 0),
                "sharpe": result.get("sharpe_ratio", 0),
                "max_drawdown": result.get("max_drawdown", 0),
                "win_rate": result.get("win_rate", 0),
                "ts": time.time(),
            })

        # Learn preferred pairs/timeframes from strategies
        for s in episodic.strategies:
            if s.get("pair") and s["pair"] not in self.user_preferences["preferred_pairs"]:
                self.user_preferences["preferred_pairs"].append(s["pair"])
            if s.get("timeframe") and s["timeframe"] not in self.user_preferences["preferred_timeframes"]:
                self.user_preferences["preferred_timeframes"].append(s["timeframe"])

        # Derive experience rules from backtest performance
        if episodic.backtest_results:
            best = max(
                episodic.backtest_results,
                key=lambda bt: bt["result"].get("sharpe_ratio", 0),
            )
            best_result = best["result"]
            if best_result.get("sharpe_ratio", 0) > 1.0:
                rule = (
                    f"Strategy with Sharpe={best_result.get('sharpe_ratio', 0):.2f} "
                    f"and return={best_result.get('total_return', 0):.2%} "
                    f"performed well — consider similar parameters."
                )
                if rule not in self.experience_rules:
                    self.experience_rules.append(rule)

            worst = min(
                episodic.backtest_results,
                key=lambda bt: bt["result"].get("total_return", 0),
            )
            worst_result = worst["result"]
            if worst_result.get("total_return", 0) < 0:
                rule = (
                    f"Strategy with return={worst_result.get('total_return', 0):.2%} "
                    f"performed poorly — avoid similar parameters."
                )
                if rule not in self.experience_rules:
                    self.experience_rules.append(rule)

        self._persist()

    # ── Access ─────────────────────────────────────────────────────

    def get_strategy_summary(self) -> str:
        """Summarize historical strategy performance for prompt."""
        if not self.strategy_stats:
            return "No historical strategy data."
        total = len(self.strategy_stats)
        avg_sharpe = sum(s["sharpe"] for s in self.strategy_stats) / total
        positive = sum(1 for s in self.strategy_stats if s["total_return"] > 0)
        return (
            f"{total} strategies tested historically, "
            f"{positive}/{total} profitable, "
            f"avg Sharpe={avg_sharpe:.2f}"
        )

    # ── Persistence ────────────────────────────────────────────────

    def set_persistence(self, file_path: str) -> None:
        self._file_path = file_path
        if os.path.exists(file_path):
            try:
                with open(file_path) as f:
                    data = json.load(f)
                self.user_preferences = data.get("user_preferences", self.user_preferences)
                self.strategy_stats = data.get("strategy_stats", [])
                self.experience_rules = data.get("experience_rules", [])
            except (json.JSONDecodeError, IOError):
                pass

    def _persist(self) -> None:
        if not self._file_path:
            return
        try:
            data = {
                "user_preferences": self.user_preferences,
                "strategy_stats": self.strategy_stats,
                "experience_rules": self.experience_rules,
            }
            Path(self._file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (IOError, TypeError):
            pass

    def format_for_prompt(self) -> str:
        """Format semantic memory as prompt context."""
        parts: list[str] = []
        prefs = self.user_preferences

        # Extra explicit long-term rules (from memory_extract):
        # max_daily_drawdown, unified_stop_loss, etc.
        _EXTRA_LABELS = {
            "max_daily_drawdown": "Max daily drawdown tolerance",
            "unified_stop_loss": "Unified stop-loss",
        }

        # Only include if there's actual learned data
        has_prefs = (
            prefs.get("preferred_pairs")
            or prefs.get("preferred_indicators")
            or prefs.get("preferred_timeframes")
            or prefs.get("risk_tolerance", "moderate") != "moderate"
            or any(k in prefs for k in _EXTRA_LABELS)
        )
        if has_prefs:
            parts.append("## Long-Term Memory")
            if prefs.get("preferred_pairs"):
                parts.append(f"- User prefers: {', '.join(prefs['preferred_pairs'][:3])}")
            if prefs.get("preferred_timeframes"):
                parts.append(f"- Preferred timeframes: {', '.join(prefs['preferred_timeframes'][:3])}")
            if prefs.get("risk_tolerance", "moderate") != "moderate":
                parts.append(f"- Risk tolerance: {prefs['risk_tolerance']}")
            for extra_key, label in _EXTRA_LABELS.items():
                if prefs.get(extra_key):
                    parts.append(f"- {label}: {prefs[extra_key]}")

        if self.strategy_stats:
            parts.append(f"\n## Historical Performance\n{self.get_strategy_summary()}")

        if self.experience_rules:
            parts.append("\n## Experience Rules")
            for rule in self.experience_rules[-3:]:  # Last 3 rules
                parts.append(f"- {rule}")

        return "\n".join(parts) if parts else "No long-term memory yet."


# ═══════════════════════════════════════════════════════════════════
#  AgentMemory — Facade combining all three tiers
# ═══════════════════════════════════════════════════════════════════


class AgentMemory:
    """Three-tier memory facade for the ReAct agent.

    Combines WorkingMemory (RAM, per-session), EpisodicMemory (file-backed,
    per-session), and SemanticMemory (file-backed, cross-session) into a
    single interface used by the agent loop and prompt builder.

    Usage:
        memory = AgentMemory(data_dir="~/.agent_memory")
        memory.add_user_message("Create an EMA strategy")
        # ... agent loop runs ...
        memory.consolidate()  # Extract insights to semantic memory at end
    """

    def __init__(
        self,
        data_dir: str | None = None,
        session_id: str | None = None,
        max_history: int = 20,
    ):
        self.working = WorkingMemory(max_messages=max_history * 2)
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()

        # Set up persistence if data_dir provided
        if data_dir:
            data_dir = os.path.expanduser(data_dir)
            self.episodic.session_id = session_id or str(int(time.time()))
            self.episodic.set_persistence(
                os.path.join(data_dir, f"episode_{self.episodic.session_id}.json")
            )
            self.semantic.set_persistence(
                os.path.join(data_dir, "semantic_memory.json")
            )

    # ── Delegated methods (for backward compatibility) ─────────────

    # WorkingMemory
    def add_user_message(self, content: str) -> None:
        self.working.add_user_message(content)
        self.episodic.add_user_request(content)

    def add_assistant_message(self, content: str) -> None:
        self.working.add_assistant_message(content)

    def get_context_window(self, n: int = 6) -> list[dict]:
        return self.working.get_context_window(n)

    def add_tool_call(self, tool: str, params: dict, result: dict) -> None:
        self.working.add_tool_call(tool, params, result)

    def get_recent_tools(self, n: int = 5) -> list[dict]:
        return self.working.get_recent_tools(n)

    # EpisodicMemory
    def add_strategy(self, dsl: dict) -> None:
        self.episodic.add_strategy(dsl)

    def add_backtest_result(self, result: dict) -> None:
        self.episodic.add_backtest_result(result)

    def add_thought(self, thought: str) -> None:
        self.episodic.add_thought(thought)

    @property
    def latest_strategy(self) -> dict | None:
        return self.episodic.latest_strategy

    @property
    def latest_backtest(self) -> dict | None:
        return self.episodic.latest_backtest

    @property
    def messages(self) -> list[dict]:
        """Backward-compatible access to working memory messages."""
        return self.working.messages

    @property
    def tool_calls(self) -> list[dict]:
        """Backward-compatible access to working memory tool calls."""
        return self.working.tool_calls

    @property
    def strategies(self) -> list[dict]:
        return self.episodic.strategies

    @property
    def backtest_results(self) -> list[dict]:
        return self.episodic.backtest_results

    # ── Consolidation ──────────────────────────────────────────────

    def consolidate(self) -> None:
        """Extract insights from episodic memory into semantic memory.

        Call this at the end of a session or after a backtest completes
        to update long-term knowledge.
        """
        self.semantic.learn_from_session(self.episodic)

    # ── Prompt formatting ──────────────────────────────────────────

    def summarize_for_prompt(self) -> str:
        """Generate a compact context string combining all three tiers.

        This is the primary interface for the prompt builder — it returns
        a single string that the LLM can read to understand the agent's
        full memory state.
        """
        parts: list[str] = []

        # Tier 3: Semantic (long-term) — first, as context
        sem = self.semantic.format_for_prompt()
        if sem and sem != "No long-term memory yet.":
            parts.append(sem)

        # Tier 2: Episodic (session history)
        epi = self.episodic.format_for_prompt()
        if epi and epi != "No strategies generated yet.":
            parts.append(epi)

        # Tier 1: Working (recent actions)
        work = self.working.format_for_prompt()
        if work and work != "No recent actions.":
            parts.append(work)

        return "\n\n".join(parts) if parts else "No prior memory."

    def format_semantic_for_prompt(self) -> str:
        """Return only semantic memory for the system prompt's long-term context."""
        return self.semantic.format_for_prompt()

    def format_conversation_history(self, n: int = 3) -> str:
        """Format recent conversation messages for the prompt."""
        recent = self.working.get_context_window(n=n)
        if not recent:
            return "First turn."
        return "\n".join(
            f"[{m['role']}]: {m['content'][:200]}..." if len(m.get("content", "")) > 200
            else f"[{m['role']}]: {m.get('content', '')}"
            for m in recent
        )
