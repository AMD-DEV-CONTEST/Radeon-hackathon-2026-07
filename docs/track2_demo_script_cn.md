# 视频演示脚本：国内市场量化 Agent

**时长**：~5 分钟 | **格式**：屏幕录制 + 中文旁白

---

## 第一部分：开场 (0:00 – 0:20)

**画面**：项目标题页

**旁白**：
> 这是基于 AMD ROCm GPU 的国内市场量化策略 Agent。用户用中文描述交易策略需求，
> 系统自动生成策略 DSL、执行模拟回测、输出风险报告。全程在 AMD GPU 上运行。

**屏幕文字**：
```
AMD ROCm 7.2.1 | gfx1100 | Qwen2.5-7B | QLoRA | vLLM
```

---

## 第二部分：AMD GPU 证据 (0:20 – 1:00)

**画面 1**：终端 — `rocminfo`

**操作**：运行 `rocminfo | grep -E "Name:|Marketing Name:|Device Type:"`

**旁白**：
> 系统运行在 AMD Radeon Graphics (gfx1100) GPU 上，ROCm 版本 7.2.1，
> CPU 为 AMD EPYC 9334 32 核处理器。

**画面 2**：终端 — vLLM 服务确认

**操作**：运行 `curl -s http://127.0.0.1:8000/v1/models | python3 -m json.tool`

**旁白**：
> vLLM 0.16.1 服务已启动，模型名为 models/qwen-trader-merged，
> 这是经过 QLoRA 微调并合并的 Qwen2.5-7B 中文市场策略模型。

**屏幕文字**：
```
GPU: AMD Radeon Graphics (gfx1100)
ROCm: 7.2.1
vLLM: 0.16.1
Model: models/qwen-trader-merged (Qwen2.5-7B + CN QLoRA)
```

---

## 第三部分：QLoRA 训练成果 (1:00 – 1:45)

**画面**：终端 — 训练日志

**操作**：运行 `cat /persistent/track2/logs/cn_qlora_train.log | tail -20`

**旁白**：
> 模型使用 400 条国内市场策略样本，在 AMD GPU 上进行了 3 个 epoch 的 LoRA 微调。
> 39 步训练，最终 loss 为 0.2848，token accuracy 达到 98.1%，
> Peak GPU 显存使用 16.21 GB。

**屏幕文字**：
```
Training: 39 steps, loss=0.2848, token_accuracy=98.1%
Peak GPU Memory: 16.21 GB
LoRA: r=64, alpha=128, FP16
```

---

## 第四部分：评估质量 (1:45 – 2:30)

**画面**：终端 — 运行评估

**操作**：运行评估脚本

```bash
cd /persistent/radeon-repo/track2-agentic-ai
/opt/venv/bin/python scripts/eval_cn_market_v2.py \
  --vllm-url http://127.0.0.1:8000/v1 \
  --model models/qwen-trader-merged \
  --output /persistent/track2/eval/cn_market_eval_final.json
```

**旁白**：
> 24 条国内市场评估用例覆盖 4 个 ETF 标的和 6 种策略类型。
> 修复前通过率仅 45.83%，主要失败原因是 JSON 格式错误和 lot_size 不合规。
> 通过增强 JSON 提取器和 CN 市场规范化器，修复后通过率达到 100%。

**屏幕文字**：
```
Before: 11/24 passed (45.83%)
After:  24/24 passed (100%)
Checks: json_valid, instrument_match, timeframe_match,
        short_disabled, constraints_valid, numeric_types_valid
```

---

## 第五部分：Dify 工作流演示 (2:30 – 3:45)

**画面 1**：Dify 工作流编辑器

**操作**：展示 6 节点工作流：
1. 用户输入 → 2. RAG 知识检索 → 3. LLM 生成 DSL → 4. 代码执行校验 → 5. 回测请求 → 6. 风险报告

**旁白**：
> Dify 工作流实现了完整的 Agent 闭环。RAG 节点检索国内市场规则，
> LLM 节点使用 AMD GPU 上的模型生成策略 DSL，代码节点执行规范化校验，
> 回测节点执行模拟交易，最终输出 PASS/REJECT 风险报告。

**画面 2**：终端 — 测试 3 类策略

**操作**：依次运行 3 个 curl 请求测试回测 API

**测试 1：沪深300 ETF EMA 趋势策略**
```bash
curl -s -X POST http://127.0.0.1:8080/api/cn/backtest/report \
  -H "Content-Type: application/json" \
  -d '{"strategy":{"name":"CN_EMA_Trend","market":{"exchange":"cn_stock","instrument":"510300.SH","timeframe":"1d"},...}}'
```

**旁白**：
> 沪深300 ETF 日线 EMA20/50 趋势策略，系统返回 PASS 决策，
> 模拟收益率 -2.61%，最大回撤 -3.28%。

**测试 2：中证500 ETF RSI 均值回归策略**
```
标的：510500.SH | 30分钟 | RSI(14)
结果：-0.49% | 最大回撤 -1.27% | ⚠️ REVIEW
```

**测试 3：创业板 ETF ADX+EMA 策略（含约束）**
```
标的：159915.SZ | 日线 | EMA20/50 + ADX(14)>25
结果：+6.07% | 最大回撤 -2.93% | ✅ PASS
```

**屏幕文字**：
```
所有回测使用确定性合成历史行情（仅用于系统演示，不构成投资建议）
市场约束：T+1、100股整手、禁止做空、涨跌停10%、佣金、印花税
```

---

## 第六部分：架构总结 (3:45 – 4:30)

**画面**：架构图

```
┌─────────────────────────────────────────────────────────┐
│                    AMD GPU (gfx1100 / ROCm 7.2.1)        │
│  ┌───────────────────────────────────────────────────┐  │
│  │  vLLM (port 8000)                                  │  │
│  │  Model: qwen-trader-cn-merged (Qwen2.5-7B + LoRA) │  │
│  └───────────────────────┬───────────────────────────┘  │
│                          │                               │
│  ┌───────────────────────▼───────────────────────────┐  │
│  │  FastAPI (port 8080)                               │  │
│  │  /api/knowledge  → RAG 国内市场规则检索            │  │
│  │  /api/cn/backtest/report → 模拟回测 + 风险报告     │  │
│  └───────────────────────┬───────────────────────────┘  │
│                          │                               │
│  ┌───────────────────────▼───────────────────────────┐  │
│  │  Dify Workflow                                     │  │
│  │  用户输入 → RAG → LLM → Code → Backtest → Answer   │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**旁白**：
> 整个系统完全运行在 AMD GPU 上：vLLM 推理、LoRA 训练、RAG 检索、
> 回测引擎均在同一台 AMD 服务器上。Dify 工作流编排所有组件，
> 实现从中文需求到风险决策的完整 Agent 闭环。

---

## 第七部分：声明 (4:30 – 5:00)

**画面**：声明文字

**旁白**：
> 所有回测均使用确定性合成历史行情，仅用于系统闭环演示，不构成投资建议。
> 未进行任何真实交易或实盘操作。系统不涉及任何加密货币内容。

**屏幕文字**：
```
⚠️ 重要声明
- 行情数据：确定性合成历史行情（仅用于演示）
- 交易模式：模拟交易 / Paper Trading
- 投资建议：本结果不构成任何投资建议
- 市场范围：仅限中国境内证券市场（A股、境内ETF）
- 硬件平台：AMD GPU (gfx1100) + ROCm 7.2.1
```
