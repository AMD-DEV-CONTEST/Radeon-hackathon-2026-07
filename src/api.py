"""Unified FastAPI server combining all tools and backtest service.

Run:
    /opt/venv/bin/uvicorn src.api:app --host 0.0.0.0 --port 8080

This single server exposes:
- /backtest         — Run strategy backtest
- /validate         — Validate strategy DSL
- /market/summary   — Get market data
- /market/history   — Get historical OHLCV
- /indicators/calc  — Calculate technical indicators
- /paper-trade/exec — Execute paper trade on Binance Testnet
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from .backtest.server import app as backtest_app, BacktestRequest, BacktestResponse
from .tools.market_data import router as market_router
from .tools.indicators import router as indicators_router
from .tools.paper_trade import router as paper_trade_router
from .tools.external.routes import router as external_tools_router


app = FastAPI(
    title="AMD CN Market Quant Agent API",
    description="Domestic stock and ETF strategy generation, validation and simulation API.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS for Dify
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(market_router, prefix="/api")
app.include_router(indicators_router, prefix="/api")
app.include_router(paper_trade_router, prefix="/api")
app.include_router(external_tools_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cn-market-quant-agent", "mode": "simulation"}


@app.post("/api/cn/backtest/report", response_class=PlainTextResponse)
async def cn_backtest_report(payload: dict[str, Any]):
    """Return an auditable Chinese report for a domestic-market DSL."""
    from .backtest.cn_runner import run_cn_demo_backtest

    # The global risk agent is an independent veto point in the Dify
    # multi-agent workflow.  Keep this check at the execution boundary so a
    # downstream node cannot accidentally paper-trade a rejected plan.
    agent_risk_decision = str(payload.get("agent_risk_decision", "")).upper()
    if agent_risk_decision == "REJECT":
        reasons = payload.get("risk_reasons") or ["全局风控 Agent 否决执行"]
        if isinstance(reasons, list):
            reasons = "；".join(str(item) for item in reasons)
        return "# AMD 国内市场策略报告\n\n- 结论：❌ REJECT\n- 原因：" + str(reasons)

    strategy = payload.get("strategy", {})
    market = strategy.get("market", {})
    constraints = strategy.get("constraints", {})
    risk = strategy.get("risk", {})
    errors: list[str] = []
    instrument = str(market.get("instrument", ""))
    if market.get("exchange") != "cn_stock":
        errors.append("exchange 必须为 cn_stock")
    if not (instrument.endswith(".SH") or instrument.endswith(".SZ")):
        errors.append("instrument 必须为 .SH 或 .SZ 证券代码")
    if constraints.get("allow_short") is not False:
        errors.append("国内现货演示禁止裸卖空")
    if int(constraints.get("lot_size", 0) or 0) != 100:
        errors.append("lot_size 必须为100股")
    if float(risk.get("stop_loss", 0) or 0) >= 0:
        errors.append("stop_loss 必须为负数")
    if errors:
        return "# AMD 国内市场策略报告\n\n- 结论：❌ REJECT\n- 原因：" + "；".join(errors)

    result = run_cn_demo_backtest(payload, days=180, initial_balance=100000.0)
    verdict = "⚠️ REVIEW" if result.max_drawdown < -0.15 or result.total_trades < 2 else "✅ PASS"
    alpha = result.total_return - result.benchmark_return
    return (
        "# AMD 国内市场量化策略演示报告\n\n"
        f"- 策略：{strategy.get('name', '未命名策略')}\n"
        f"- 标的：{instrument}\n"
        f"- 周期：{market.get('timeframe', '1d')}\n"
        "- 运行模式：Paper Trading / 模拟回测\n"
        "- 行情来源：确定性合成历史行情（仅用于系统闭环演示）\n"
        "- 市场约束：T+1、100股整数手、禁止裸卖空、佣金、卖出印花税、滑点\n"
        f"- 初始资金：¥{result.initial_balance:,.2f}\n"
        f"- 最终资金：¥{result.final_balance:,.2f}\n"
        f"- 总收益率：{result.total_return:.2%}\n"
        f"- 最大回撤：{result.max_drawdown:.2%}\n"
        f"- 完成交易：{result.total_trades} 笔\n"
        f"- 胜率：{result.win_rate:.2%}\n"
        f"- 相对演示基准 Alpha：{alpha:.2%}\n\n"
        f"## 风控结论\n\n{verdict}\n\n"
        "> 本结果只验证 AMD GPU Agent 的策略生成、校验与模拟执行闭环，不构成投资建议。"
    )


# Re-export backtest endpoints
@app.post("/api/backtest", response_model=BacktestResponse)
async def backtest(req: BacktestRequest):
    """Run a strategy backtest from DSL specification."""
    from .backtest.server import backtest as _backtest
    return await _backtest(req)


@app.post("/api/backtest/report", response_class=PlainTextResponse)
async def backtest_report(req: BacktestRequest):
    """Run a strategy backtest and return a concise Chinese report."""
    from .backtest.server import backtest_report as _backtest_report
    return await _backtest_report(req)


@app.post("/api/validate")
async def validate(strategy: dict):
    """Validate a strategy DSL without running backtest."""
    from .dsl.validator import validate_dsl
    is_valid, errors = validate_dsl(strategy)
    return {"is_valid": is_valid, "errors": errors}


@app.post("/api/walkforward")
async def walk_forward(req: BacktestRequest):
    """Run walk-forward analysis (in-sample / out-of-sample)."""
    from .backtest.server import walk_forward as _wf
    return await _wf(req)


@app.get("/api/knowledge")
async def knowledge_retrieval(query: str = ""):
    """Retrieve trading knowledge from RAG knowledge base."""
    from .knowledge_base.cn_knowledge import retrieve_cn_knowledge
    if not query:
        return {"success": False, "error": "Query parameter 'query' is required"}
    context = retrieve_cn_knowledge(query)
    return {"success": True, "query": query, "context": context}
