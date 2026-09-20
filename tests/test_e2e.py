"""End-to-end pipeline tests."""

import json

import pytest


VALID_DSL = {
    "strategy": {
        "name": "E2ETest",
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


def test_full_dsl_pipeline():
    """Test: validate → transpile → verify output structure."""
    from src.dsl.validator import validate_dsl
    from src.dsl.transpiler import transpile_to_freqtrade

    # Validate
    is_valid, errors = validate_dsl(VALID_DSL)
    assert is_valid, f"Validation failed: {errors}"

    # Transpile
    code = transpile_to_freqtrade(VALID_DSL)

    # Verify output contains all required components
    required_components = [
        "class E2ETest(IStrategy)",
        "INTERFACE_VERSION = 3",
        "timeframe = '1h'",
        "stoploss = -0.03",
        "max_open_trades = 3",
        "def populate_indicators",
        "def populate_entry_trend",
        "def populate_exit_trend",
    ]
    for component in required_components:
        assert component in code, f"Missing: {component}"


def test_dsl_to_json_roundtrip():
    """Test that DSL can be serialized/deserialized correctly."""
    dsl_json = json.dumps(VALID_DSL)
    dsl_parsed = json.loads(dsl_json)
    assert dsl_parsed["strategy"]["name"] == "E2ETest"
    assert len(dsl_parsed["strategy"]["indicators"]) == 2


@pytest.mark.asyncio
async def test_backtest_api():
    """Test the backtest API endpoint (requires running server)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Health check
            resp = await client.get("http://localhost:8080/health")
            if resp.status_code != 200:
                pytest.skip("Backtest API not running")

            # Run backtest
            resp = await client.post(
                "http://localhost:8080/api/backtest",
                json={"strategy": VALID_DSL, "days": 30},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_valid"] is True
            assert data["success"] is True
            assert "metrics" in data
    except httpx.ConnectError:
        pytest.skip("Backtest API not running")


@pytest.mark.asyncio
async def test_llm_inference():
    """Test LLM inference via vLLM (requires running server)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get("http://localhost:8000/v1/models")
            if resp.status_code != 200:
                pytest.skip("vLLM not running")

            models = resp.json()
            assert len(models.get("data", [])) > 0

            # Test chat completion
            resp = await client.post(
                "http://localhost:8000/v1/chat/completions",
                json={
                    "model": models["data"][0]["id"],
                    "messages": [
                        {"role": "user", "content": "What is EMA crossover?"},
                    ],
                    "max_tokens": 128,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["choices"][0]["message"]["content"]) > 0
    except httpx.ConnectError:
        pytest.skip("vLLM not running")


def test_dsl_pairs_generation():
    """Test that DSL training pairs can be generated."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from training.data.prepare_dsl_pairs import generate_dsl_pairs

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        output_path = f.name

    generate_dsl_pairs(total_pairs=10, output_path=output_path)

    with open(output_path) as f:
        lines = f.readlines()

    assert len(lines) == 10
    import json as j
    for line in lines:
        item = j.loads(line.strip())
        assert "instruction" in item
        assert "output" in item
        assert "strategy:" in item["output"]  # Should contain DSL YAML

    import os
    os.unlink(output_path)
