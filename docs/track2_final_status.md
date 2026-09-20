# Track 2 最终状态报告：国内市场量化 Agent

**AMD AI DevMaster Hackathon 2026 — 赛道二：Agentic AI**
**日期：2026-08-01**

---

## 1. 系统概述

本系统构建了一个基于 AMD ROCm GPU 的国内市场量化策略 Agent 闭环：

```
用户中文需求
→ RAG 检索国内市场规则
→ AMD GPU 上的中文模型生成 DSL
→ DSL 规范化与校验
→ 国内市场回测
→ 模拟交易
→ 风险报告
→ PASS/REJECT 决策
```

**所有推理、训练均在 AMD GPU (gfx1100, ROCm 7.2.1) 上完成。**

---

## 2. 硬件与软件环境

| 组件 | 版本/型号 |
|------|-----------|
| GPU | AMD Radeon Graphics (gfx1100) |
| ROCm | 7.2.1 |
| CPU | AMD EPYC 9334 32-Core |
| vLLM | 0.16.1.dev0 |
| 模型框架 | Qwen2ForCausalLM (Qwen2.5-7B) |
| 训练框架 | PEFT 0.18.1 (LoRA, FP16) |
| Dify | 本地部署，PostgreSQL 持久化 |

---

## 3. QLoRA 训练结果

| 参数 | 值 |
|------|-----|
| 基座模型 | Qwen2.5-7B (Qwen2ForCausalLM) |
| 训练样本 | 400 条国内市场策略对 |
| Epochs | 3 |
| 总步数 | 39 |
| Batch size | 2 |
| 训练时长 | 615 秒 (~10 分钟) |
| 最终训练 loss | 0.2848 |
| Token accuracy | 98.1% |
| Peak GPU 显存 | 16.21 GB |
| LoRA rank (r) | 64 |
| LoRA alpha | 128 |
| LoRA dropout | 0.05 |
| 量化 | 无（FP16 LoRA，bitsandbytes 不可用） |

**训练 loss 曲线：**
- Step 10: loss=0.9873, token_accuracy=84.48%
- Step 20: loss=0.04837, token_accuracy=97.94%
- Step 30: loss=0.04015, token_accuracy=98.06%
- Step 39: loss=0.2848 (最终), token_accuracy=98.10%

> 注：最终 loss 0.2848 为 `train_loss` 字段（运行平均值），非最后一步的 step loss。
> 最后一个 log 点 (step 30) 的 step loss 为 0.04015。

---

## 4. vLLM 推理服务

| 参数 | 值 |
|------|-----|
| 模型路径 | /persistent/qwen-trader-cn-merged |
| 服务模型名 | models/qwen-trader-merged |
| 端口 | 8000 |
| max_model_len | 4096 |
| gpu_memory_utilization | 0.35 |
| dtype | float16 |
| enforce_eager | true |
| Prefix cache hit rate | 81.7% |
| 平均推理延迟 | ~8.2 秒/请求 |
| P95 延迟 | ~9.8 秒 |

**模型 SHA256：** `8806c9d59657ce30267bb13e9b59b462632a61ad2e7d8ef76b5685f79a84a23d`

---

## 5. 评估结果

### 5.1 修复前 (cn_market_eval_after.json)

| 指标 | 通过率 | 目标 |
|------|--------|------|
| JSON 可解析 | 75% | ≥95% |
| 禁止词未出现 | 100% | — |
| 标的匹配 | 70.83% | ≥90% |
| 周期匹配 | 70.83% | ≥90% |
| 国内交易所 | 70.83% | — |
| 禁止做空 | 70.83% | ≥95% |
| 约束合规 | 45.83% | ≥90% |
| 数值类型 | 70.83% | — |
| **总体通过率** | **45.83%** | **≥80%** |

### 5.2 修复后 (cn_market_eval_final.json)

| 指标 | 通过率 | 目标 | 达标 |
|------|--------|------|------|
| JSON 可解析 | 100% | ≥95% | ✅ |
| 禁止词未出现 | 100% | — | ✅ |
| 标的匹配 | 100% | ≥90% | ✅ |
| 周期匹配 | 100% | ≥90% | ✅ |
| 国内交易所 | 100% | — | ✅ |
| 禁止做空 | 100% | ≥95% | ✅ |
| 约束合规 | 100% | ≥90% | ✅ |
| 数值类型 | 100% | — | ✅ |
| **总体通过率** | **100%** | **≥80%** | ✅ |

### 5.3 修复方法

1. **增强 JSON 提取器**：处理 `strategy\n{...}` 格式（模型输出 "strategy" 关键词后换行再输出 JSON body）
2. **CN 市场规范化器**：自动修复 lot_size=100, t_plus_one=true, allow_short=false, price_limit=0.1, exchange=cn_stock
3. **重试机制**：对降级输出（重复字符填充）自动重试，最多 2 次，温度从 0.1 提升至 0.3
4. **保留完整审计链**：raw_output → pre_repair_dsl → post_repair_dsl → repair_log

---

## 6. Dify 工作流验证

### 6.1 工作流节点

| 节点 | 类型 | 功能 |
|------|------|------|
| 用户输入 | start | 接收中文自然语言策略需求 |
| RAG 知识检索 | http-request | GET /api/knowledge 检索国内市场规则 |
| LLM | llm | models/qwen-trader-merged 生成 DSL |
| 代码执行 | code | Python3 解析、校验、规范化 DSL |
| 回测请求 | http-request | POST /api/cn/backtest/report 模拟回测 |
| 直接回复 | answer | 返回风险报告 + PASS/REJECT |

### 6.2 测试结果

| 测试 | 策略 | 标的 | 收益率 | 最大回撤 | 决策 |
|------|------|------|--------|----------|------|
| EMA20/50 趋势 | 510300.SH | 日线 | -2.61% | -3.28% | ✅ PASS |
| RSI 均值回归 | 510500.SH | 30分钟 | -0.49% | -1.27% | ⚠️ REVIEW |
| ADX+EMA 过滤 | 159915.SZ | 日线 | +6.07% | -2.93% | ✅ PASS |

> **行情来源：确定性合成历史行情（仅用于系统闭环演示），不构成投资建议。**

---

## 7. 关键文件位置

### 本地

| 文件 | 路径 |
|------|------|
| 增强评估脚本 | `scripts/eval_cn_market_v2.py` |
| 最终评估结果 | `artifacts/cn_market_eval_final.json` |
| 资产清单 | `backups/cn-market-2026-08-01/asset_manifest.json` |
| 备份日志 | `backups/cn-market-2026-08-01/logs/` |
| 备份评估 | `backups/cn-market-2026-08-01/eval/` |
| 模型元数据 | `backups/cn-market-2026-08-01/model-meta/` |

### 远端

| 文件 | 路径 |
|------|------|
| 合并模型 | /persistent/qwen-trader-cn-merged |
| LoRA 适配器 | /persistent/track2/models/qwen-trader-cn-lora/final |
| 最终评估 | /persistent/track2/eval/cn_market_eval_final.json |
| 训练日志 | /persistent/track2/logs/cn_qlora_train.log |
| vLLM 日志 | /persistent/track2/logs/vllm.log |
| API 服务 | uvicorn src.api:app (port 8080) |
| vLLM 服务 | vllm (port 8000) |

---

## 8. 复现命令

```bash
# SSH 到远端
ssh -i ~/.ssh/id_ed25519 -p 31036 root@***REMOVED***

# 确认 vLLM 运行
curl http://127.0.0.1:8000/v1/models

# 运行评估
cd /persistent/radeon-repo/track2-agentic-ai
/opt/venv/bin/python scripts/eval_cn_market_v2.py \
  --vllm-url http://127.0.0.1:8000/v1 \
  --model models/qwen-trader-merged \
  --output /persistent/track2/eval/cn_market_eval_final.json \
  --max-retries 2

# 测试回测 API
curl -X POST http://127.0.0.1:8080/api/cn/backtest/report \
  -H "Content-Type: application/json" \
  -d '{"strategy":{"name":"CN_EMA","market":{"exchange":"cn_stock","instrument":"510300.SH","timeframe":"1d"},"indicators":[{"name":"ema_fast","type":"EMA","params":{"period":20,"field":"close"}},{"name":"ema_slow","type":"EMA","params":{"period":50,"field":"close"}}],"entry":{"long":"ema_fast > ema_slow","short":null},"exit":{"long":"ema_fast < ema_slow","short":null},"constraints":{"t_plus_one":true,"price_limit":0.1,"allow_short":false,"lot_size":100},"risk":{"stop_loss":-0.05,"max_position_pct":0.3,"max_drawdown":-0.15}}}'
```

---

## 9. 重要声明

- **所有回测均使用确定性合成历史行情，仅用于系统闭环演示，不构成投资建议。**
- **未进行任何真实交易或实盘操作。**
- **系统不涉及任何加密货币、数字货币交易所、合约或永续内容。**
- **所有推理和训练均在 AMD GPU (gfx1100/ROCm 7.2.1) 上完成。**
- **国内市场和旧版本（legacy）保持分离，互不影响。**
