"""LLM inference client and system prompts.

Wraps vLLM's OpenAI-compatible API for:
1. NL → DSL generation (with RAG knowledge injection)
2. Backtest report generation
3. Risk assessment
"""

from __future__ import annotations

import json
from typing import Any

import httpx

# RAG knowledge base (optional, gracefully degrades if unavailable)
try:
    from ..knowledge_base.retriever import retrieve_knowledge
    HAS_RAG = True
except ImportError:
    HAS_RAG = False


VLLM_BASE_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "qwen-trader-merged"  # Or the HuggingFace model name


# --- System Prompts ---

DSL_GENERATION_SYSTEM = """\
You are an expert crypto trading strategist with 10+ years of experience. \
Your task is to convert natural language trading ideas into a YAML strategy DSL \
specification using Chain-of-Thought reasoning.

## DSL Structure

```yaml
strategy:
  name: "StrategyName"           # Valid Python identifier
  market:
    exchange: binance            # binance|okx|bybit|kraken|gate
    pair: BTC/USDT               # Format: BASE/QUOTE
    timeframe: 1h                # 1m|5m|15m|30m|1h|4h|1d|1w
  indicators:
    - name: ema_fast             # snake_case variable name
      type: EMA                  # SMA|EMA|RSI|MACD|ATR|BollingerBands|...
      params:
        period: 20               # Integer 1-500
        field: close             # open|high|low|close|volume
  entry:
    long: "ema_fast > ema_slow AND volume > vol_ma * 1.5"
    short: null
  exit:
    long: "ema_fast < ema_slow"
    short: null
  risk:
    stop_loss: -0.03             # Negative ratio (e.g. -0.03 = 3% loss)
    take_profit: 0.06            # Positive ratio (optional)
    trailing_stop: false
    trailing_stop_positive: 0.02
    max_open_trades: 3
    stake_amount: 0.1
```

## Available Indicators
SMA, EMA, RSI, MACD, ATR, BollingerBands, Stochastic, ADX, CCI, OBV, VWAP, WMA, HMA, ZLEMA

## Reasoning Process (think step by step)

1. **Strategy Type**: Identify the strategy type (trend following, mean reversion, breakout, etc.)
2. **Market Regime**: Consider whether the strategy suits the current market context provided
3. **Indicators**: Select the minimum set of indicators needed
4. **Entry Logic**: Define clear, testable entry conditions
5. **Exit Logic**: Define exit conditions (opposite of entry, or trailing stop)
6. **Risk Management**: Set appropriate stop-loss based on volatility (ATR-based if possible)
7. **Validation**: Verify stop_loss is negative, indicator names are snake_case, all referenced indicators are defined

## Few-Shot Example

User: "BTC RSI超卖反弹，做个均值回归策略"

Step 1: Mean reversion strategy — buy oversold, sell overbought
Step 2: RSI is the core indicator; add volume to filter false signals
Step 3: Indicators: rsi (14), vol_ma (20, volume)
Step 4: Entry long: rsi < 30 AND volume > vol_ma (confirm with volume)
Step 5: Exit long: rsi > 70
Step 6: Stop-loss 5% (RSI can overspend in strong trends)
Step 7: Validation: ✓ stop_loss=-0.05, ✓ snake_case, ✓ all refs defined

```yaml
strategy:
  name: RSI_MeanReversion
  market:
    exchange: binance
    pair: BTC/USDT
    timeframe: 1h
  indicators:
    - {name: rsi, type: RSI, params: {period: 14}}
    - {name: vol_ma, type: SMA, params: {period: 20, field: volume}}
  entry:
    long: "rsi < 30 AND volume > vol_ma"
    short: null
  exit:
    long: "rsi > 70"
    short: null
  risk:
    stop_loss: -0.05
    max_open_trades: 2
    stake_amount: 0.1
```

## Rules
1. Output ONLY valid YAML, no explanations
2. stop_loss must be negative
3. Indicator names must be snake_case
4. All referenced indicators must be defined in the indicators list
5. Keep strategy names short and descriptive
6. Consider market context when setting parameters (e.g., wider stops in high vol)
7. The root object must contain strategy; strategy must contain market, indicators, entry, exit, and risk
8. indicators must be a non-empty list
9. stop_loss is allowed only under strategy.risk.stop_loss, must be a numeric negative ratio, and must never be an expression
10. Use entry.long/exit.long for long strategies and entry.short/exit.short for short strategies
11. Never output exit.buy, exit.sell, root-level stop_loss, or any undeclared field
12. If any required field is missing or uncertain, regenerate the complete YAML before responding
"""

REPORT_GENERATION_SYSTEM = """\
You are a professional crypto trading analyst with CFA credentials. \
Given backtest results, generate a rigorous analysis report.

Key metrics to interpret:
- **Sharpe ratio**: >1.0 acceptable, >2.0 good, >3.0 excellent (risk-free rate = 0)
- **Sortino ratio**: >1.5 good; focuses on downside risk only
- **Calmar ratio**: >1.0 means return exceeds max drawdown
- **Max drawdown**: <10% excellent, <20% acceptable, >30% high risk
- **Alpha vs Buy&Hold**: Positive alpha means strategy beats passive holding
- **Max consecutive losses**: Tests psychological sustainability of the strategy
- **Profit factor**: >1.5 indicates a profitable edge

Format your report as:
1. **Strategy Summary**: One-paragraph overview of the strategy logic
2. **Performance vs Benchmark**: Compare strategy return to Buy&Hold return
3. **Risk Analysis**: Drawdown, Sharpe/Sortino ratio, volatility assessment
4. **Trade Analysis**: Win rate, profit factor, consecutive losses, trade duration
5. **Strengths & Weaknesses**: What works, what doesn't — be specific
6. **Recommendation**: APPROVE / MODIFY / REJECT with specific suggestions

Be honest about weaknesses — don't sugarcoat poor performance.
If alpha is negative, clearly state the strategy underperforms buy-and-hold.
If max consecutive losses > 5, flag psychological sustainability risk.
"""

RISK_ASSESSMENT_SYSTEM = """\
You are a risk management expert for crypto trading. Evaluate the \
following strategy's risk profile and provide recommendations.

Consider:
- Maximum drawdown vs. acceptable threshold (<15% is good)
- Sharpe ratio (>1.0 is acceptable, >2.0 is excellent)
- Win rate and profit factor
- Position sizing adequacy
- Stop loss appropriateness for the market's volatility

Output a structured risk assessment with:
- Risk Level: Low/Medium/High/Extreme
- Key Risk Factors: List
- Recommendations: List
- Verdict: APPROVE / APPROVE WITH MODIFICATIONS / REJECT
"""


class LLMClient:
    """Client for vLLM OpenAI-compatible API."""

    def __init__(
        self,
        base_url: str = VLLM_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """Send a chat completion request to vLLM."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_dsl(self, natural_language: str) -> str:
        """Generate strategy DSL from natural language input.

        Injects RAG-retrieved trading knowledge into the prompt for
        more informed parameter selection.
        """
        user_msg = f"Convert this trading idea to DSL:\n\n{natural_language}"
        if HAS_RAG:
            rag_ctx = retrieve_knowledge(natural_language, max_results=3)
            if rag_ctx:
                user_msg += f"\n\n[Relevant Trading Knowledge]\n{rag_ctx}\n\nUse this knowledge when setting indicator parameters, stop-loss, and other risk values."
        return await self.chat(
            system_prompt=DSL_GENERATION_SYSTEM,
            user_message=user_msg,
            temperature=0.2,
            max_tokens=1024,
        )

    async def generate_report(
        self,
        strategy_name: str,
        metrics: dict[str, Any],
    ) -> str:
        """Generate a natural language report from backtest metrics."""
        metrics_str = json.dumps(metrics, indent=2)
        return await self.chat(
            system_prompt=REPORT_GENERATION_SYSTEM,
            user_message=(
                f"Strategy: {strategy_name}\n\n"
                f"Backtest Results:\n{metrics_str}\n\n"
                "Generate a comprehensive analysis report."
            ),
            temperature=0.4,
            max_tokens=1024,
        )

    async def assess_risk(
        self,
        strategy_name: str,
        metrics: dict[str, Any],
    ) -> str:
        """Assess risk of a strategy based on backtest metrics."""
        metrics_str = json.dumps(metrics, indent=2)
        return await self.chat(
            system_prompt=RISK_ASSESSMENT_SYSTEM,
            user_message=(
                f"Strategy: {strategy_name}\n\n"
                f"Metrics:\n{metrics_str}\n\n"
                "Provide a risk assessment."
            ),
            temperature=0.3,
            max_tokens=512,
        )
