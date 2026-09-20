"""Reasoning Agent — LoRA-powered trading intent generation.

Input:  market data + retrieval results (reference_docs)
Output: trading intent JSON (view, confidence, position_ratio, stop_loss)

IMPORTANT: This agent produces a **trading intent**, NOT an order.
The Risk Agent has veto power — execution only happens if Risk approves.

If has_valid_docs=false (no RAG support), this agent MUST output neutral.
"""

from __future__ import annotations

import json
import os
import re

import httpx

from .protocol import AgentMessage

VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen-trader-merged")

REASONING_SYSTEM_PROMPT = """\
You are a quantitative trading reasoning agent. Given market data and \
reference documents from the knowledge base, produce a trading intent.

## Strict Rules

1. All position ratios, stop-loss, and trading rules MUST come from the \
reference documents. Do NOT fabricate numbers.
2. If reference documents are insufficient (has_valid_docs=false), you MUST \
output: {"view":"neutral","confidence":0.0,"reason":"...","suggest_position_ratio":0,"stop_loss_price":null}
3. Output ONLY valid JSON — no markdown, no explanations outside JSON.
4. view ∈ {long, short, neutral}
5. confidence ∈ [0.0, 1.0]
6. suggest_position_ratio ∈ [0.0, 0.3]

## Output Format
```json
{
  "view": "long|short|neutral",
  "confidence": 0.0,
  "reason": "explanation citing reference docs",
  "suggest_position_ratio": 0.0,
  "stop_loss_price": null
}
```
"""


def _call_vllm(system_prompt: str, user_message: str, temperature: float = 0.3) -> str:
    """Call vLLM's chat API."""
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
                    "max_tokens": 512,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f'{{"view":"neutral","confidence":0.0,"reason":"LLM error: {e}","suggest_position_ratio":0,"stop_loss_price":null}}'


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM output."""
    # Try fenced JSON
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try bare JSON
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _neutral_intent(reason: str) -> dict:
    """Return a standardized neutral intent."""
    return {
        "view": "neutral",
        "confidence": 0.0,
        "reason": reason,
        "suggest_position_ratio": 0,
        "stop_loss_price": None,
    }


def run_reasoning_agent(msg: AgentMessage) -> AgentMessage:
    """Generate trading intent from market data + RAG results.

    If has_valid_docs=false → forced neutral output.
    """
    retrieval_payload = msg.payload
    has_valid_docs = retrieval_payload.get("has_valid_docs", False)
    reference_docs = retrieval_payload.get("reference_docs", [])
    market_data = retrieval_payload.get("market_data", "")
    user_request = retrieval_payload.get("user_request", "")

    # ── Short-circuit: no valid docs → neutral ─────────────────
    if not has_valid_docs:
        intent = _neutral_intent(
            "知识库无合格参考文档（置信度不足），无法生成有依据的交易决策"
        )
        return AgentMessage(
            payload=intent,
            status="success",
            source_agent="reasoning_agent",
            target_agent="risk_agent",
            session_id=msg.session_id,
            asset=msg.asset,
            timeframe=msg.timeframe,
        )

    # ── Build LLM prompt ────────────────────────────────────────
    docs_text = "\n\n".join(
        f"### {d.get('title', '?')} (score={d.get('score', 0)})\n{d.get('content', '')}"
        for d in reference_docs
    )

    user_msg = (
        f"用户请求: {user_request}\n\n"
        f"市场数据: {market_data}\n\n"
        f"参考文档 (has_valid_docs={has_valid_docs}):\n{docs_text}\n\n"
        f"根据参考文档生成交易意向JSON。"
    )

    # ── Call LLM ────────────────────────────────────────────────
    llm_output = _call_vllm(REASONING_SYSTEM_PROMPT, user_msg, temperature=0.3)
    intent = _extract_json(llm_output)

    if intent is None:
        intent = _neutral_intent("LLM输出无法解析为有效JSON")

    # ── Validate intent fields ─────────────────────────────────
    intent.setdefault("view", "neutral")
    intent.setdefault("confidence", 0.0)
    intent.setdefault("suggest_position_ratio", 0)
    intent.setdefault("stop_loss_price", None)
    intent.setdefault("reason", "")

    # Clamp values
    intent["confidence"] = max(0.0, min(1.0, float(intent.get("confidence", 0))))
    intent["suggest_position_ratio"] = max(0.0, min(0.3, float(intent.get("suggest_position_ratio", 0))))
    if intent["view"] not in ("long", "short", "neutral"):
        intent["view"] = "neutral"

    return AgentMessage(
        payload=intent,
        status="success",
        source_agent="reasoning_agent",
        target_agent="risk_agent",
        session_id=msg.session_id,
        asset=msg.asset,
        timeframe=msg.timeframe,
    )
