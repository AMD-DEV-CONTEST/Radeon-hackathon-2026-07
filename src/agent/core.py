"""ReAct Agent core — Reasoning + Acting loop.

This module implements the agent loop:
1. Thought: LLM reasons about what to do next
2. Action: LLM selects a tool to call
3. Observation: Tool result is added to memory
4. Repeat until Final Answer or max iterations

The loop replaces the fixed linear pipeline in chat_app.py with an
adaptive, LLM-driven workflow that can:
- Reason about market conditions before generating a strategy
- Validate and retry on failure
- Analyze backtest results and suggest improvements
- Remember previous actions within the conversation
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Generator

import httpx

from .memory import AgentMemory
from .memory_extract import apply_memory_updates
from .prompts import REACT_SYSTEM_PROMPT, TOOL_DESCRIPTIONS, MEMORY_GUIDELINES
from .rl_feedback import RLFeedbackLoop
from .personality import is_trading_intent, build_personality_prompt
from .tools import (
    TOOL_REGISTRY,
    call_vllm,
    execute_tool,
    parse_action,
    _tool_get_market_data,
)

# ── Agent State ─────────────────────────────────────────────────────


@dataclass
class AgentState:
    """Mutable state carried across agent iterations.

    This provides the agent's short-term memory — the current strategy,
    backtest result, and market context, accessible to all tools.
    """

    user_goal: str = ""
    market_context: str = ""
    strategy_dsl: dict | None = None
    backtest_result: dict | None = None
    memory: AgentMemory | None = None
    max_iterations: int = 8
    iteration: int = 0
    # RL feedback loop
    rl_feedback: RLFeedbackLoop | None = None
    # Accumulated thoughts for final output
    thoughts: list[str] = field(default_factory=list)


# ── General conversation handler ────────────────────────────────────


def _handle_general_conversation(
    user_message: str,
    memory: AgentMemory,
) -> Generator[str, None, None]:
    """Handle non-trading messages with personality-driven LLM response.

    Uses the personality prompt (小R) with semantic memory and
    conversation history for a natural, human-like interaction.
    """
    yield "💬"

    semantic_ctx = memory.format_semantic_for_prompt()
    conv_history = memory.format_conversation_history(n=5)

    system_prompt = build_personality_prompt(
        semantic_memory=semantic_ctx,
        conversation_history=conv_history,
    )

    response = call_vllm(system_prompt, user_message, temperature=0.7)

    memory.add_assistant_message(response)
    memory.consolidate()

    yield response


# ── Agent Loop ──────────────────────────────────────────────────────


def _build_agent_prompt(state: AgentState) -> str:
    """Build the user message for the LLM, including context and history."""
    parts: list[str] = [f"User request: {state.user_goal}"]

    # Add action history
    if state.memory and state.memory.tool_calls:
        parts.append("\n" + state.memory.summarize_for_prompt())

    # Add current state
    if state.strategy_dsl:
        name = state.strategy_dsl.get("strategy", {}).get("name", "Unknown")
        parts.append(f"\nCurrent strategy: {name}")

    if state.backtest_result:
        bt = state.backtest_result
        parts.append(
            f"Last backtest: return={bt.get('total_return', 0):.2%}, "
            f"sharpe={bt.get('sharpe_ratio', 0):.2f}, "
            f"max_dd={bt.get('max_drawdown', 0):.2%}, "
            f"alpha={bt.get('alpha', 0):+.2%}"
        )

    parts.append(
        f"\nIteration {state.iteration + 1}/{state.max_iterations}. "
        "Decide your next action."
    )

    return "\n".join(parts)


def _format_system_prompt(state: AgentState) -> str:
    """Build the system prompt with dynamic context from all three memory tiers."""
    # Market context
    market_ctx = state.market_context or "Market data not yet fetched."

    # Tier 3: Semantic memory (long-term preferences + experience rules)
    semantic_ctx = "No long-term memory yet."
    if state.memory:
        semantic_ctx = state.memory.format_semantic_for_prompt()

    # RAG context (from tool calls in working memory)
    rag_ctx = "No knowledge retrieved yet."
    if state.memory and state.memory.tool_calls:
        for tc in state.memory.tool_calls:
            if tc["tool"] == "retrieve_knowledge" and tc.get("result", {}).get("context"):
                rag_ctx = tc["result"]["context"][:1500]
                break

    # Tier 2 + Tier 1: Episodic + Working memory combined
    action_history = "No prior actions."
    if state.memory:
        action_history = state.memory.summarize_for_prompt()

    # Tier 1: Conversation history from working memory
    conv_history = "First turn."
    if state.memory:
        conv_history = state.memory.format_conversation_history(n=3)

    # RL reward feedback (L1: immediate)
    reward_ctx = "No reward feedback yet."
    if state.rl_feedback:
        reward_ctx = state.rl_feedback.format_feedback_for_prompt()

    return REACT_SYSTEM_PROMPT.format(
        tool_descriptions=TOOL_DESCRIPTIONS,
        max_iterations=state.max_iterations,
        market_context=market_ctx,
        rag_context=rag_ctx,
        action_history=action_history,
        conversation_history=conv_history,
        semantic_memory=semantic_ctx,
        reward_feedback=reward_ctx,
        memory_guidelines=MEMORY_GUIDELINES,
    )


def run_agent_loop(
    user_message: str,
    history: list,
    max_iterations: int = 8,
) -> Generator[str, None, None]:
    """Run the ReAct agent loop.

    This is a generator that yields status updates for the Gradio UI,
    then yields the final comprehensive output at the end.

    Args:
        user_message: The user's natural language input.
        history: Gradio chat history (list of [user, assistant] pairs).
        max_iterations: Maximum tool calls before forced termination.

    Yields:
        Status updates (str) during the loop, then the final output.
    """
    # Initialize three-tier memory
    data_dir = os.environ.get("AGENT_MEMORY_DIR", os.path.expanduser("~/.agent_memory"))
    memory = AgentMemory(data_dir=data_dir, max_history=20)
    # Convert Gradio history to messages
    for pair in history:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            if pair[0]:
                memory.add_user_message(pair[0])
            if pair[1]:
                memory.add_assistant_message(pair[1])

    memory.add_user_message(user_message)

    # Extract explicit long-term preferences / rule cancellations from the
    # current message into Tier-3 SemanticMemory (S3/S8 memory consistency).
    # Whitelist-based and non-fatal: must never break the agent loop.
    try:
        apply_memory_updates(memory, user_message)
    except Exception:
        pass  # non-fatal by design

    # ── Intent routing: trading vs general conversation ────────
    if not is_trading_intent(user_message):
        # General conversation — personality-driven direct response
        yield from _handle_general_conversation(user_message, memory)
        return

    state = AgentState(
        user_goal=user_message,
        memory=memory,
        max_iterations=max_iterations,
        rl_feedback=RLFeedbackLoop(),
    )

    # Pre-fetch market context for better reasoning
    yield "🔄 正在初始化 Agent，获取市场数据..."
    try:
        market = _tool_get_market_data({"pair": "BTC/USDT"})
        if market.get("last_price", 0) > 0:
            state.market_context = (
                f"BTC/USDT = ${market['last_price']:,.2f}, "
                f"24h change: {market.get('change_pct', 0):+.1f}%, "
                f"24h volume: {market.get('volume_24h', 0):,.0f}"
            )
    except Exception:
        state.market_context = "Market data unavailable (API not running)."

    # ── Agent Loop ─────────────────────────────────────────────────

    for iteration in range(max_iterations):
        state.iteration = iteration

        # Build prompts
        system_prompt = _format_system_prompt(state)
        user_prompt = _build_agent_prompt(state)

        # Call LLM
        llm_output = call_vllm(system_prompt, user_prompt, temperature=0.3)

        # Parse response
        thought, action = parse_action(llm_output)

        if action is None:
            # LLM didn't produce a valid action — treat as final answer
            yield f"💭 {thought[:200]}..."
            yield llm_output
            return

        state.thoughts.append(thought)
        memory.add_thought(thought)

        # Check for final answer
        if action.get("tool") == "final_answer":
            yield f"✅ {thought[:200]}..."
            final_text = action.get("answer", thought)
            # Consolidate episodic → semantic memory
            memory.consolidate()
            # RL: Consolidate reward feedback → semantic memory
            if state.rl_feedback:
                state.rl_feedback.consolidate_to_memory(memory.semantic)
            # Enrich with structured data if available
            enriched = _enrich_final_output(final_text, state)
            yield enriched
            return

        tool_name = action.get("tool", "unknown")
        yield f"💭 Thought: {thought[:300]}\n\n🔧 Calling tool: **{tool_name}**..."

        # Execute tool
        result = execute_tool(action, state)

        # Log to memory
        memory.add_tool_call(tool_name, action, result)

        # Brief status update
        if result.get("success") is False:
            yield f"❌ {tool_name} failed: {result.get('error', 'Unknown error')}"
        else:
            summary = _summarize_tool_result(tool_name, result)
            yield f"✅ {tool_name} → {summary}"

            # RL: Record strategy + reward after backtest
            if tool_name == "run_backtest" and state.strategy_dsl and state.rl_feedback:
                record = state.rl_feedback.record_strategy(
                    dsl=state.strategy_dsl,
                    metrics=result,
                    user_request=user_message,
                )
                yield (
                    f"🎯 RL Reward: {record.reward.total:+.2f} "
                    f"(Grade: {record.reward.grade}) — {record.reward.feedback}"
                )

    # Max iterations reached
    yield f"⚠️ 达到最大推理轮数 ({max_iterations})，输出当前结果..."
    memory.consolidate()
    # RL: Consolidate reward feedback → semantic memory
    if state.rl_feedback:
        state.rl_feedback.consolidate_to_memory(memory.semantic)
    yield _enrich_final_output(
        "Agent reached maximum iterations. Here is what was accomplished:\n"
        + "\n".join(f"- {t}" for t in state.thoughts),
        state,
    )


# ── Helpers ─────────────────────────────────────────────────────────


def _summarize_tool_result(tool_name: str, result: dict) -> str:
    """One-line summary of a tool result for the UI."""
    if tool_name == "get_market_data":
        return f"BTC/USDT = ${result.get('last_price', 0):,.2f}"
    elif tool_name == "generate_strategy_dsl":
        return f"Strategy: {result.get('strategy_name', 'Unknown')}"
    elif tool_name == "validate_dsl":
        return f"Valid={result.get('is_valid')}, Errors={result.get('errors', [])}"
    elif tool_name == "run_backtest":
        return (
            f"Return={result.get('total_return', 0):.2%}, "
            f"Sharpe={result.get('sharpe_ratio', 0):.2f}, "
            f"MaxDD={result.get('max_drawdown', 0):.2%}"
        )
    elif tool_name == "walk_forward_analysis":
        return f"Robust={result.get('is_robust')}, Overfit={result.get('overfitting_score', 0):+.2%}"
    elif tool_name == "paper_trade":
        return f"Order: {result.get('action', '?')}, Pair={result.get('pair', '?')}"
    elif tool_name == "retrieve_knowledge":
        ctx = result.get("context", "")
        return f"Retrieved {len(ctx)} chars of knowledge"
    return str(result)[:200]


def _enrich_final_output(text: str, state: AgentState) -> str:
    """Enrich the LLM's final answer with structured data.

    If the agent generated a strategy and ran a backtest, append
    the structured metrics and DSL for the user.
    """
    import yaml as _yaml

    parts: list[str] = [text]

    # Append backtest metrics if available
    if state.backtest_result:
        bt = state.backtest_result
        metrics_table = f"""

---

### 📊 回测指标

| Metric | Value |
|--------|-------|
| Total Trades | {bt.get('total_trades', 0)} |
| Win Rate | {bt.get('win_rate', 0):.1%} |
| Total Return | {bt.get('total_return', 0):.2%} |
| Buy & Hold Return | {bt.get('benchmark_return', 0):.2%} |
| Alpha | {bt.get('alpha', 0):+.2%} |
| Max Drawdown | {bt.get('max_drawdown', 0):.2%} |
| Sharpe Ratio | {bt.get('sharpe_ratio', 0):.2f} |
| Sortino Ratio | {bt.get('sortino_ratio', 0):.2f} |
| Final Balance | ${bt.get('final_balance', 0):,.2f} |
"""
        parts.append(metrics_table)

    # Append DSL if available
    if state.strategy_dsl:
        dsl_yaml = _yaml.dump(state.strategy_dsl, default_flow_style=False, sort_keys=False, allow_unicode=True)
        parts.append(f"""

---

### 📝 策略DSL (YAML)

```yaml
{dsl_yaml}
```
""")

    # Append agent trace
    if state.thoughts:
        trace = "\n".join(f"  {i+1}. {t[:100]}..." if len(t) > 100 else f"  {i+1}. {t}"
                          for i, t in enumerate(state.thoughts))
        parts.append(f"""

---

### 🧠 Agent 推理轨迹

{trace}

### 🛠️ 工具调用记录

{state.memory.summarize_for_prompt() if state.memory else 'N/A'}

---

### 🤖 技术栈
- **Agent架构**: ReAct (Reasoning + Acting) Loop on AMD ROCm GPU
- **LLM推理**: Qwen2.5-7B (LoRA微调) via vLLM on AMD ROCm
- **记忆管理**: 对话历史 + 工具调用日志 + 策略/回测历史
- **工具调用**: {len(TOOL_REGISTRY)}个工具 (行情/策略/校验/回测/Walk-Forward/模拟交易/知识库)
""")

    return "\n".join(parts)
