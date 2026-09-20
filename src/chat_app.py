"""Gradio-based chat interface for the Crypto Trading Agent.

Replaces Dify with a lightweight Python web UI that connects to
vLLM (OpenAI-compatible API) and the backtest microservice.

Run:
    /opt/venv/bin/python src/chat_app.py

Access: http://localhost:7860
"""

from __future__ import annotations

import io
import json
import os
import re
from typing import Any

import gradio as gr
import httpx
import yaml

# Optional: matplotlib for equity curve chart
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# RAG knowledge base
try:
    from .knowledge_base.retriever import retrieve_knowledge
    HAS_RAG = True
except ImportError:
    HAS_RAG = False
import yaml

# --- Configuration ---
VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
BACKTEST_API_URL = os.environ.get("BACKTEST_API_URL", "http://localhost:8080")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen-trader-merged")
CN_MARKET_MODE = os.environ.get("CN_MARKET_MODE", "1").lower() in {"1", "true", "yes"}

# --- System Prompts ---

SYSTEM_PROMPT_DSL = """You are an expert crypto trading strategist with 10+ years of experience. Convert natural language trading ideas into a YAML strategy DSL specification.

## Reasoning Process
Think step by step, then output ONLY the final YAML:
1. Identify the strategy type (trend following, mean reversion, breakout, etc.)
2. Select the minimum set of indicators needed
3. Define clear entry conditions
4. Define exit conditions
5. Set stop-loss appropriate for the strategy's volatility
6. Verify: stop_loss is negative, indicator names are snake_case, all referenced indicators are defined

## DSL Structure
```yaml
strategy:
  name: "StrategyName"
  market:
    exchange: binance
    pair: BTC/USDT
    timeframe: 1h
  indicators:
    - name: ema_fast
      type: EMA
      params:
        period: 20
        field: close
  entry:
    long: "ema_fast > ema_slow AND volume > vol_ma * 1.5"
    short: null
  exit:
    long: "ema_fast < ema_slow"
    short: null
  risk:
    stop_loss: -0.03
    max_open_trades: 3
    stake_amount: 0.1
```

## Available Indicators
SMA, EMA, RSI, MACD, ATR, BollingerBands, Stochastic, ADX, CCI, OBV, VWAP, WMA, HMA, ZLEMA, Supertrend, ICHIMOKU

## Multi-Column Indicators (produce sub-fields)
- BollingerBands: {name}_upper, {name}_middle, {name}_lower
- MACD: {name}_signal, {name}_hist
- Stochastic: {name}_k, {name}_d
- ICHIMOKU: {name}_tenkan, {name}_kijun, {name}_spanA, {name}_spanB
Use these sub-field names directly in entry/exit expressions (e.g. close < bb_lower).

Boolean operators: AND, OR, NOT, >, <, >=, <=, ==, !=

## Rules
1. Output ONLY valid YAML — no explanations, no markdown code fences
2. stop_loss must be negative (e.g. -0.03 = 3% loss)
3. Indicator names must be snake_case
4. All referenced indicators must be defined in the indicators list
5. Keep strategy names short and descriptive
"""

SYSTEM_PROMPT_REPORT = """You are a professional crypto trading analyst with CFA credentials. Given backtest results, generate a clear analysis report in Chinese.

Key metric interpretation:
- Sharpe >1.0 acceptable, >2.0 good; Sortino >1.5 good
- Max drawdown <10% excellent, <20% acceptable, >30% high risk
- Alpha >0 means strategy beats Buy&Hold; negative alpha means underperform
- Max consecutive losses >5 flags psychological sustainability risk
- Profit factor >1.5 indicates profitable edge

Format:
1. **策略概述** — Strategy logic summary
2. **回测表现** — Key metrics vs Buy&Hold benchmark
3. **风险分析** — Drawdown, Sharpe/Sortino, volatility assessment
4. **优势与不足** — Strengths and weaknesses with specific numbers
5. **建议** — APPROVE / MODIFY / REJECT with specific suggestions

Be honest about poor performance. If alpha is negative, clearly state underperformance vs buy-and-hold."""


def call_vllm(system_prompt: str, user_message: str, temperature: float = 0.3) -> str:
    """Call vLLM's OpenAI-compatible chat API."""
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
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM Error] {e}"


def run_backtest(strategy_dsl: dict) -> dict:
    """Call the backtest API."""
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{BACKTEST_API_URL}/api/backtest",
                json={"strategy": strategy_dsl, "days": 180, "initial_balance": 10000},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def extract_yaml(text: str) -> dict | None:
    """Extract YAML from LLM response.

    Handles multiple output formats:
    1. Fenced YAML: ```yaml ... ``` or ```yml ... ```
    2. Bare code fence: ``` ... ``` containing strategy:
    3. CoT reasoning followed by bare YAML (find 'strategy:' marker)
    4. Entire text as YAML (fallback)
    """
    # 1. Try fenced YAML blocks (yaml or yml or bare ```)
    yaml_match = re.search(r"```(?:ya?ml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if yaml_match:
        yaml_text = yaml_match.group(1)
        try:
            parsed = yaml.safe_load(yaml_text)
            if isinstance(parsed, dict) and "strategy" in parsed:
                return parsed
        except yaml.YAMLError:
            pass

    # 2. Try to find 'strategy:' anywhere in the text (handles CoT before YAML)
    strategy_match = re.search(r"(^|\n)(strategy:\s*\n.*)", text, re.DOTALL)
    if strategy_match:
        yaml_text = strategy_match.group(2)
        try:
            parsed = yaml.safe_load(yaml_text)
            if isinstance(parsed, dict) and "strategy" in parsed:
                return parsed
        except yaml.YAMLError:
            pass

    # 3. Try entire text as YAML (last resort)
    try:
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict) and "strategy" in parsed:
            return parsed
    except yaml.YAMLError:
        pass

    return None


def _generate_equity_chart(equity_curve: list[float], benchmark_curve: list[float], dates: list[str]) -> str | None:
    """Generate equity vs benchmark chart as a temp PNG file.

    Returns path to the saved image, or None if matplotlib unavailable.
    """
    if not HAS_MPL or not equity_curve:
        return None

    fig, ax = plt.subplots(figsize=(10, 4))

    n = len(equity_curve)
    x = range(n)
    ax.plot(x, equity_curve, label="Strategy", linewidth=1.5, color="#2196F3")

    if benchmark_curve:
        # Align benchmark length
        bm = benchmark_curve[:n] if len(benchmark_curve) >= n else benchmark_curve
        ax.plot(range(len(bm)), bm, label="Buy & Hold", linewidth=1.5, color="#FF9800", alpha=0.8)

    ax.set_xlabel("Time")
    ax.set_ylabel("Equity ($)")
    ax.set_title("Strategy Equity vs Buy & Hold Benchmark")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Annotate final values
    if equity_curve:
        final_eq = equity_curve[-1]
        ax.annotate(f"${final_eq:,.0f}", xy=(n - 1, final_eq), fontsize=9, color="#2196F3")
    if benchmark_curve:
        final_bm = benchmark_curve[-1]
        ax.annotate(f"${final_bm:,.0f}", xy=(len(benchmark_curve) - 1, final_bm), fontsize=9, color="#FF9800")

    plt.tight_layout()

    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return tmp.name


def format_metrics(metrics: dict) -> str:
    """Format backtest metrics for display."""
    if not metrics:
        return "No metrics available"

    sortino = metrics.get('sortino_ratio', 0)
    calmar = metrics.get('calmar_ratio', 0)
    vol = metrics.get('volatility_annual', 0)
    max_cl = metrics.get('max_consecutive_losses', 0)
    avg_dur = metrics.get('avg_trade_duration', 0)
    bench = metrics.get('benchmark_return', 0)
    alpha = metrics.get('alpha', 0)

    pf = metrics.get('profit_factor')
    pf_str = f"{pf:.2f}" if pf else "N/A"

    return f"""
| Metric | Value |
|--------|-------|
| Total Trades | {metrics.get('total_trades', 0)} |
| Win Rate | {metrics.get('win_rate', 0):.1%} |
| Total Return | {metrics.get('total_return', 0):.2%} |
| Buy & Hold Return | {bench:.2%} |
| Alpha (vs B&H) | {alpha:+.2%} |
| Max Drawdown | {metrics.get('max_drawdown', 0):.2%} |
| Sharpe Ratio | {metrics.get('sharpe_ratio', 0):.2f} |
| Sortino Ratio | {sortino:.2f} |
| Calmar Ratio | {calmar:.2f} |
| Volatility (Annual) | {vol:.2%} |
| Profit Factor | {pf_str} |
| Max Consecutive Losses | {max_cl} |
| Avg Trade Duration | {avg_dur:.0f} candles |
| Final Balance | ${metrics.get('final_balance', 0):,.2f} |
| Win/Loss | {metrics.get('win_trades', 0)}/{metrics.get('loss_trades', 0)} |
"""


def get_market_context(pair: str = "BTC/USDT") -> str:
    """Fetch current market context for LLM prompt injection."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{BACKTEST_API_URL}/api/market/summary", params={"pair": pair})
            if resp.status_code == 200:
                data = resp.json()
                return (
                    f"Current market: {pair} = ${data.get('last_price', 0):,.2f}, "
                    f"24h change: {data.get('change_pct', 0):+.1f}%, "
                    f"24h high: ${data.get('high_24h', 0):,.2f}, "
                    f"24h low: ${data.get('low_24h', 0):,.2f}, "
                    f"24h volume: {data.get('volume_24h', 0):,.0f}"
                )
    except Exception:
        pass
    return ""


def process_user_message(message: str, history: list) -> str:
    """Full pipeline: NL → DSL → Backtest → Report."""
    yield "🔄 正在获取市场数据..."

    # Fetch market context for better strategy generation
    market_ctx = get_market_context()

    # Retrieve relevant knowledge from RAG
    rag_ctx = retrieve_knowledge(message, max_results=3) if HAS_RAG else ""

    yield "🔄 正在生成策略DSL..."

    # Step 1: Generate DSL via LLM with market context + RAG knowledge
    dsl_prompt = f"{message}"
    context_parts = []
    if market_ctx:
        context_parts.append(f"[Market Context]\n{market_ctx}")
    if rag_ctx:
        context_parts.append(f"[Trading Knowledge]\n{rag_ctx}")
    if context_parts:
        dsl_prompt += "\n\n" + "\n\n".join(context_parts)
        dsl_prompt += "\n\nUse this knowledge when setting strategy parameters (e.g., appropriate stop-loss for the timeframe and asset)."
    if CN_MARKET_MODE:
        from .cn_pipeline import CN_MARKET_DSL_PROMPT, process_cn_model_output
        dsl_system_prompt = CN_MARKET_DSL_PROMPT
    else:
        dsl_system_prompt = SYSTEM_PROMPT_DSL
    dsl_text = call_vllm(dsl_system_prompt, dsl_prompt, temperature=0.2)

    # Extract and canonicalize; keep raw output for auditability.
    cn_result = process_cn_model_output(dsl_text) if CN_MARKET_MODE else None
    strategy_dsl = cn_result["canonicalized"] if cn_result else extract_yaml(dsl_text)
    if strategy_dsl is None:
        yield f"❌ LLM无法生成有效的策略DSL。原始输出:\n\n{dsl_text}"
        return

    strategy_name = strategy_dsl.get("strategy", {}).get("name", "Unknown")
    yield f"✅ 策略DSL生成完成: **{strategy_name}**\n\n🔄 正在校验并执行回测..."

    # Step 2: Run backtest
    backtest_result = run_backtest(strategy_dsl)

    if not backtest_result.get("success"):
        error = backtest_result.get("error", "Unknown error")
        yield f"✅ 策略DSL生成完成: **{strategy_name}**\n\n❌ 回测失败: {error}"
        return

    metrics = backtest_result.get("metrics", {})
    metrics_str = format_metrics(metrics)

    yield f"✅ 策略DSL生成完成: **{strategy_name}**\n✅ 回测完成\n\n🔄 正在生成分析报告..."

    # Step 3: Generate report via LLM
    report = call_vllm(
        SYSTEM_PROMPT_REPORT,
        f"策略: {strategy_name}\n\n回测结果:\n{json.dumps(metrics, indent=2)}\n\n生成中文分析报告。",
        temperature=0.4,
    )

    # Generate equity curve chart
    equity_curve = backtest_result.get("equity_curve", [])
    benchmark_curve = backtest_result.get("benchmark_curve", [])
    dates = backtest_result.get("dates", [])
    chart_path = _generate_equity_chart(equity_curve, benchmark_curve, dates)

    # Final output
    dsl_yaml = yaml.dump(strategy_dsl, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Build walk-forward summary if available
    wf_summary = ""
    try:
        wf_result = _call_walkforward(strategy_dsl)
        if wf_result and wf_result.get("success"):
            is_m = wf_result["in_sample"]
            oos_m = wf_result["out_of_sample"]
            robust = "✅ 稳健" if wf_result.get("is_robust") else "⚠️ 可能过拟合"
            wf_summary = f"""
---

### 🔬 Walk-Forward 分析 (样本外验证)

| 指标 | 样本内 (IS) | 样本外 (OOS) |
|------|------------|-------------|
| 收益率 | {is_m['total_return']:.2%} | {oos_m['total_return']:.2%} |
| Sharpe | {is_m['sharpe_ratio']:.2f} | {oos_m['sharpe_ratio']:.2f} |
| Max DD | {is_m['max_drawdown']:.2%} | {oos_m['max_drawdown']:.2%} |
| Alpha | {is_m['alpha']:+.2%} | {oos_m['alpha']:+.2%} |

- **过拟合分数**: {wf_result['overfitting_score']:+.2%} (越低越好)
- **稳健性评估**: {robust}
"""
    except Exception:
        pass

    chart_md = f"\n\n### 📈 净值曲线\n\n![Equity Curve]({chart_path})" if chart_path else ""

    final_output = f"""## 策略分析报告

{report}

---

### 📊 回测指标

{metrics_str}{chart_md}
{wf_summary}

---

### 📝 策略DSL (YAML)

```yaml
{dsl_yaml}
```

---

### 🤖 技术栈
- **LLM推理**: Qwen2.5-7B (QLoRA微调) on AMD ROCm GPU via vLLM
- **回测引擎**: FastAPI + CCXT + TA-Lib (多仓位 + 滑点 + 基准对比)
- **全链路**: 自然语言 → DSL生成 → Schema校验 → 历史回测 → Walk-Forward → AI分析报告
"""
    yield final_output


def _call_walkforward(strategy_dsl: dict) -> dict | None:
    """Call walk-forward analysis API."""
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{BACKTEST_API_URL}/api/walkforward",
                json={"strategy": strategy_dsl, "days": 180, "initial_balance": 10000},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None


def create_app():
    """Create the Gradio chat interface."""
    with gr.Blocks(
        title="Crypto Trading Agent — AMD ROCm",
    ) as app:
        gr.Markdown("""
# 🤖 Crypto Trading Agent on AMD Radeon GPU

**AMD AI DevMaster Hackathon 2026 — Track 2: Agentic AI**

用自然语言描述交易策略，AI自动生成策略DSL → 回测 → 分析报告。
Powered by Qwen2.5-7B (QLoRA fine-tuned) on AMD ROCm GPU.
""")

        with gr.Row():
            with gr.Column(scale=4):
                chat = gr.ChatInterface(
                    fn=process_user_message,
                    title="交易策略助手",
                    examples=[
                        "BTC放量突破前高，帮我做一个EMA突破策略，止损3%",
                        "RSI超卖反弹策略，BTC/USDT 1小时线，RSI低于30买入",
                        "布林带策略，ETH/USDT，价格触及下轨买入，上轨卖出",
                        "MACD金叉策略，BTC/USDT 4小时线，止损5%",
                        "多指标共振策略：EMA金叉 + RSI超卖 + 放量确认",
                    ],
                )
            with gr.Column(scale=1):
                gr.Markdown("""
### 🏗 架构

```
用户输入 (NL)
    ↓
LLM: Qwen2.5-7B
  (vLLM/ROCm GPU)
    ↓
策略DSL (YAML)
    ↓
JSON Schema 校验
    ↓
回测 (CCXT + TA-Lib)
    ↓
LLM: 分析报告
```

### 📊 评审对标

| 维度 | 分值 |
|------|------|
| 功能完整性 | 60 |
| ROCm优化 | 40 |
""")

    return app


if __name__ == "__main__":
    app = create_app()
    app.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
