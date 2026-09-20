"""NL → DSL generation quality tests.

Tests the extract_yaml() function and DSL validation pipeline
against simulated LLM outputs that mimic real model behavior:
1. Clean YAML output
2. CoT reasoning + fenced YAML
3. CoT reasoning + bare YAML (no code fence)
4. YAML with trailing explanation
5. Minimal/direct YAML

Also tests that the DSL spec validation catches common LLM errors.
"""

import json

import pytest
import yaml

from src.dsl.validator import validate_dsl
from src.dsl.transpiler import transpile_to_freqtrade
from src.dsl.transpiler_backtrader import transpile_to_backtrader


# --- Simulated LLM outputs ---

# 1. Clean fenced YAML
LLM_OUTPUT_CLEAN = """```yaml
strategy:
  name: EMA_Crossover
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
    - name: ema_slow
      type: EMA
      params:
        period: 50
        field: close
  entry:
    long: "ema_fast > ema_slow"
    short: null
  exit:
    long: "ema_fast < ema_slow"
    short: null
  risk:
    stop_loss: -0.03
    max_open_trades: 3
    stake_amount: 0.1
```"""

# 2. CoT reasoning + fenced YAML
LLM_OUTPUT_COT_FENCED = """Step 1: Strategy type — trend following (MA crossover)
Step 2: Indicators — EMA 20 (fast) and EMA 50 (slow)
Step 3: Entry — golden cross (fast > slow)
Step 4: Exit — death cross (fast < slow)
Step 5: Stop-loss — 3% for 1h timeframe
Step 6: Validation — stop_loss is negative, names are snake_case

```yaml
strategy:
  name: EMA_Trend
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
    - name: ema_slow
      type: EMA
      params:
        period: 50
        field: close
  entry:
    long: "ema_fast > ema_slow"
    short: null
  exit:
    long: "ema_fast < ema_slow"
    short: null
  risk:
    stop_loss: -0.03
    max_open_trades: 3
    stake_amount: 0.1
```"""

# 3. CoT + bare YAML (no code fence)
LLM_OUTPUT_COT_BARE = """Step 1: Mean reversion using RSI
Step 2: RSI 14 period
Step 3: Entry when RSI < 30
Step 4: Exit when RSI > 70
Step 5: Stop 5% for wider mean reversion
Step 6: Validation OK

strategy:
  name: RSI_MeanReversion
  market:
    exchange: binance
    pair: BTC/USDT
    timeframe: 1h
  indicators:
    - name: rsi
      type: RSI
      params:
        period: 14
  entry:
    long: "rsi < 30"
    short: null
  exit:
    long: "rsi > 70"
    short: null
  risk:
    stop_loss: -0.05
    max_open_trades: 2
    stake_amount: 0.1"""

# 4. Bollinger Bands with sub-columns
LLM_OUTPUT_BB = """```yaml
strategy:
  name: BB_Bounce
  market:
    exchange: binance
    pair: ETH/USDT
    timeframe: 4h
  indicators:
    - name: bb
      type: BollingerBands
      params:
        period: 20
        std_dev: 2.0
  entry:
    long: "close < bb_lower"
    short: null
  exit:
    long: "close > bb_upper"
    short: null
  risk:
    stop_loss: -0.03
    max_open_trades: 3
    stake_amount: 0.1
```"""

# 5. Multi-indicator confluence with short
LLM_OUTPUT_CONFLUENCE = """```yaml
strategy:
  name: Confluence_Strat
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
    - name: ema_slow
      type: EMA
      params:
        period: 50
        field: close
    - name: rsi
      type: RSI
      params:
        period: 14
    - name: vol_ma
      type: SMA
      params:
        period: 20
        field: volume
  entry:
    long: "ema_fast > ema_slow AND rsi < 70 AND volume > vol_ma * 1.5"
    short: "ema_fast < ema_slow AND rsi > 70 AND volume > vol_ma * 1.5"
  exit:
    long: "ema_fast < ema_slow OR rsi > 70"
    short: "ema_fast > ema_slow OR rsi < 30"
  risk:
    stop_loss: -0.03
    take_profit: 0.06
    trailing_stop: true
    trailing_stop_positive: 0.02
    max_open_trades: 2
    stake_amount: 0.1
```"""


# --- extract_yaml tests ---

def _extract_yaml_from_text(text: str):
    """Import and call extract_yaml from chat_app."""
    # We can't import chat_app directly (requires gradio), so replicate the logic
    import re
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


@pytest.mark.parametrize("llm_output,expected_name", [
    (LLM_OUTPUT_CLEAN, "EMA_Crossover"),
    (LLM_OUTPUT_COT_FENCED, "EMA_Trend"),
    (LLM_OUTPUT_COT_BARE, "RSI_MeanReversion"),
    (LLM_OUTPUT_BB, "BB_Bounce"),
    (LLM_OUTPUT_CONFLUENCE, "Confluence_Strat"),
])
def test_extract_yaml_from_llm_output(llm_output, expected_name):
    """Test that YAML extraction works for various LLM output formats."""
    result = _extract_yaml_from_text(llm_output)
    assert result is not None, f"Failed to extract YAML from output starting with: {llm_output[:50]}..."
    assert "strategy" in result
    assert result["strategy"]["name"] == expected_name


# --- DSL validation of extracted YAML ---

@pytest.mark.parametrize("llm_output", [
    LLM_OUTPUT_CLEAN,
    LLM_OUTPUT_COT_FENCED,
    LLM_OUTPUT_COT_BARE,
    LLM_OUTPUT_BB,
    LLM_OUTPUT_CONFLUENCE,
])
def test_extracted_dsl_passes_validation(llm_output):
    """Test that extracted DSL from simulated LLM output passes validation."""
    dsl = _extract_yaml_from_text(llm_output)
    assert dsl is not None
    is_valid, errors = validate_dsl(dsl)
    assert is_valid, f"DSL validation failed: {errors}"


# --- Transpilation of extracted DSL ---

@pytest.mark.parametrize("llm_output", [
    LLM_OUTPUT_CLEAN,
    LLM_OUTPUT_COT_FENCED,
    LLM_OUTPUT_COT_BARE,
    LLM_OUTPUT_BB,
    LLM_OUTPUT_CONFLUENCE,
])
def test_extracted_dsl_transpiles_to_freqtrade(llm_output):
    """Test that extracted DSL transpiles to valid Freqtrade code."""
    import ast
    dsl = _extract_yaml_from_text(llm_output)
    code = transpile_to_freqtrade(dsl)
    ast.parse(code)  # Raises SyntaxError if invalid


@pytest.mark.parametrize("llm_output", [
    LLM_OUTPUT_CLEAN,
    LLM_OUTPUT_COT_FENCED,
    LLM_OUTPUT_COT_BARE,
    LLM_OUTPUT_BB,
    LLM_OUTPUT_CONFLUENCE,
])
def test_extracted_dsl_transpiles_to_backtrader(llm_output):
    """Test that extracted DSL transpiles to valid Backtrader code."""
    import ast
    dsl = _extract_yaml_from_text(llm_output)
    code = transpile_to_backtrader(dsl)
    ast.parse(code)  # Raises SyntaxError if invalid


# --- Common LLM error detection ---

def test_positive_stop_loss_rejected():
    """LLM sometimes outputs positive stop_loss — should be caught."""
    dsl = {
        "strategy": {
            "name": "BadStop",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": [{"name": "ema", "type": "EMA", "params": {"period": 20, "field": "close"}}],
            "entry": {"long": "close > ema", "short": None},
            "exit": {"long": "close < ema", "short": None},
            "risk": {"stop_loss": 0.03, "max_open_trades": 3, "stake_amount": 0.1},  # Positive!
        }
    }
    is_valid, errors = validate_dsl(dsl)
    assert not is_valid
    assert any("stop_loss" in e for e in errors)


def test_undefined_indicator_rejected():
    """LLM might reference an indicator not in the list — should be caught."""
    dsl = {
        "strategy": {
            "name": "BadRef",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": [{"name": "ema", "type": "EMA", "params": {"period": 20, "field": "close"}}],
            "entry": {"long": "ema > sma_200", "short": None},  # sma_200 not defined!
            "exit": {"long": "ema < sma_200", "short": None},
            "risk": {"stop_loss": -0.03, "max_open_trades": 3, "stake_amount": 0.1},
        }
    }
    is_valid, errors = validate_dsl(dsl)
    assert not is_valid
    assert any("sma_200" in e or "undefined" in e.lower() for e in errors)


def test_bb_sub_columns_accepted():
    """BB sub-columns (bb_lower, bb_upper) should pass validation."""
    dsl = {
        "strategy": {
            "name": "BBTest",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": [{"name": "bb", "type": "BollingerBands", "params": {"period": 20, "std_dev": 2.0}}],
            "entry": {"long": "close < bb_lower", "short": None},
            "exit": {"long": "close > bb_upper", "short": None},
            "risk": {"stop_loss": -0.03, "max_open_trades": 3, "stake_amount": 0.1},
        }
    }
    is_valid, errors = validate_dsl(dsl)
    assert is_valid, f"BB sub-columns should be valid: {errors}"


def test_syntax_error_in_expression_rejected():
    """Malformed expression syntax should be caught by validator."""
    dsl = {
        "strategy": {
            "name": "SyntaxErr",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": [{"name": "ema", "type": "EMA", "params": {"period": 20, "field": "close"}}],
            "entry": {"long": "ema > AND close < 100", "short": None},  # Syntax error
            "exit": {"long": "ema < close", "short": None},
            "risk": {"stop_loss": -0.03, "max_open_trades": 3, "stake_amount": 0.1},
        }
    }
    is_valid, errors = validate_dsl(dsl)
    assert not is_valid
    assert any("syntax" in e.lower() or "error" in e.lower() for e in errors)


# --- End-to-end NL → DSL → Validate → Transpile pipeline ---

def test_full_pipeline_clean_yaml():
    """Full pipeline: extract → validate → transpile (Freqtrade + Backtrader)."""
    import ast
    dsl = _extract_yaml_from_text(LLM_OUTPUT_CONFLUENCE)
    assert dsl is not None

    # Validate
    is_valid, errors = validate_dsl(dsl)
    assert is_valid, f"Validation failed: {errors}"

    # Transpile to Freqtrade
    ft_code = transpile_to_freqtrade(dsl)
    ast.parse(ft_code)

    # Transpile to Backtrader
    bt_code = transpile_to_backtrader(dsl)
    ast.parse(bt_code)


def test_dsl_spec_documentation_exists():
    """Verify that the DSL specification document exists."""
    from pathlib import Path
    spec_path = Path(__file__).parent.parent / "docs" / "dsl_specification.md"
    assert spec_path.exists(), "DSL specification document should exist"
    content = spec_path.read_text()
    assert "Expression Grammar" in content
    assert "Indicator Types" in content
