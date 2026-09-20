# LoRA Training Dataset Construction Spec — Quantitative Agent

**Version 1.0** — AMD AI DevMaster Hackathon 2026, Track 2

## Core Principle

> LoRA **does not learn facts, market parameters, or static rules.**
> It only learns: reasoning patterns, structured output format, tool calling,
> instruction following, and professional quantitative expression.

All dynamic facts (contract specs, strategy parameters, risk thresholds) are
maintained by the RAG knowledge base, not the LoRA weights.

---

## 1. Data Categories (4 types only)

### Category A: Instruction Following & Structured Output (60%)

**Goal:** Force the model to output fixed JSON structure, eliminate free text.

```json
{
  "instruction": "根据行情指标推演交易意向，严格输出JSON，禁止额外文字",
  "input": "当前BTC 1h K线，EMA20=68200，EMA60=67850，ATR=320",
  "output": {
    "view": "long",
    "confidence": 0.72,
    "reason": "短期均线多头排列，价格站稳双均线",
    "suggest_position_ratio": 0.15,
    "stop_loss_price": 67700
  }
}
```

**Constraints:**
- All outputs use unified fields: `view`, `confidence`, `reason`, `suggest_position_ratio`, `stop_loss_price`
- Format-inconsistent samples are discarded
- `view` ∈ {long, short, neutral}
- `confidence` ∈ [0.0, 1.0]
- `suggest_position_ratio` ∈ [0.0, 0.3]

### Category B: Quantitative Logic Reasoning (25%)

**Goal:** Train chain-of-thought reasoning — given indicator conditions,
output step-by-step reasoning → final trading intent.

```json
{
  "instruction": "根据以下指标条件，分步推理后输出交易意向JSON",
  "input": "RSI=28, MACD柱=-15且收缩, 布林下轨=67500, 当前价=67800",
  "output": "Step 1: RSI<30，超卖区域，有反弹可能\nStep 2: MACD柱负值但收缩，下跌动能减弱\nStep 3: 价格接近布林下轨，支撑位附近\nStep 4: 综合判断，均值回归做多\n{\"view\":\"long\",\"confidence\":0.65,\"reason\":\"RSI超卖+MACD收缩+布林支撑\",\"suggest_position_ratio\":0.10,\"stop_loss_price\":67400}"
}
```

**Key:** Train reasoning chains, do NOT embed strategy-specific parameters.

### Category C: Tool Calling Samples (10%)

**Goal:** Train the model to proactively call market data, indicator, and
backtest tools in the correct format.

```json
{
  "instruction": "作为交易Agent，根据用户请求选择合适的工具调用",
  "input": "用户想了解BTC当前行情和RSI指标",
  "output": "Thought: 用户需要行情数据和RSI指标，我先获取市场数据\nAction: {\"tool\":\"get_market_data\",\"pair\":\"BTC/USDT\"}\n\nThought: 接下来计算RSI指标\nAction: {\"tool\":\"retrieve_knowledge\",\"query\":\"RSI指标含义和参数\"}"
}
```

### Category D: Boundary Rejection Samples (5%) — Critical for Hallucination Prevention

**Goal:** When information is insufficient, the model must output standardized
rejection — never fabricate numbers.

```json
{
  "instruction": "根据以下信息判断交易意向，信息不足时必须拒答",
  "input": "用户请求交易建议，但未提供交易品种、时间周期、当前持仓",
  "output": {
    "view": "neutral",
    "confidence": 0.0,
    "reason": "缺少关键参数：交易品种、时间周期、当前持仓，知识库无对应规则支撑，无法生成决策",
    "suggest_position_ratio": 0,
    "stop_loss_price": null
  }
}
```

---

## 2. Prohibited Data (Never Include in Training Set)

- ❌ Fixed strategy parameters, contract specs, risk thresholds (maintained by RAG)
- ❌ Outdated historical market cases (固化过时认知)
- ❌ Conflicting trading rules
- ❌ Vague, inconclusive free-text conversations

---

## 3. Data Cleaning Standards

1. **Logical reproducibility** — every sample's logic must be reproducible;
   numerically inconsistent samples are deleted
2. **Strong input-output correlation** — irrelevant samples are prohibited
3. **Deduplication** — highly similar samples are sampled to prevent overfitting
4. **Split** — 90% train, 10% validation; validation set MUST include extreme
   boundary scenarios

---

## 4. LoRA Training Hyperparameters (7B Base)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Method | QLoRA / LoRA | 4-bit quantization or FP16 LoRA |
| rank | 16 | Balance capacity and overfitting risk |
| alpha | 32 (rank × 2) | Standard scaling |
| lr | 2e-4 ~ 3e-4 | Stable convergence |
| seq_length | 2048 | Reserve space for RAG context |
| grad_accum | 4 ~ 8 | Effective batch size |
| epochs | ≤ 3 | Prevent overfitting |
| target_modules | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj | All linear layers |

**Post-training test:** Deliberately inject RAG rules that conflict with
LoRA's built-in knowledge. Verify the model reads context first, not weights.

---

## 5. Validation Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| Output format compliance | ≥ 98% | All outputs follow JSON schema |
| Context adherence | ≥ 90% | When external docs provided, model follows docs over weights |
| Boundary rejection rate | 100% | Information-missing scenarios correctly trigger neutral |
| Hallucination rate | < 2% | No fabricated numbers without RAG support |

---

## 6. Relationship with RAG

| Layer | Responsibility | What it stores |
|-------|---------------|----------------|
| **LoRA** | Reasoning patterns, output format, tool calling | How to think, not what to know |
| **RAG** | Dynamic facts, rules, parameters | Contract specs, risk thresholds, strategy docs |
| **Risk Agent** | Hard rule enforcement | Position limits, stop-loss compliance (code-level) |

> **The LLM (base + LoRA + RAG) only produces trading intent.**
> **The Risk Agent decides whether execution is allowed.**
