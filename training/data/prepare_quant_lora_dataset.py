"""Generate LoRA training dataset for the quantitative agent.

Produces 4 categories of samples following the LoRA Training Spec:
  A (60%) — Instruction following & structured JSON output
  B (25%) — Quantitative logic reasoning with chain-of-thought
  C (10%) — Tool calling format
  D (5%)  — Boundary rejection (anti-hallucination)

Key principle: LoRA does NOT learn facts, market parameters, or static rules.
All dynamic facts come from the RAG knowledge base.

Usage:
    python training/data/prepare_quant_lora_dataset.py
    # → training/data/processed/quant_lora_train.jsonl
    # → training/data/processed/quant_lora_val.jsonl
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

random.seed(42)

# ── Output paths ────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent / "processed"
TRAIN_FILE = OUTPUT_DIR / "quant_lora_train.jsonl"
VAL_FILE = OUTPUT_DIR / "quant_lora_val.jsonl"

TOTAL_SAMPLES = 2000
VAL_RATIO = 0.10

# Category distribution
CAT_A_RATIO = 0.60  # Structured output
CAT_B_RATIO = 0.25  # Reasoning
CAT_C_RATIO = 0.10  # Tool calling
CAT_D_RATIO = 0.05  # Boundary rejection


# ═══════════════════════════════════════════════════════════════════
#  Category A: Instruction Following & Structured Output (60%)
# ═══════════════════════════════════════════════════════════════════

ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
TIMEFRAMES = ["15m", "1h", "4h", "1d"]
VIEWS = ["long", "short", "neutral"]

# Indicator scenarios (generic patterns, NOT fixed strategy params)
INDICATOR_SCENARIOS = [
    {
        "desc": "EMA短期在长期上方，多头排列",
        "indicators": "EMA20={ema_fast}, EMA60={ema_slow}, ATR={atr}",
        "view": "long",
        "confidence_range": (0.6, 0.8),
        "reason": "短期均线多头排列，价格站稳双均线",
    },
    {
        "desc": "EMA短期在长期下方，空头排列",
        "indicators": "EMA20={ema_fast}, EMA60={ema_slow}, ATR={atr}",
        "view": "short",
        "confidence_range": (0.55, 0.75),
        "reason": "短期均线下穿长期均线，空头排列确认",
    },
    {
        "desc": "RSI超卖区域，有反弹可能",
        "indicators": "RSI={rsi}, MACD柱={macd_hist}, 当前价={price}",
        "view": "long",
        "confidence_range": (0.5, 0.7),
        "reason": "RSI超卖+下跌动能减弱，均值回归做多",
    },
    {
        "desc": "RSI超买区域，有回调风险",
        "indicators": "RSI={rsi}, MACD柱={macd_hist}, 当前价={price}",
        "view": "short",
        "confidence_range": (0.5, 0.7),
        "reason": "RSI超买+上涨动能减弱，均值回归做空",
    },
    {
        "desc": "布林带收窄，价格在中轨附近，方向不明",
        "indicators": "BB_upper={bb_upper}, BB_middle={bb_mid}, BB_lower={bb_lower}, 当前价={price}",
        "view": "neutral",
        "confidence_range": (0.2, 0.4),
        "reason": "布林带收窄，波动率降低，等待方向突破",
    },
    {
        "desc": "价格突破布林上轨，强势突破",
        "indicators": "BB_upper={bb_upper}, BB_middle={bb_mid}, 当前价={price}, 成交量放大",
        "view": "long",
        "confidence_range": (0.6, 0.75),
        "reason": "价格突破布林上轨且成交量放大，动量突破确认",
    },
    {
        "desc": "MACD金叉，零轴上方",
        "indicators": "MACD={macd}, MACD_signal={macd_signal}, MACD_hist={macd_hist}",
        "view": "long",
        "confidence_range": (0.55, 0.7),
        "reason": "MACD金叉且在零轴上方，多头动能增强",
    },
    {
        "desc": "MACD死叉，零轴下方",
        "indicators": "MACD={macd}, MACD_signal={macd_signal}, MACD_hist={macd_hist}",
        "view": "short",
        "confidence_range": (0.55, 0.7),
        "reason": "MACD死叉且在零轴下方，空头动能增强",
    },
]


def _rand_price(asset: str) -> float:
    prices = {"BTC": (60000, 70000), "ETH": (3000, 4000), "SOL": (140, 180), "BNB": (550, 650)}
    base = asset.split("/")[0]
    lo, hi = prices.get(base, (100, 200))
    return round(random.uniform(lo, hi), 2)


def _gen_category_a() -> list[dict]:
    """Generate structured output samples."""
    samples = []
    count = int(TOTAL_SAMPLES * CAT_A_RATIO)

    for _ in range(count):
        scenario = random.choice(INDICATOR_SCENARIOS)
        asset = random.choice(ASSETS)
        timeframe = random.choice(TIMEFRAMES)
        price = _rand_price(asset)

        # Generate indicator values (generic, not fixed strategy params)
        params = {
            "ema_fast": round(price * random.uniform(0.99, 1.01), 2),
            "ema_slow": round(price * random.uniform(0.97, 1.03), 2),
            "atr": round(price * random.uniform(0.01, 0.04), 2),
            "rsi": round(random.uniform(20, 80), 1),
            "macd": round(random.uniform(-50, 50), 2),
            "macd_signal": round(random.uniform(-50, 50), 2),
            "macd_hist": round(random.uniform(-20, 20), 2),
            "price": price,
            "bb_upper": round(price * 1.03, 2),
            "bb_mid": round(price * 1.0, 2),
            "bb_lower": round(price * 0.97, 2),
        }

        indicators_str = scenario["indicators"].format(**params)
        conf = round(random.uniform(*scenario["confidence_range"]), 2)
        pos_ratio = round(random.uniform(0.05, 0.2), 2) if scenario["view"] != "neutral" else 0.0
        stop_loss = round(price * (1 - random.uniform(0.02, 0.05)), 2) if scenario["view"] == "long" else \
                    round(price * (1 + random.uniform(0.02, 0.05)), 2) if scenario["view"] == "short" else None

        instruction = f"根据行情指标推演交易意向，严格输出JSON，禁止额外文字。品种: {asset}, 周期: {timeframe}"
        input_text = indicators_str
        output = {
            "view": scenario["view"],
            "confidence": conf,
            "reason": scenario["reason"],
            "suggest_position_ratio": pos_ratio,
            "stop_loss_price": stop_loss,
        }

        samples.append({
            "instruction": instruction,
            "input": input_text,
            "output": json.dumps(output, ensure_ascii=False),
            "source": "cat_a_structured",
        })

    return samples


# ═══════════════════════════════════════════════════════════════════
#  Category B: Quantitative Logic Reasoning (25%)
# ═══════════════════════════════════════════════════════════════════

REASONING_TEMPLATES = [
    {
        "input": "RSI={rsi}, MACD柱={macd_hist}且{direction}, 布林{bb_pos}=67500, 当前价={price}",
        "steps": [
            "Step 1: RSI={rsi}，{rsi_status}",
            "Step 2: MACD柱={macd_hist}，{macd_status}",
            "Step 3: 价格{price}相对布林{bb_pos}，{bb_status}",
            "Step 4: 综合判断，{final}",
        ],
        "view": "long",
        "reason_template": "RSI{rsi_status_short}+MACD{macd_status_short}+布林{bb_status_short}",
    },
    {
        "input": "EMA20={ema_fast}, EMA60={ema_slow}, ADX={adx}, 成交量={vol_status}",
        "steps": [
            "Step 1: EMA20={ema_fast} vs EMA60={ema_slow}，{ema_status}",
            "Step 2: ADX={adx}，{adx_status}",
            "Step 3: 成交量{vol_status}",
            "Step 4: 综合判断，{final}",
        ],
        "view": "long",
        "reason_template": "均线{ema_status_short}+ADX{adx_status_short}+量能{vol_status}",
    },
]


def _gen_category_b() -> list[dict]:
    """Generate reasoning chain samples."""
    samples = []
    count = int(TOTAL_SAMPLES * CAT_B_RATIO)

    for _ in range(count):
        asset = random.choice(ASSETS)
        timeframe = random.choice(TIMEFRAMES)
        price = _rand_price(asset)
        is_long = random.choice([True, False])

        rsi = round(random.uniform(22, 35) if is_long else random.uniform(65, 78), 1)
        macd_hist = round(random.uniform(-15, -5) if is_long else random.uniform(5, 15), 2)
        ema_fast = round(price * (1 + random.uniform(-0.01, 0.01)), 2)
        ema_slow = round(price * (1 + (random.uniform(0.005, 0.02) if is_long else random.uniform(-0.02, -0.005))), 2)
        adx = round(random.uniform(25, 45), 1)

        rsi_status = "超卖区域，有反弹可能" if is_long else "超买区域，有回调风险"
        macd_status = "负值但收缩，下跌动能减弱" if is_long else "正值但收缩，上涨动能减弱"
        bb_pos = "下轨" if is_long else "上轨"
        bb_status = "支撑位附近" if is_long else "压力位附近"
        ema_status = "多头排列" if is_long else "空头排列"
        adx_status = "趋势较强" if adx > 30 else "趋势一般"
        vol_status = "放量确认" if random.random() > 0.5 else "缩量"

        final = "均值回归做多" if is_long else "均值回归做空"
        view = "long" if is_long else "short"
        conf = round(random.uniform(0.55, 0.75), 2)
        pos_ratio = round(random.uniform(0.08, 0.15), 2)
        stop = round(price * (1 - 0.03) if is_long else price * (1 + 0.03), 2)

        params = {
            "rsi": rsi, "macd_hist": macd_hist, "price": price,
            "direction": "收缩" if is_long else "收缩",
            "bb_pos": bb_pos,
            "ema_fast": ema_fast, "ema_slow": ema_slow,
            "adx": adx, "vol_status": vol_status,
            "rsi_status": rsi_status, "macd_status": macd_status,
            "bb_status": bb_status, "ema_status": ema_status,
            "adx_status": adx_status, "final": final,
            "rsi_status_short": "超卖", "macd_status_short": "动能减弱",
            "bb_status_short": "支撑" if is_long else "压力",
            "ema_status_short": "多头排列" if is_long else "空头排列",
            "adx_status_short": "趋势确认" if adx > 30 else "趋势一般",
        }

        template = random.choice(REASONING_TEMPLATES)
        input_text = template["input"].format(**params)
        steps = [s.format(**params) for s in template["steps"]]
        output_json = json.dumps({
            "view": view,
            "confidence": conf,
            "reason": template["reason_template"].format(**params),
            "suggest_position_ratio": pos_ratio,
            "stop_loss_price": stop,
        }, ensure_ascii=False)
        output = "\n".join(steps) + "\n" + output_json

        samples.append({
            "instruction": f"根据以下指标条件，分步推理后输出交易意向JSON。品种: {asset}, 周期: {timeframe}",
            "input": input_text,
            "output": output,
            "source": "cat_b_reasoning",
        })

    return samples


# ═══════════════════════════════════════════════════════════════════
#  Category C: Tool Calling (10%)
# ═══════════════════════════════════════════════════════════════════

TOOL_SCENARIOS = [
    {
        "user": "帮我查一下BTC当前行情",
        "thought": "用户需要实时行情数据",
        "action": '{"tool": "get_market_data", "pair": "BTC/USDT"}',
    },
    {
        "user": "RSI指标怎么用？参数一般设多少？",
        "thought": "用户询问RSI指标知识，检索知识库",
        "action": '{"tool": "retrieve_knowledge", "query": "RSI指标含义和参数"}',
    },
    {
        "user": "帮我回测一个EMA交叉策略",
        "thought": "用户需要生成策略DSL，然后回测",
        "action": '{"tool": "generate_strategy_dsl", "description": "EMA交叉策略，快线20慢线50"}',
    },
    {
        "user": "当前策略回测结果如何？有没有过拟合？",
        "thought": "用户需要回测结果和过拟合检测",
        "action": '{"tool": "walk_forward_analysis", "dsl": "<current_strategy>"}',
    },
    {
        "user": "帮我模拟买入0.001个BTC",
        "thought": "用户要求模拟交易",
        "action": '{"tool": "paper_trade", "action": "buy", "pair": "BTC/USDT", "amount": 0.001}',
    },
    {
        "user": "MACD和布林带有什么策略模式？",
        "thought": "检索策略知识",
        "action": '{"tool": "retrieve_knowledge", "query": "MACD布林带策略模式"}',
    },
    {
        "user": "止损应该怎么设？",
        "thought": "检索风控知识",
        "action": '{"tool": "retrieve_knowledge", "query": "止损规则仓位管理"}',
    },
    {
        "user": "ETH现在什么情况？",
        "thought": "获取ETH实时行情",
        "action": '{"tool": "get_market_data", "pair": "ETH/USDT"}',
    },
]


def _gen_category_c() -> list[dict]:
    """Generate tool calling samples."""
    samples = []
    count = int(TOTAL_SAMPLES * CAT_C_RATIO)

    for _ in range(count):
        scenario = random.choice(TOOL_SCENARIOS)
        output = f"Thought: {scenario['thought']}\nAction: {scenario['action']}"

        samples.append({
            "instruction": "作为交易Agent，根据用户请求选择合适的工具调用",
            "input": scenario["user"],
            "output": output,
            "source": "cat_c_tool_call",
        })

    return samples


# ═══════════════════════════════════════════════════════════════════
#  Category D: Boundary Rejection (5%) — Anti-Hallucination
# ═══════════════════════════════════════════════════════════════════

BOUNDARY_SCENARIOS = [
    {
        "input": "用户请求交易建议，但未提供交易品种、时间周期、当前持仓",
        "reason": "缺少关键参数：交易品种、时间周期、当前持仓，知识库无对应规则支撑，无法生成决策",
    },
    {
        "input": "用户要求推荐具体止损价格，但未提供当前价格和ATR波动率",
        "reason": "缺少当前价格和波动率参数，无法计算合理止损位",
    },
    {
        "input": "用户询问某山寨币策略，但知识库中无该品种任何信息",
        "reason": "知识库无该品种相关数据，无法提供有依据的策略建议",
    },
    {
        "input": "用户要求满仓操作，但未提供风险承受能力和资金规模",
        "reason": "缺少风险承受能力评估，满仓操作不符合风控要求",
    },
    {
        "input": "指标数据异常：RSI=150（超出0-100范围），数据可能错误",
        "reason": "输入指标数据异常（RSI超出有效范围），数据质量不可靠",
    },
    {
        "input": "用户要求基于一条新闻做多，但无法验证新闻真实性",
        "reason": "无法验证新闻来源和真实性，不基于未验证信息生成交易决策",
    },
    {
        "input": "市场处于极端行情，历史回测数据可能不适用",
        "reason": "极端行情下历史规律可能失效，建议等待波动率回归正常区间",
    },
    {
        "input": "用户要求高杠杆交易，但当前风控规则不允许杠杆",
        "reason": "风控规则禁止杠杆交易，建议使用现货模式",
    },
]


def _gen_category_d() -> list[dict]:
    """Generate boundary rejection samples."""
    samples = []
    count = int(TOTAL_SAMPLES * CAT_D_RATIO)

    for _ in range(count):
        scenario = random.choice(BOUNDARY_SCENARIOS)
        output = json.dumps({
            "view": "neutral",
            "confidence": 0.0,
            "reason": scenario["reason"],
            "suggest_position_ratio": 0,
            "stop_loss_price": None,
        }, ensure_ascii=False)

        samples.append({
            "instruction": "根据以下信息判断交易意向，信息不足或数据异常时必须拒答（输出neutral）",
            "input": scenario["input"],
            "output": output,
            "source": "cat_d_boundary",
        })

    return samples


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════


def generate_dataset():
    """Generate the complete 4-category LoRA training dataset."""
    print("Generating LoRA training dataset...")

    cat_a = _gen_category_a()
    cat_b = _gen_category_b()
    cat_c = _gen_category_c()
    cat_d = _gen_category_d()

    all_samples = cat_a + cat_b + cat_c + cat_d
    random.shuffle(all_samples)

    # Split into train / validation
    val_count = int(len(all_samples) * VAL_RATIO)
    val_samples = all_samples[:val_count]
    train_samples = all_samples[val_count:]

    # Ensure validation set includes boundary samples
    val_boundary = [s for s in val_samples if s["source"] == "cat_d_boundary"]
    if len(val_boundary) < 3:
        # Move some boundary samples to validation
        train_boundary = [s for s in train_samples if s["source"] == "cat_d_boundary"]
        for s in train_boundary[:3 - len(val_boundary)]:
            train_samples.remove(s)
            val_samples.append(s)

    # Write
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(TRAIN_FILE, "w") as f:
        for sample in train_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    with open(VAL_FILE, "w") as f:
        for sample in val_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"✅ Training set: {TRAIN_FILE} ({len(train_samples)} samples)")
    print(f"✅ Validation set: {VAL_FILE} ({len(val_samples)} samples)")
    print(f"\nCategory distribution:")
    print(f"  A (structured output): {len(cat_a)} ({len(cat_a)/len(all_samples)*100:.0f}%)")
    print(f"  B (reasoning):          {len(cat_b)} ({len(cat_b)/len(all_samples)*100:.0f}%)")
    print(f"  C (tool calling):       {len(cat_c)} ({len(cat_c)/len(all_samples)*100:.0f}%)")
    print(f"  D (boundary rejection): {len(cat_d)} ({len(cat_d)/len(all_samples)*100:.0f}%)")
    print(f"\nValidation set includes {len([s for s in val_samples if s['source'] == 'cat_d_boundary'])} boundary samples")


if __name__ == "__main__":
    generate_dataset()
