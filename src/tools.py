"""Tool registry and executor for the ReAct agent.

Each tool wraps an existing API call (from chat_app.py or src/api.py),
providing a unified interface for the agent loop.

Tools are dispatched by name — the LLM chooses which tool to call,
and this module executes it and returns the result.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
import yaml

# ── Configuration (same as chat_app.py) ─────────────────────────────

VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
BACKTEST_API_URL = os.environ.get("BACKTEST_API_URL", "http://localhost:8080")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen-trader-merged")
CN_MARKET_MODE = os.environ.get("CN_MARKET_MODE", "1").lower() in {"1", "true", "yes"}

# ── Tool registry ───────────────────────────────────────────────────

TOOL_REGISTRY: list[dict[str, str]] = [
    {
        "name": "get_market_data",
        "description": "获取交易对实时行情（价格、24h涨跌、成交量）",
        "usage": '{"tool": "get_market_data", "pair": "BTC/USDT"}',
    },
    {
        "name": "generate_strategy_dsl",
        "description": "根据自然语言描述生成策略DSL（YAML格式）",
        "usage": '{"tool": "generate_strategy_dsl", "description": "EMA突破策略，止损3%"}',
    },
    {
        "name": "validate_dsl",
        "description": "校验策略DSL的结构和语义正确性",
        "usage": '{"tool": "validate_dsl", "dsl": <strategy_dict>}',
    },
    {
        "name": "run_backtest",
        "description": "用历史数据回测策略，返回收益率、夏普比率、最大回撤等指标",
        "usage": '{"tool": "run_backtest", "dsl": <strategy_dict>, "days": 180}',
    },
    {
        "name": "walk_forward_analysis",
        "description": "Walk-Forward分析，检测策略过拟合",
        "usage": '{"tool": "walk_forward_analysis", "dsl": <strategy_dict>}',
    },
    {
        "name": "paper_trade",
        "description": "在Binance Testnet模拟下单（DRY_RUN默认安全模式）",
        "usage": '{"tool": "paper_trade", "action": "buy", "pair": "BTC/USDT", "amount": 0.001}',
    },
    {
        "name": "retrieve_knowledge",
        "description": "从交易知识库检索技术指标、策略模式、风控规则",
        "usage": '{"tool": "retrieve_knowledge", "query": "RSI超卖策略"}',
    },
    {
        "name": "final_answer",
        "description": "任务完成，输出最终分析报告",
        "usage": '{"tool": "final_answer"}',
    },
]

# ── LLM client (sync, for agent loop) ──────────────────────────────


def call_vllm(system_prompt: str, user_message: str, temperature: float = 0.3) -> str:
    """Call vLLM's OpenAI-compatible chat API (synchronous)."""
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{VLLM_BASE_URL}/chat/completions",
                json={
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": temperature,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM Error] {e}"


# ── YAML extraction (reused from chat_app.py) ────────────────────────


def extract_yaml(text: str) -> dict | None:
    """Extract YAML from LLM response — handles fenced, bare, and CoT-prefixed."""
    yaml_match = re.search(r"```(?:ya?ml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if yaml_match:
        try:
            parsed = yaml.safe_load(yaml_match.group(1))
            if isinstance(parsed, dict) and "strategy" in parsed:
                return parsed
        except yaml.YAMLError:
            pass

    strategy_match = re.search(r"(^|\n)(strategy:\s*\n.*)", text, re.DOTALL)
    if strategy_match:
        try:
            parsed = yaml.safe_load(strategy_match.group(2))
            if isinstance(parsed, dict) and "strategy" in parsed:
                return parsed
        except yaml.YAMLError:
            pass

    try:
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict) and "strategy" in parsed:
            return parsed
    except yaml.YAMLError:
        pass

    return None


# ── Tool executors ──────────────────────────────────────────────────


def _tool_get_market_data(params: dict) -> dict:
    """Fetch current market data via the backtest API."""
    pair = params.get("pair", "BTC/USDT")
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(f"{BACKTEST_API_URL}/api/market/summary", params={"pair": pair})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def _tool_generate_strategy_dsl(params: dict, state: Any) -> dict:
    """Generate a strategy DSL via vLLM."""
    from .prompts import DSL_GENERATION_PROMPT
    from ..knowledge_base.retriever import retrieve_knowledge

    description = params.get("description", "")
    if not description:
        return {"success": False, "error": "Missing 'description' parameter"}

    # Inject market context if available
    context_parts: list[str] = []
    if state.market_context:
        context_parts.append(f"[Market Context]\n{state.market_context}")

    rag_ctx = retrieve_knowledge(description, max_results=3)
    if rag_ctx:
        context_parts.append(f"[Trading Knowledge]\n{rag_ctx}")

    prompt = description
    if context_parts:
        prompt += "\n\n" + "\n\n".join(context_parts)
        prompt += "\n\nUse this knowledge when setting strategy parameters."

    if CN_MARKET_MODE:
        from ..cn_pipeline import CN_MARKET_DSL_PROMPT, process_cn_model_output
        generation_prompt = CN_MARKET_DSL_PROMPT
    else:
        generation_prompt = DSL_GENERATION_PROMPT

    dsl_text = call_vllm(generation_prompt, prompt, temperature=0.2)
    cn_result = process_cn_model_output(dsl_text) if CN_MARKET_MODE else None
    dsl = cn_result["canonicalized"] if cn_result else extract_yaml(dsl_text)

    if dsl is None:
        return {
            "success": False,
            "error": "LLM failed to generate valid domestic-market DSL" if CN_MARKET_MODE else "LLM failed to generate valid YAML",
            "raw_output": dsl_text[:2000],
            "repairs": (cn_result or {}).get("extract_repairs", []) + (cn_result or {}).get("canon_repairs", []),
        }

    # Canonicalize
    try:
        from ..dsl.canonicalizer import canonicalize_dsl
        if not CN_MARKET_MODE:
            dsl = canonicalize_dsl(dsl)
    except Exception:
        pass

    state.strategy_dsl = dsl
    if state.memory:
        state.memory.add_strategy(dsl)

    return {
        "success": True,
        "strategy_name": dsl.get("strategy", {}).get("name", "Unknown"),
        "dsl": dsl,
        "raw_output": dsl_text,
        "repairs": (cn_result or {}).get("extract_repairs", []) + (cn_result or {}).get("canon_repairs", []),
    }


def _tool_validate_dsl(params: dict) -> dict:
    """Validate a strategy DSL."""
    dsl = params.get("dsl")
    if not dsl:
        return {"success": False, "error": "Missing 'dsl' parameter"}

    try:
        from ..dsl.validator import validate_dsl
        is_valid, errors = validate_dsl(dsl)
        return {"is_valid": is_valid, "errors": errors}
    except Exception as e:
        return {"is_valid": False, "errors": [str(e)]}


def _tool_run_backtest(params: dict, state: Any) -> dict:
    """Run a backtest via the API."""
    dsl = params.get("dsl") or state.strategy_dsl
    if not dsl:
        return {"success": False, "error": "No strategy DSL available. Generate one first."}

    days = params.get("days", 180)

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{BACKTEST_API_URL}/api/backtest",
                json={"strategy": dsl, "days": days, "initial_balance": 10000},
            )
            resp.raise_for_status()
            result = resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

    if result.get("success"):
        metrics = result.get("metrics", {})
        state.backtest_result = metrics
        if state.memory:
            state.memory.add_backtest_result(metrics)
        return metrics
    else:
        return result


def _tool_walk_forward(params: dict, state: Any) -> dict:
    """Run walk-forward analysis."""
    dsl = params.get("dsl") or state.strategy_dsl
    if not dsl:
        return {"success": False, "error": "No strategy DSL available."}

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{BACKTEST_API_URL}/api/walkforward",
                json={"strategy": dsl, "days": 180, "initial_balance": 10000},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def _tool_paper_trade(params: dict) -> dict:
    """Execute a paper trade — always DRY_RUN from the agent loop.

    The agent cannot bypass dry_run mode. Real Testnet trades require
    manual API calls with proper authentication.
    """
    action = params.get("action", "status")
    pair = params.get("pair", "BTC/USDT")
    amount = params.get("amount", 0.001)

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{BACKTEST_API_URL}/api/paper-trade/execute",
                json={
                    "action": action,
                    "pair": pair,
                    "amount": amount,
                    "dry_run": True,  # Forced — agent cannot override
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def _tool_retrieve_knowledge(params: dict) -> dict:
    """Retrieve knowledge via multi-path retrieval (keyword + BM25 + reranking).

    Returns confidence-gated results: if no docs pass the threshold,
    has_valid_docs=false, and the reasoning agent must output neutral.
    """
    query = params.get("query", "")
    if not query:
        return {"success": False, "error": "Missing 'query' parameter"}

    try:
        from ..knowledge_base.multi_retriever import retrieve_with_confidence
        result = retrieve_with_confidence(query)
        return {
            "success": True,
            "has_valid_docs": result.has_valid_docs,
            "max_confidence_score": result.max_confidence_score,
            "reference_docs": result.reference_docs,
            "context": "\n\n".join(
                f"### {d['title']} (score={d['score']})\n{d['content']}"
                for d in result.reference_docs
            ),
        }
    except Exception as e:
        # Fallback to keyword-only retrieval
        try:
            from ..knowledge_base.retriever import retrieve_knowledge
            context = retrieve_knowledge(query, max_results=3)
            return {"success": True, "has_valid_docs": bool(context), "context": context, "reference_docs": []}
        except Exception as e2:
            return {"success": False, "error": str(e2)}


# ── Dispatcher ──────────────────────────────────────────────────────


def execute_tool(action: dict, state: Any) -> dict:
    """Execute a tool call and return the result.

    Args:
        action: Dict with "tool" key and tool-specific parameters.
        state: AgentState — provides access to strategy_dsl, backtest_result, etc.

    Returns:
        Tool result dict.
    """
    tool_name = action.get("tool", "")

    if tool_name == "get_market_data":
        return _tool_get_market_data(action)
    elif tool_name == "generate_strategy_dsl":
        return _tool_generate_strategy_dsl(action, state)
    elif tool_name == "validate_dsl":
        return _tool_validate_dsl(action)
    elif tool_name == "run_backtest":
        return _tool_run_backtest(action, state)
    elif tool_name == "walk_forward_analysis":
        return _tool_walk_forward(action, state)
    elif tool_name == "paper_trade":
        return _tool_paper_trade(action)
    elif tool_name == "retrieve_knowledge":
        return _tool_retrieve_knowledge(action)
    elif tool_name == "final_answer":
        return {"success": True, "tool": "final_answer"}
    else:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}


# ── JSON action parser ──────────────────────────────────────────────


def parse_action(llm_output: str) -> tuple[str, dict | None]:
    """Parse the LLM's response into (thought, action_dict).

    The LLM outputs either:
    - "Thought: ...\\nAction: ```json\\n{...}\\n```" → return (thought, parsed_json)
    - "Thought: ...\\nFinal Answer: ..." → return (thought, {"tool": "final_answer"})

    Returns:
        (thought_text, action_dict) — action_dict is None if parsing fails.
    """
    # Check for Final Answer
    final_match = re.search(r"Final Answer:\s*(.*)", llm_output, re.DOTALL)
    if final_match:
        thought_match = re.search(r"Thought:\s*(.*?)(?:Final Answer:|$)", llm_output, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else ""
        return thought, {"tool": "final_answer", "answer": final_match.group(1).strip()}

    # Extract Thought
    thought_match = re.search(r"Thought:\s*(.*?)(?:Action:|$)", llm_output, re.DOTALL)
    thought = thought_match.group(1).strip() if thought_match else llm_output.strip()

    # Extract Action JSON
    action_match = re.search(r"Action:\s*```(?:json)?\s*\n(.*?)\n```", llm_output, re.DOTALL)
    if action_match:
        try:
            action = json.loads(action_match.group(1))
            return thought, action
        except json.JSONDecodeError:
            pass

    # Try bare JSON after "Action:"
    action_match = re.search(r"Action:\s*(\{.*\})", llm_output, re.DOTALL)
    if action_match:
        try:
            action = json.loads(action_match.group(1))
            return thought, action
        except json.JSONDecodeError:
            pass

    # No action parsed — treat as final answer
    return thought, None
