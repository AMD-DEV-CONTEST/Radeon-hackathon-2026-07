"""Multi-agent orchestrator — coordinates Retrieval → Reasoning → Risk.

Pipeline:
  ① RetrievalAgent: query → reference_docs + has_valid_docs
  ② ReasoningAgent: market data + docs → trading intent (JSON)
  ③ RiskAgent: intent → allow_execute + final_position_ratio

Short-circuits:
  - has_valid_docs=false → reasoning forced to neutral → risk rejects
  - Any agent timeout → reject
  - RiskAgent veto is final — no appeal

This replaces the single ReAct loop when MULTI_AGENT_MODE=true.
"""

from __future__ import annotations

import json
import os
import time
from typing import Generator

import httpx

from .protocol import AgentMessage
from .retrieval_agent import run_retrieval_agent
from .reasoning_agent import run_reasoning_agent
from .risk_agent import run_risk_agent, RiskConfig

BACKTEST_API_URL = os.environ.get("BACKTEST_API_URL", "http://localhost:8080")


def _get_market_data(pair: str = "BTC/USDT") -> str:
    """Fetch current market data for context."""
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(f"{BACKTEST_API_URL}/api/market/summary", params={"pair": pair})
            if resp.status_code == 200:
                d = resp.json()
                return (
                    f"{pair} = ${d.get('last_price', 0):,.2f}, "
                    f"24h change: {d.get('change_pct', 0):+.1f}%, "
                    f"volume: {d.get('volume_24h', 0):,.0f}"
                )
    except Exception:
        pass
    return "Market data unavailable"


def run_multi_agent(
    user_message: str,
    history: list,
    risk_config: RiskConfig | None = None,
) -> Generator[str, None, None]:
    """Run the three-agent pipeline.

    Yields status updates for the Gradio UI, then the final decision.
    """
    session_id = str(int(time.time()))
    asset = "BTC-USDT"
    timeframe = "1h"

    # ── Step 0: Fetch market data ─────────────────────────────
    yield "🔄 [Orchestrator] 初始化多Agent管道，获取市场数据..."
    market_data = _get_market_data()

    # ── Step 1: Retrieval Agent ────────────────────────────────
    yield "🔍 [Retrieval Agent] 正在多路检索知识库 (keyword + BM25 + reranking)..."

    retrieval_msg = AgentMessage(
        payload={
            "query": user_message,
            "filter_meta": {"asset": asset, "timeframe": timeframe},
        },
        source_agent="orchestrator",
        target_agent="retrieval_agent",
        session_id=session_id,
        asset=asset,
        timeframe=timeframe,
    )

    retrieval_result = run_retrieval_agent(retrieval_msg)

    has_valid = retrieval_result.payload.get("has_valid_docs", False)
    max_score = retrieval_result.payload.get("max_confidence_score", 0)
    num_docs = len(retrieval_result.payload.get("reference_docs", []))

    if has_valid:
        yield f"✅ [Retrieval Agent] 检索完成: {num_docs}条参考文档, 最高置信度={max_score:.2f}"
    else:
        yield f"⚠️ [Retrieval Agent] 无合格文档 (最高置信度={max_score:.2f} < 0.45) → 推理Agent将被强制neutral"

    # ── Step 2: Reasoning Agent ────────────────────────────────
    yield "🧠 [Reasoning Agent] 正在生成交易意向 (LoRA + RAG)..."

    # Pass retrieval results + market data to reasoning agent
    reasoning_input = AgentMessage(
        payload={
            **retrieval_result.payload,
            "market_data": market_data,
            "user_request": user_message,
        },
        source_agent="retrieval_agent",
        target_agent="reasoning_agent",
        session_id=session_id,
        asset=asset,
        timeframe=timeframe,
    )

    reasoning_result = run_reasoning_agent(reasoning_input)
    intent = reasoning_result.payload

    view = intent.get("view", "neutral")
    confidence = intent.get("confidence", 0)
    pos_ratio = intent.get("suggest_position_ratio", 0)
    reason = intent.get("reason", "")

    yield f"📊 [Reasoning Agent] 意向: view={view}, confidence={confidence:.2f}, position={pos_ratio:.2%}"

    # ── Step 3: Risk Agent (veto power) ───────────────────────
    yield "🛡️ [Risk Agent] 正在校验风控规则 (仓位/止损/杠杆)..."

    risk_msg = AgentMessage(
        payload=intent,
        source_agent="reasoning_agent",
        target_agent="risk_agent",
        session_id=session_id,
        asset=asset,
        timeframe=timeframe,
    )

    risk_result = run_risk_agent(risk_msg, config=risk_config)
    risk_payload = risk_result.payload

    allow = risk_payload.get("allow_execute", False)
    final_ratio = risk_payload.get("final_position_ratio", 0)
    audit_note = risk_payload.get("audit_note", "")
    checks_passed = risk_payload.get("checks_passed", [])
    checks_failed = risk_payload.get("checks_failed", [])

    if allow:
        yield f"✅ [Risk Agent] 风控通过! 最终仓位={final_ratio:.2%}"
    else:
        yield f"❌ [Risk Agent] 风控驳回: {audit_note}"

    # ── Final Output ───────────────────────────────────────────
    checks_detail = "\n".join(
        f"  {'✅' if c['passed'] else '❌'} {c['name']}: {c['detail']}"
        for c in risk_payload.get("check_details", [])
    )

    # Format the comprehensive output
    final_output = f"""## 多Agent决策报告

### 📋 用户请求
{user_message}

### 📊 市场数据
{market_data}

### 🔍 检索Agent
- 有效文档: {'✅ 有' if has_valid else '❌ 无 (置信度不足)'}
- 最高置信度: {max_score:.2f}
- 参考文档数: {num_docs}

### 🧠 推理Agent (交易意向)
| 字段 | 值 |
|------|-----|
| 方向 | {view} |
| 置信度 | {confidence:.2f} |
| 建议仓位 | {pos_ratio:.2%} |
| 止损价 | {intent.get('stop_loss_price', 'N/A')} |
| 理由 | {reason} |

### 🛡️ 风控Agent (最终决策)
- **执行许可**: {'✅ 允许' if allow else '❌ 驳回'}
- **最终仓位**: {final_ratio:.2%}
- **审计说明**: {audit_note}

#### 风控检查明细
{checks_detail}

### 📐 消息协议

```json
{json.dumps(risk_result.to_dict(), ensure_ascii=False, indent=2)}
```

### 🏗️ 架构

```
用户请求
  ↓
[Retrieval Agent] → 多路检索 (keyword+BM25+reranking) → 置信度门控
  ↓ (has_valid_docs)
[Reasoning Agent] → LoRA推理 → 交易意向JSON (非下单指令)
  ↓ (trading intent)
[Risk Agent] → 硬规则校验 → 通过/驳回 (一票否决权)
  ↓
最终决策 (只有风控通过才可执行)
```

> ⚠️ **关键设计**: LLM (基座+LoRA+RAG) 只负责产生交易意向。
> 最终能否下单，决定权完全在风控Agent规则引擎。
"""
    yield final_output
