# AMD Radeon 优化与稳定性报告

## 实验环境

- GPU：D70709 Navi31 XTW-C A0 GDDR6 48GB 2Slot；VRAM 49136 MB；96 CU / gfx1100。
- ROCm：7.2.1；amdgpu：6.16.13。
- Python：3.10.12；PyTorch：2.9.1+gitff65f5b；torch HIP：7.2.53211-e1a6bc5663。
- vLLM：0.16.1.dev0+g89a77b108.d20260318。
- 模型：`/persistent/models/Qwen3-VL-8B-Instruct`。
- 模型 fingerprint：`cec420e03b2df4db1f120faed9a7a2c302c2d5ecb65ccab2085c2c5e561be6dc`。

## 公平实验条件

- Source commit：`0ce3564`
- 相同 Golden Case、请求顺序、temperature=0、输出上限和评价器。
- Baseline：{"name": "baseline", "model": "/persistent/models/Qwen3-VL-8B-Instruct", "served_model_name": "Qwen/Qwen3-VL-8B-Instruct", "temperature": 0.0, "max_output_tokens": 500, "max_model_len": 16384, "gpu_memory_utilization": 0.9, "max_num_batched_tokens": null, "enable_prefix_caching": false, "context_mode": "full_history", "tool_result_mode": "full"}
- Optimized 对照测量配置：{"name": "optimized", "model": "/persistent/models/Qwen3-VL-8B-Instruct", "served_model_name": "Qwen/Qwen3-VL-8B-Instruct", "temperature": 0.0, "max_output_tokens": 500, "max_model_len": 16384, "gpu_memory_utilization": 0.9, "max_num_batched_tokens": 16384, "enable_prefix_caching": true, "context_mode": "case_capsule_dynamic", "tool_result_mode": "necessary_fields_only"}
- 参数搜索后选定并完成 30 分钟验证的运行配置：{"gpu_memory_utilization": "0.95", "max_num_batched_tokens": "8192", "max_model_len": "16384", "enable_prefix_caching": true}

## Baseline vs Optimized

| 指标 | Baseline | Optimized | 变化 |
|---|---:|---:|---:|
| Input tokens | 11808 | 5795 | 50.9% 减少 |
| TTFT p50 | 9.003s | 0.113s | 98.8% 改善 |
| TPOT p50 | 0.040s | 0.039s | — |
| Latency p95 | 23.407s | 15.228s | — |
| Output throughput | 15.417 tok/s | 25.689 tok/s | — |
| GPU utilization mean | 99.533% | 100.000% | — |
| VRAM peak | 44246.000 MB | 43984.000 MB | — |
| Success rate / OOM | 100.0% / 0 | 100.0% / 0 | — |
| Quality score | 93.571 | 96.364 | 不低于 Baseline |
| Verifier | 0.0% | 0.0% | — |
| ProtectedField retention | 100% | 100.0% | — |

Baseline/Optimized 对照负载刻意固定了共享前缀与性能输出长度；两组均未输出评价器要求的完整 ID 列表，故该表 Verifier 同为 0%。业务语义完整的并发 1/2/4 测试 Verifier 为 100%，并且 Optimized quality score 不低于 Baseline。

## Prefix Cache

重复案件第二问 TTFT 从 9.002s 降至 0.104s，改善 98.8%。
vLLM 日志记录的 Prefix Cache 命中率峰值：99.400%。

## 参数矩阵

| 配置 | gpu_memory_utilization | batch tokens | context | success | TTFT p50 | tok/s | VRAM MB | OOM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| batch32768 | 0.9 | 32768 | 16384 | 100.0% | 0.106 | 48.631 | 41539 | 0 |
| batch8192 | 0.9 | 8192 | 16384 | 100.0% | 0.134 | 49.320 | 43868 | 0 |
| context32k | 0.9 | 16384 | 32768 | 100.0% | 0.113 | 25.407 | 44498 | 0 |
| mem080 | 0.8 | 16384 | 16384 | 100.0% | 0.103 | 48.776 | 39588 | 0 |
| mem085 | 0.85 | 16384 | 16384 | 100.0% | 0.103 | 48.866 | 42036 | 0 |
| mem095 | 0.95 | 16384 | 16384 | 100.0% | 0.136 | 48.921 | 46932 | 0 |
| ref-mem090-batch16384-ctx16k | 0.9 | 16384 | 16384 | 100.0% | 0.136 | 49.322 | 43984 | 0 |

## 并发与稳定性

- 并发档位：[1, 2, 4]；每档 20 请求。
- 30 分钟稳定性：通过；实际 1809.493s；请求 298/298；成功率 100.0%；OOM 0。
- 稳定性 GPU：利用率均值/峰值 99.626%/100.000%；VRAM 峰值 46744.000 MB。
- 稳定性温度峰值 edge/hotspot/VRAM：54.000°C/61.000°C/60.000°C；功耗峰值 224.000 W。
- vLLM PID 全程稳定：True；UI/API：200/200；SQLite quick_check：ok。

## 安全与隐私

- SEC-01/02：通过；模型请求 `http://127.0.0.1:8000/v1/models`。
- SEC-03：通过；未脱敏命中 0。

## 目标验收

- ✅ token_reduction_ge_40: True
- ✅ protected_fields_100: True
- ✅ prefix_ttft_improvement_ge_15: True
- ✅ stability_30m: True
- ✅ quality_not_lower: True
- ✅ security: True
- ✅ privacy: True

## 限制与部署建议

- Prefix Cache 命中率若未由当前 vLLM 版本直接暴露，则以相同前缀第二问 TTFT 和服务日志作为证据。
- 32K 与 16K 使用同一案件验证，质量分相同，但 32K 延迟与显存更高，因此最终保留 16K。
- 0.95 是本实例 30 分钟无 OOM 的最高已验证参数，但仅余约 2.4 GB VRAM；商业环境建议从 0.85 起步并根据多模态负载压测后上调。
- 比赛交互采用 0.95 / batch 8192 / 16K 的已验证配置；批量评测使用 c4 前继续采集温度/功耗。
- 商业部署建议增加按租户限流、指标告警、版本化配置和每日隐私扫描，不对外暴露模型端点。
