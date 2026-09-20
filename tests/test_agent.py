"""Tests for the ReAct Agent module.

Tests cover:
- ConversationMemory: message history, tool call logging, prompt summarization
- Tool dispatch: correct routing of tool names to executor functions
- Action parser: extracting Thought/Action/Final Answer from LLM output
- AgentState: state transitions and memory integration
- Agent loop: mocked LLM responses to verify end-to-end flow
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from src.agent.memory import (
    AgentMemory,
    WorkingMemory,
    EpisodicMemory,
    SemanticMemory,
    _summarize_result,
)
from src.agent.tools import (
    TOOL_REGISTRY,
    execute_tool,
    parse_action,
    extract_yaml,
)
from src.agent.core import AgentState, _enrich_final_output, _summarize_tool_result
from src.agent.prompts import REACT_SYSTEM_PROMPT, TOOL_DESCRIPTIONS


# ── WorkingMemory tests (Tier 1) ────────────────────────────────────


class TestWorkingMemory:
    def test_add_and_retrieve_messages(self):
        wm = WorkingMemory()
        wm.add_user_message("Hello")
        wm.add_assistant_message("Hi there")
        assert len(wm.messages) == 2
        assert wm.messages[0]["role"] == "user"
        assert wm.messages[1]["role"] == "assistant"

    def test_context_window_limits(self):
        wm = WorkingMemory(max_messages=6)
        for i in range(10):
            wm.add_user_message(f"msg {i}")
            wm.add_assistant_message(f"reply {i}")
        ctx = wm.get_context_window(n=3)
        assert len(ctx) <= 6

    def test_tool_call_logging(self):
        wm = WorkingMemory()
        wm.add_tool_call("run_backtest", {"days": 180}, {"total_return": 0.15})
        assert len(wm.tool_calls) == 1
        tc = wm.tool_calls[0]
        assert tc["tool"] == "run_backtest"
        assert "return" in tc["result_summary"]

    def test_format_for_prompt_empty(self):
        wm = WorkingMemory()
        assert "No recent actions" in wm.format_for_prompt()

    def test_format_for_prompt_with_data(self):
        wm = WorkingMemory()
        wm.add_tool_call("get_market_data", {}, {"last_price": 65000})
        formatted = wm.format_for_prompt()
        assert "get_market_data" in formatted

    def test_max_messages_trim(self):
        wm = WorkingMemory(max_messages=4)
        for i in range(20):
            wm.add_user_message(f"msg {i}")
        assert len(wm.messages) <= 4


# ── EpisodicMemory tests (Tier 2) ──────────────────────────────────


class TestEpisodicMemory:
    def test_add_strategy(self):
        em = EpisodicMemory()
        dsl = {"strategy": {"name": "TestStrategy", "market": {"pair": "BTC/USDT", "timeframe": "1h"}}}
        em.add_strategy(dsl)
        assert em.latest_strategy is not None
        assert em.latest_strategy["strategy"]["name"] == "TestStrategy"
        assert len(em.strategies) == 1
        assert em.strategies[0]["pair"] == "BTC/USDT"

    def test_add_backtest_result(self):
        em = EpisodicMemory()
        result = {"total_return": 0.12, "sharpe_ratio": 1.5}
        em.add_backtest_result(result)
        assert em.latest_backtest is not None
        assert em.latest_backtest["total_return"] == 0.12

    def test_all_strategy_names(self):
        em = EpisodicMemory()
        em.add_strategy({"strategy": {"name": "A", "market": {}}})
        em.add_strategy({"strategy": {"name": "B", "market": {}}})
        assert em.all_strategy_names == ["A", "B"]

    def test_format_for_prompt_empty(self):
        em = EpisodicMemory()
        assert "No strategies" in em.format_for_prompt()

    def test_format_for_prompt_with_data(self):
        em = EpisodicMemory()
        em.add_strategy({"strategy": {"name": "EMA Cross", "market": {"pair": "BTC/USDT", "timeframe": "1h"}}})
        em.add_backtest_result({"total_return": 0.1, "sharpe_ratio": 1.2, "max_drawdown": -0.05})
        formatted = em.format_for_prompt()
        assert "EMA Cross" in formatted
        assert "BTC/USDT" in formatted

    def test_add_user_request_and_thought(self):
        em = EpisodicMemory()
        em.add_user_request("Create EMA strategy")
        em.add_thought("I should check market data first")
        assert len(em.user_requests) == 1
        assert len(em.agent_thoughts) == 1

    def test_persistence_roundtrip(self, tmp_path):
        f = str(tmp_path / "episode.json")
        em = EpisodicMemory()
        em.set_persistence(f)
        em.add_strategy({"strategy": {"name": "Persist", "market": {}}})
        em.add_backtest_result({"total_return": 0.15})

        # Create new instance, load from file
        em2 = EpisodicMemory()
        em2.set_persistence(f)
        assert len(em2.strategies) == 1
        assert em2.strategies[0]["name"] == "Persist"
        assert len(em2.backtest_results) == 1


# ── SemanticMemory tests (Tier 3) ──────────────────────────────────


class TestSemanticMemory:
    def test_initial_preferences(self):
        sm = SemanticMemory()
        assert sm.user_preferences["risk_tolerance"] == "moderate"
        assert sm.user_preferences["preferred_indicators"] == []

    def test_update_preferences(self):
        sm = SemanticMemory()
        sm.update_preferences("risk_tolerance", "aggressive")
        assert sm.user_preferences["risk_tolerance"] == "aggressive"

    def test_update_preferences_list_merge(self):
        sm = SemanticMemory()
        sm.update_preferences("preferred_indicators", ["EMA"])
        sm.update_preferences("preferred_indicators", ["RSI"])
        assert "EMA" in sm.user_preferences["preferred_indicators"]
        assert "RSI" in sm.user_preferences["preferred_indicators"]

    def test_learn_from_session(self):
        sm = SemanticMemory()
        em = EpisodicMemory()
        em.add_strategy({"strategy": {"name": "Test", "market": {"pair": "BTC/USDT", "timeframe": "1h"}}})
        em.add_backtest_result({"total_return": 0.15, "sharpe_ratio": 1.8, "max_drawdown": -0.05})
        sm.learn_from_session(em)
        assert len(sm.strategy_stats) == 1
        assert sm.strategy_stats[0]["total_return"] == 0.15
        assert "BTC/USDT" in sm.user_preferences["preferred_pairs"]
        assert "1h" in sm.user_preferences["preferred_timeframes"]

    def test_experience_rule_extraction_good(self):
        sm = SemanticMemory()
        em = EpisodicMemory()
        em.add_backtest_result({"total_return": 0.20, "sharpe_ratio": 2.5, "max_drawdown": -0.05})
        sm.learn_from_session(em)
        assert any("performed well" in r for r in sm.experience_rules)

    def test_experience_rule_extraction_bad(self):
        sm = SemanticMemory()
        em = EpisodicMemory()
        em.add_backtest_result({"total_return": -0.10, "sharpe_ratio": -0.5, "max_drawdown": -0.15})
        sm.learn_from_session(em)
        assert any("performed poorly" in r for r in sm.experience_rules)

    def test_get_strategy_summary_empty(self):
        sm = SemanticMemory()
        assert "No historical" in sm.get_strategy_summary()

    def test_get_strategy_summary_with_data(self):
        sm = SemanticMemory()
        sm.strategy_stats = [
            {"total_return": 0.1, "sharpe": 1.2, "pair": "BTC/USDT"},
            {"total_return": -0.05, "sharpe": -0.3, "pair": "ETH/USDT"},
        ]
        summary = sm.get_strategy_summary()
        assert "2 strategies" in summary
        assert "1/2 profitable" in summary

    def test_persistence_roundtrip(self, tmp_path):
        f = str(tmp_path / "semantic.json")
        sm = SemanticMemory()
        sm.set_persistence(f)
        sm.update_preferences("risk_tolerance", "conservative")
        sm.experience_rules.append("Test rule")
        sm._persist()  # Explicitly persist after direct list mutation

        sm2 = SemanticMemory()
        sm2.set_persistence(f)
        assert sm2.user_preferences["risk_tolerance"] == "conservative"
        assert "Test rule" in sm2.experience_rules

    def test_format_for_prompt_empty(self):
        sm = SemanticMemory()
        assert "No long-term memory" in sm.format_for_prompt()

    def test_format_for_prompt_with_data(self):
        sm = SemanticMemory()
        sm.update_preferences("preferred_pairs", ["BTC/USDT"])
        sm.update_preferences("risk_tolerance", "aggressive")
        sm.strategy_stats = [{"total_return": 0.1, "sharpe": 1.2, "pair": "BTC/USDT"}]
        formatted = sm.format_for_prompt()
        assert "BTC/USDT" in formatted
        assert "aggressive" in formatted
        assert "1 strategies" in formatted


# ── AgentMemory facade tests ────────────────────────────────────────


class TestAgentMemory:
    def test_initialization(self):
        am = AgentMemory()
        assert am.working is not None
        assert am.episodic is not None
        assert am.semantic is not None

    def test_add_user_message_delegates(self):
        am = AgentMemory()
        am.add_user_message("Hello")
        assert len(am.working.messages) == 1
        assert len(am.episodic.user_requests) == 1

    def test_add_strategy_delegates(self):
        am = AgentMemory()
        am.add_strategy({"strategy": {"name": "Test", "market": {}}})
        assert am.latest_strategy is not None
        assert am.latest_strategy["strategy"]["name"] == "Test"

    def test_add_tool_call_delegates(self):
        am = AgentMemory()
        am.add_tool_call("run_backtest", {}, {"total_return": 0.1})
        assert len(am.working.tool_calls) == 1

    def test_consolidate(self):
        am = AgentMemory()
        am.add_strategy({"strategy": {"name": "Test", "market": {"pair": "BTC/USDT", "timeframe": "1h"}}})
        am.add_backtest_result({"total_return": 0.15, "sharpe_ratio": 1.8, "max_drawdown": -0.05})
        am.consolidate()
        assert len(am.semantic.strategy_stats) == 1
        assert "BTC/USDT" in am.semantic.user_preferences["preferred_pairs"]

    def test_summarize_for_prompt_all_tiers(self):
        am = AgentMemory()
        am.add_tool_call("get_market_data", {}, {"last_price": 65000})
        am.add_strategy({"strategy": {"name": "EMA", "market": {"pair": "BTC/USDT", "timeframe": "1h"}}})
        am.add_backtest_result({"total_return": 0.1, "sharpe_ratio": 1.2, "max_drawdown": -0.05})
        am.consolidate()
        summary = am.summarize_for_prompt()
        # Should contain data from all tiers
        assert "EMA" in summary or "BTC/USDT" in summary

    def test_summarize_for_prompt_empty(self):
        am = AgentMemory()
        assert "No prior memory" in am.summarize_for_prompt()

    def test_format_conversation_history(self):
        am = AgentMemory()
        am.add_user_message("Create a strategy")
        am.add_assistant_message("Sure, what kind?")
        hist = am.format_conversation_history(n=3)
        assert "Create a strategy" in hist
        assert "Sure" in hist

    def test_backward_compatible_properties(self):
        am = AgentMemory()
        am.add_user_message("msg")
        assert len(am.messages) == 1
        am.add_tool_call("test", {}, {"ok": True})
        assert len(am.tool_calls) == 1

    def test_persistence_with_data_dir(self, tmp_path):
        am = AgentMemory(data_dir=str(tmp_path), session_id="test123")
        am.add_strategy({"strategy": {"name": "Persist", "market": {}}})
        am.add_backtest_result({"total_return": 0.1})
        am.consolidate()

        # New agent loads semantic memory
        am2 = AgentMemory(data_dir=str(tmp_path), session_id="test456")
        assert len(am2.semantic.strategy_stats) == 1


# ── Tool registry tests ─────────────────────────────────────────────


class TestToolRegistry:
    def test_all_tools_have_required_fields(self):
        for tool in TOOL_REGISTRY:
            assert "name" in tool
            assert "description" in tool
            assert "usage" in tool

    def test_eight_tools_registered(self):
        tool_names = [t["name"] for t in TOOL_REGISTRY]
        assert len(tool_names) == 8
        assert "get_market_data" in tool_names
        assert "generate_strategy_dsl" in tool_names
        assert "run_backtest" in tool_names
        assert "final_answer" in tool_names

    def test_tool_descriptions_in_prompt(self):
        assert "get_market_data" in TOOL_DESCRIPTIONS
        assert "run_backtest" in TOOL_DESCRIPTIONS
        assert "final_answer" in TOOL_DESCRIPTIONS


# ── Action parser tests ─────────────────────────────────────────────


class TestParseAction:
    def test_parse_thought_and_action(self):
        text = """Thought: I should fetch market data first.
Action: ```json
{"tool": "get_market_data", "pair": "BTC/USDT"}
```"""
        thought, action = parse_action(text)
        assert "fetch market data" in thought
        assert action is not None
        assert action["tool"] == "get_market_data"
        assert action["pair"] == "BTC/USDT"

    def test_parse_final_answer(self):
        text = """Thought: The strategy looks good.
Final Answer: The EMA crossover strategy performed well with 15% return."""
        thought, action = parse_action(text)
        assert "strategy looks good" in thought
        assert action is not None
        assert action["tool"] == "final_answer"
        assert "15% return" in action["answer"]

    def test_parse_bare_json_action(self):
        text = """Thought: Let me validate the DSL.
Action: {"tool": "validate_dsl", "dsl": {"strategy": {}}}"""
        thought, action = parse_action(text)
        assert action is not None
        assert action["tool"] == "validate_dsl"

    def test_parse_no_action_returns_none(self):
        text = "I'm not sure what to do."
        thought, action = parse_action(text)
        assert action is None

    def test_parse_action_with_multiline_thought(self):
        text = """Thought: Let me think about this carefully.
The user wants an EMA crossover strategy.
I should first check the market data, then generate the strategy.

Action: ```json
{"tool": "get_market_data", "pair": "ETH/USDT"}
```"""
        thought, action = parse_action(text)
        assert "EMA crossover" in thought
        assert action["pair"] == "ETH/USDT"


# ── Tool executor tests ─────────────────────────────────────────────


class TestExecuteTool:
    def test_unknown_tool(self):
        state = AgentState()
        result = execute_tool({"tool": "nonexistent"}, state)
        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    def test_final_answer_tool(self):
        state = AgentState()
        result = execute_tool({"tool": "final_answer"}, state)
        assert result["success"] is True

    def test_validate_dsl_valid(self):
        state = AgentState()
        valid_dsl = {
            "strategy": {
                "name": "TestEMA",
                "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
                "indicators": [
                    {"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}},
                    {"name": "ema_slow", "type": "EMA", "params": {"period": 50, "field": "close"}},
                ],
                "entry": {"long": "ema_fast > ema_slow", "short": None},
                "exit": {"long": "ema_fast < ema_slow", "short": None},
                "risk": {"stop_loss": -0.03, "max_open_trades": 3, "stake_amount": 0.1},
            }
        }
        result = execute_tool({"tool": "validate_dsl", "dsl": valid_dsl}, state)
        assert result["is_valid"] is True

    def test_validate_dsl_invalid(self):
        state = AgentState()
        invalid_dsl = {
            "strategy": {
                "name": "Bad",
                "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
                "indicators": [],
                "entry": {"long": "ema_fast > ema_slow", "short": None},
                "exit": {"long": "ema_fast < ema_slow", "short": None},
                "risk": {"stop_loss": 0.03},  # positive stop_loss = invalid
            }
        }
        result = execute_tool({"tool": "validate_dsl", "dsl": invalid_dsl}, state)
        assert result["is_valid"] is False

    def test_retrieve_knowledge(self):
        state = AgentState()
        result = execute_tool(
            {"tool": "retrieve_knowledge", "query": "RSI oversold"},
            state,
        )
        assert result["success"] is True
        assert len(result["context"]) > 0

    def test_validate_dsl_missing_param(self):
        state = AgentState()
        result = execute_tool({"tool": "validate_dsl"}, state)
        assert result["success"] is False
        assert "dsl" in result["error"]


# ── AgentState tests ────────────────────────────────────────────────


class TestAgentState:
    def test_state_initialization(self):
        state = AgentState(user_goal="Test strategy")
        assert state.user_goal == "Test strategy"
        assert state.strategy_dsl is None
        assert state.backtest_result is None
        assert state.iteration == 0
        assert state.max_iterations == 8

    def test_state_with_memory(self):
        mem = AgentMemory()
        state = AgentState(user_goal="Test", memory=mem)
        assert state.memory is mem

    def test_thoughts_accumulate(self):
        state = AgentState()
        state.thoughts.append("First thought")
        state.thoughts.append("Second thought")
        assert len(state.thoughts) == 2


# ── Summarize helpers tests ─────────────────────────────────────────


class TestSummarizeHelpers:
    def test_summarize_backtest_result(self):
        result = {"total_return": 0.15, "sharpe_ratio": 1.5, "max_drawdown": -0.08, "total_trades": 10}
        summary = _summarize_tool_result("run_backtest", result)
        assert "15.00%" in summary
        assert "1.50" in summary

    def test_summarize_market_data(self):
        result = {"last_price": 65000}
        summary = _summarize_tool_result("get_market_data", result)
        assert "65,000" in summary

    def test_summarize_validation(self):
        result = {"is_valid": True, "errors": []}
        summary = _summarize_tool_result("validate_dsl", result)
        assert "True" in summary

    def test_summarize_result_backtest(self):
        result = {"total_return": 0.12, "sharpe_ratio": 1.3, "max_drawdown": -0.05, "total_trades": 8}
        summary = _summarize_result(result)
        assert "12.00%" in summary
        assert "1.30" in summary


# ── Enrich final output tests ───────────────────────────────────────


class TestEnrichFinalOutput:
    def test_enrich_with_backtest(self):
        state = AgentState()
        state.backtest_result = {
            "total_return": 0.15,
            "sharpe_ratio": 1.5,
            "max_drawdown": -0.08,
            "total_trades": 10,
            "win_rate": 0.6,
            "benchmark_return": 0.10,
            "alpha": 0.05,
            "sortino_ratio": 1.8,
            "final_balance": 11500,
        }
        output = _enrich_final_output("Strategy performed well.", state)
        assert "回测指标" in output
        assert "15.00%" in output

    def test_enrich_with_dsl(self):
        state = AgentState()
        state.strategy_dsl = {
            "strategy": {
                "name": "TestStrategy",
                "market": {"pair": "BTC/USDT"},
            }
        }
        output = _enrich_final_output("Here is the strategy.", state)
        assert "策略DSL" in output
        assert "TestStrategy" in output

    def test_enrich_with_agent_trace(self):
        state = AgentState()
        state.thoughts = ["First thought", "Second thought"]
        output = _enrich_final_output("Done.", state)
        assert "Agent 推理轨迹" in output
        assert "First thought" in output

    def test_enrich_plain_text(self):
        state = AgentState()
        output = _enrich_final_output("Just a response.", state)
        assert "Just a response." in output


# ── YAML extraction tests ────────────────────────────────────────────


class TestExtractYaml:
    def test_fenced_yaml(self):
        text = 'Here is the strategy:\n```yaml\nstrategy:\n  name: Test\n```\n'
        result = extract_yaml(text)
        assert result is not None
        assert result["strategy"]["name"] == "Test"

    def test_bare_yaml(self):
        text = 'strategy:\n  name: Bare\n  market:\n    pair: BTC/USDT\n'
        result = extract_yaml(text)
        assert result is not None
        assert result["strategy"]["name"] == "Bare"

    def test_cot_then_yaml(self):
        text = """Let me think about this.
I'll create an EMA crossover.

strategy:
  name: EMA Cross
  market:
    pair: BTC/USDT
"""
        result = extract_yaml(text)
        assert result is not None
        assert result["strategy"]["name"] == "EMA Cross"

    def test_invalid_yaml(self):
        text = "This is just plain text without any YAML."
        result = extract_yaml(text)
        assert result is None


# ── System prompt tests ────────────────────────────────────────────


class TestSystemPrompt:
    def test_prompt_has_placeholders(self):
        assert "{tool_descriptions}" in REACT_SYSTEM_PROMPT
        assert "{max_iterations}" in REACT_SYSTEM_PROMPT
        assert "{market_context}" in REACT_SYSTEM_PROMPT
        assert "{rag_context}" in REACT_SYSTEM_PROMPT
        assert "{action_history}" in REACT_SYSTEM_PROMPT
        assert "{conversation_history}" in REACT_SYSTEM_PROMPT
        assert "{semantic_memory}" in REACT_SYSTEM_PROMPT

    def test_prompt_mentions_react(self):
        assert "Thought" in REACT_SYSTEM_PROMPT
        assert "Action" in REACT_SYSTEM_PROMPT
        assert "Final Answer" in REACT_SYSTEM_PROMPT

    def test_prompt_lists_all_tools(self):
        for tool in TOOL_REGISTRY:
            assert tool["name"] in TOOL_DESCRIPTIONS


# ── Intent classification tests ────────────────────────────────────


class TestIntentClassification:
    def test_trading_keywords_detected(self):
        from src.agent.personality import is_trading_intent
        assert is_trading_intent("帮我做一个EMA突破策略") is True
        assert is_trading_intent("BTC现在什么行情？") is True
        assert is_trading_intent("RSI超卖策略，止损3%") is True
        assert is_trading_intent("回测一下这个MACD策略") is True

    def test_general_conversation_detected(self):
        from src.agent.personality import is_trading_intent
        assert is_trading_intent("你好") is False
        assert is_trading_intent("今天天气怎么样") is False
        assert is_trading_intent("讲个笑话") is False
        assert is_trading_intent("你是谁？") is False
        assert is_trading_intent("谢谢！") is False

    def test_empty_message(self):
        from src.agent.personality import is_trading_intent
        assert is_trading_intent("") is False
        assert is_trading_intent("   ") is False

    def test_english_trading_keywords(self):
        from src.agent.personality import is_trading_intent
        assert is_trading_intent("Create a backtest for EMA crossover") is True
        assert is_trading_intent("What's the BTC price?") is True
        assert is_trading_intent("Set stop loss to 3%") is True

    def test_english_general_conversation(self):
        from src.agent.personality import is_trading_intent
        assert is_trading_intent("Hello there!") is False
        assert is_trading_intent("How are you?") is False
        assert is_trading_intent("Tell me a joke") is False

    def test_mixed_language(self):
        from src.agent.personality import is_trading_intent
        assert is_trading_intent("今天BTC的行情怎么样") is True
        assert is_trading_intent("帮我看看ETH的K线") is True
        assert is_trading_intent("周末去哪玩") is False

    def test_dsl_pattern_detected(self):
        from src.agent.personality import is_trading_intent
        assert is_trading_intent("strategy: name=Test, indicators: EMA") is True
        assert is_trading_intent("stop_loss: -0.03") is True


# ── Personality prompt tests ──────────────────────────────────────


class TestPersonalityPrompt:
    def test_build_prompt_has_name(self):
        from src.agent.personality import build_personality_prompt
        prompt = build_personality_prompt()
        assert "小R" in prompt

    def test_build_prompt_has_memory_placeholders(self):
        from src.agent.personality import build_personality_prompt
        prompt = build_personality_prompt(
            semantic_memory="用户偏好: BTC/USDT",
            conversation_history="用户: 你好\n助手: 你好呀",
        )
        assert "BTC/USDT" in prompt
        assert "你好" in prompt

    def test_build_prompt_defaults(self):
        from src.agent.personality import build_personality_prompt
        prompt = build_personality_prompt()
        assert "还没有积累用户偏好" in prompt
        assert "第一轮对话" in prompt

    def test_prompt_no_ai_disclaimer(self):
        from src.agent.personality import PERSONALITY_PROMPT
        # The prompt should explicitly forbid AI disclaimers (negative instruction)
        assert "不要" in PERSONALITY_PROMPT or "绝对不要" in PERSONALITY_PROMPT
        # Should not have "As an AI" style English disclaimers
        assert "As an AI" not in PERSONALITY_PROMPT

    def test_prompt_has_personality_traits(self):
        from src.agent.personality import PERSONALITY_PROMPT
        assert "幽默" in PERSONALITY_PROMPT or "温度" in PERSONALITY_PROMPT
        assert "ROCm" in PERSONALITY_PROMPT
