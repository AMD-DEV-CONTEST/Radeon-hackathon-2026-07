"""FastAPI backtest microservice.

Accepts a strategy DSL, transpiles it, runs backtest, returns results.
This service is called by Dify's HTTP Request node.

Run:
    /opt/venv/bin/uvicorn src.backtest.server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..dsl.validator import validate_dsl
from ..dsl.transpiler import transpile_to_freqtrade
from .runner import run_backtest, run_walk_forward, BacktestResult, WalkForwardResult


app = FastAPI(
    title="Crypto Trading Backtest Service",
    description="Backtest trading strategies from DSL specifications",
    version="1.0.0",
)


class BacktestRequest(BaseModel):
    """Request body for the backtest endpoint."""
    strategy: dict[str, Any]  # The full DSL dict
    days: int = 180
    initial_balance: float = 10000.0


class BacktestResponse(BaseModel):
    """Response from the backtest endpoint."""
    success: bool
    is_valid: bool
    validation_errors: list[str] = []
    strategy_name: str = ""
    strategy_code: str = ""  # Generated Freqtrade Python source
    metrics: dict[str, Any] = {}
    trades: list[dict] = []
    equity_curve: list[float] = []
    dates: list[str] = []
    benchmark_curve: list[float] = []
    error: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok", "service": "backtest"}


@app.post("/api/backtest", response_model=BacktestResponse)
async def backtest(req: BacktestRequest) -> BacktestResponse:
    """Run a backtest from a strategy DSL.

    1. Validates the DSL against JSON Schema
    2. Transpiles to Freqtrade strategy code
    3. Runs the backtest on historical data
    4. Returns structured results
    """
    # --- Validate DSL ---
    is_valid, errors = validate_dsl(req.strategy)
    if not is_valid:
        return BacktestResponse(
            success=False,
            is_valid=False,
            validation_errors=errors,
            error="DSL validation failed",
        )

    # --- Transpile to Freqtrade code ---
    strategy_code = transpile_to_freqtrade(req.strategy)
    strategy_name = req.strategy["strategy"]["name"]

    # --- Run backtest ---
    result: BacktestResult = run_backtest(
        strategy_dsl=req.strategy,
        days=req.days,
        initial_balance=req.initial_balance,
    )

    if result.error:
        return BacktestResponse(
            success=False,
            is_valid=True,
            strategy_name=strategy_name,
            strategy_code=strategy_code,
            error=result.error,
            benchmark_curve=[],
        )

    return BacktestResponse(
        success=True,
        is_valid=True,
        strategy_name=strategy_name,
        strategy_code=strategy_code,
        metrics={
            "total_trades": result.total_trades,
            "win_rate": round(result.win_rate, 4),
            "total_return": round(result.total_return, 4),
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "calmar_ratio": result.calmar_ratio,
            "volatility_annual": result.volatility_annual,
            "profit_factor": round(result.profit_factor, 4) if result.profit_factor != float('inf') else None,
            "avg_win": round(result.avg_win, 2),
            "avg_loss": round(result.avg_loss, 2),
            "final_balance": result.final_balance,
            "initial_balance": result.initial_balance,
            "win_trades": result.win_trades,
            "loss_trades": result.loss_trades,
            "max_consecutive_losses": result.max_consecutive_losses,
            "avg_trade_duration": result.avg_trade_duration,
            "benchmark_return": result.benchmark_return,
            "alpha": result.alpha,
            "is_valid": result.is_valid,
        },
        trades=result.trades[-20:],  # Last 20 trades for brevity
        equity_curve=result.equity_curve[::max(1, len(result.equity_curve) // 100)],
        dates=result.dates[::max(1, len(result.dates) // 100)],
        benchmark_curve=result.benchmark_curve[::max(1, len(result.benchmark_curve) // 100)] if result.benchmark_curve else []
    )


@app.post("/api/backtest/report", response_class=PlainTextResponse)
async def backtest_report(req: BacktestRequest) -> str:
    """Run a backtest and return a concise Chinese Markdown report for Dify."""
    response = await backtest(req)

    if not response.success:
        details = "；".join(response.validation_errors) if response.validation_errors else (response.error or "未知错误")
        return (
            "# AMD AI 交易策略回测报告\n\n"
            f"- 策略：{response.strategy_name or '未识别'}\n"
            "- 结论：❌ REJECT（拒绝执行）\n"
            f"- 原因：{details}\n\n"
            "> 本系统不会因回测失败而伪造收益；当前策略必须调整后重新验证。"
        )

    m = response.metrics
    total_return = float(m.get("total_return", 0))
    max_drawdown = float(m.get("max_drawdown", 0))
    sharpe = float(m.get("sharpe_ratio", 0))
    win_rate = float(m.get("win_rate", 0))

    warnings: list[str] = []
    if max_drawdown <= -0.30:
        warnings.append("最大回撤超过 30%")
    if sharpe < 0.5:
        warnings.append("夏普比率低于 0.5")
    if int(m.get("total_trades", 0)) < 20:
        warnings.append("交易样本少于 20 笔")

    verdict = "⚠️ REVIEW（需要人工复核）" if warnings else "✅ PASS（通过基础风控）"
    warning_text = "；".join(warnings) if warnings else "未触发基础风险阈值"

    return (
        "# AMD AI 交易策略回测报告\n\n"
        f"- 策略：{response.strategy_name}\n"
        f"- 回测周期：{req.days} 天\n"
        f"- 初始资金：${float(m.get('initial_balance', req.initial_balance)):,.2f}\n"
        f"- 最终资金：${float(m.get('final_balance', 0)):,.2f}\n"
        f"- 总收益率：{total_return:.2%}\n"
        f"- 最大回撤：{max_drawdown:.2%}\n"
        f"- 夏普比率：{sharpe:.2f}\n"
        f"- 胜率：{win_rate:.2%}\n"
        f"- 完成交易：{int(m.get('total_trades', 0))} 笔\n"
        f"- 相对基准 Alpha：{float(m.get('alpha', 0)):.2%}\n\n"
        f"## 风控结论\n\n{verdict}\n\n风险检查：{warning_text}\n\n"
        "> 仅用于研究和 Paper Trading，不构成投资建议。"
    )


@app.post("/api/validate")
async def validate(strategy: dict[str, Any]):
    """Validate a strategy DSL without running a backtest."""
    is_valid, errors = validate_dsl(strategy)
    return {"is_valid": is_valid, "errors": errors}


@app.post("/api/walkforward")
async def walk_forward(req: BacktestRequest):
    """Run walk-forward analysis (in-sample / out-of-sample split).

    Tests strategy robustness by splitting data 70/30 and comparing
    performance between the two segments. Detects overfitting.
    """
    is_valid, errors = validate_dsl(req.strategy)
    if not is_valid:
        return {"success": False, "is_valid": False, "validation_errors": errors}

    wf: WalkForwardResult = run_walk_forward(
        strategy_dsl=req.strategy,
        days=req.days,
        initial_balance=req.initial_balance,
    )

    if wf.error:
        return {"success": False, "error": wf.error}

    def _metrics(r: BacktestResult) -> dict:
        return {
            "total_trades": r.total_trades,
            "win_rate": round(r.win_rate, 4),
            "total_return": round(r.total_return, 4),
            "max_drawdown": r.max_drawdown,
            "sharpe_ratio": r.sharpe_ratio,
            "sortino_ratio": r.sortino_ratio,
            "benchmark_return": r.benchmark_return,
            "alpha": r.alpha,
        }

    return {
        "success": True,
        "in_sample": _metrics(wf.in_sample),
        "out_of_sample": _metrics(wf.out_of_sample),
        "overfitting_score": wf.overfitting_score,
        "is_robust": wf.is_robust,
        "split_ratio": wf.split_ratio,
    }


@app.get("/api/knowledge")
async def knowledge(query: str = ""):
    """Retrieve trading knowledge from RAG knowledge base."""
    from ..knowledge_base.retriever import retrieve_knowledge
    if not query:
        return {"success": False, "error": "Query parameter 'query' is required"}
    context = retrieve_knowledge(query, max_results=5)
    return {"success": True, "query": query, "context": context}
