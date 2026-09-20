from src.backtest.cn_runner import run_cn_demo_backtest
from src.knowledge_base.cn_knowledge import retrieve_cn_knowledge


def sample_dsl():
    return {
        "strategy": {
            "name": "CN_EMA_20_50",
            "market": {"exchange": "cn_stock", "instrument": "510300.SH", "timeframe": "1d"},
            "indicators": [
                {"name": "ema_fast", "type": "EMA", "params": {"period": 20}},
                {"name": "ema_slow", "type": "EMA", "params": {"period": 50}},
            ],
            "constraints": {"t_plus_one": True, "price_limit": 0.1, "allow_short": False, "lot_size": 100},
            "risk": {"stop_loss": -0.05, "max_position_pct": 0.3, "max_drawdown": -0.15},
        }
    }


def test_cn_backtest_is_deterministic_and_bounded():
    first = run_cn_demo_backtest(sample_dsl(), 180, 100_000)
    second = run_cn_demo_backtest(sample_dsl(), 180, 100_000)
    assert first == second
    assert first.final_balance > 0
    assert -1 < first.max_drawdown <= 0
    assert first.data_source == "deterministic_synthetic_cn_market_demo"


def test_cn_knowledge_discloses_simulation_and_rules():
    context = retrieve_cn_knowledge("沪深300ETF策略")
    assert "T+1" in context
    assert "100股" in context
    assert "合成行情只能用于系统演示" in context
    assert "不构成投资建议" in context
