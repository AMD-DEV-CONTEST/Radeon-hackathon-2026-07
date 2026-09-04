# 动态记忆压缩与稀疏反馈实验报告

所有性能数字均来自本次运行日志；稀疏反馈为明确标记的模拟评审流程，不是法律或保险专家的真实签署意见，也未用于训练或 LoRA。

## MEM-03 完整上下文 Baseline

| 指标 | 结果 |
|---|---:|
| Input tokens | 11708 |
| Output tokens | 500 |
| TTFT | 8859.94 ms |
| TPOT | 40.81 ms/token |
| Total latency | 29.226 s |
| GPU utilization mean/peak | 98.7% / 100% |
| VRAM used peak | 43820 MB |
| Quality / verifier | 21.429 / False |

## MEM-04 Case Capsule

| 指标 | 结果 |
|---|---:|
| Input tokens | 8718 |
| Token reduction | 25.54% |
| TTFT | 5419.32 ms |
| TPOT | 40.04 ms/token |
| Total latency | 25.400 s |
| Latency change | -13.09% |
| VRAM peak change | 0 MB |
| Conclusion consistency | 100.00% |

## MEM-05 忠实性

- Protected fields: 101 个；保留率 100.00%。
- 结果：通过。
- 检查范围：日期、法定期限、金额、责任比例、Evidence ID、Fact ID、Law ID、审批状态，以及既有车辆/当事人保护字段。

## EXP-01/02 案件与评测问题

- 3 个合成测试案件；12 个问题（车辆、责任、权益、证据各 3 个）。
- Demo B 缺车辆属性鉴定与路口监控；Demo C 包含视频/认定书冲突。

## EXP-03 RAG 网格

| 配置 | Recall | Citation accuracy | Latency (s) | Verifier |
|---|---:|---:|---:|---:|
| top12-rerank3 | 0.708 | 0.375 | 0.3884 | 55.8 |
| top12-rerank5 | 0.708 | 0.322 | 0.3906 | 53.5 |
| top4-rerank3 | 0.431 | 0.375 | 0.3869 | 40.6 |
| top4-rerank5 | 0.431 | 0.354 | 0.3889 | 39.6 |
| top8-rerank3 | 0.667 | 0.375 | 0.3876 | 53.5 |
| top8-rerank5 | 0.667 | 0.322 | 0.3884 | 51.2 |

## EXP-04 Prompt A/B

| Prompt | Correctness | Evidence | Legal | Verifier pass | Latency (s) |
|---|---:|---:|---:|---:|---:|
| A | 0.695 | 0.667 | 0.667 | 0.000 | 23.699 |
| B | 0.433 | 0.333 | 0.333 | 0.000 | 24.547 |

## EXP-05 稀疏反馈

生成 3 条 A/B 比较记录；字段符合 `sparse_feedback.schema.json`。这些记录仅演示人工偏好采集，未触发训练、微调或参数更新。

## EXP-06 Leaderboard

| Rank | 配置 | 综合分 | Verifier | Latency (s) | Tokens |
|---:|---|---:|---:|---:|---:|
| 1 | top12-rerank3-promptA | 64.093 | 0.279 | 24.088 | 10904 |
| 2 | top8-rerank3-promptA | 63.872 | 0.268 | 24.087 | 10904 |
| 3 | top4-rerank3-promptA | 62.582 | 0.203 | 24.086 | 10904 |
| 4 | top4-rerank5-promptA | 57.612 | 0.198 | 24.088 | 11278 |
| 5 | top12-rerank5-promptA | 54.082 | 0.267 | 24.090 | 11650 |
| 6 | top8-rerank5-promptA | 53.878 | 0.256 | 24.088 | 11650 |
| 7 | top12-rerank3-promptB | 37.773 | 0.279 | 24.936 | 10956 |
| 8 | top8-rerank3-promptB | 37.553 | 0.268 | 24.935 | 10956 |
| 9 | top4-rerank3-promptB | 36.263 | 0.203 | 24.934 | 10956 |
| 10 | top4-rerank5-promptB | 31.292 | 0.198 | 24.936 | 11330 |
| 11 | top12-rerank5-promptB | 27.762 | 0.267 | 24.938 | 11701 |
| 12 | top8-rerank5-promptB | 27.559 | 0.256 | 24.936 | 11701 |

## AMD 下一阶段输入

本次 JSON/CSV 已保存 full vs capsule 的 input/output tokens、TTFT、TPOT、总延迟、GPU 利用率、VRAM peak 和 concurrency=1。后续 AMD 优化应在相同模型、温度、请求与硬件下扩展 concurrency 2/4。
