# 动态记忆压缩与稀疏反馈实验报告

所有性能数字均来自本次运行日志；稀疏反馈为明确标记的模拟评审流程，不是法律或保险专家的真实签署意见，也未用于训练或 LoRA。

## MEM-03 完整上下文 Baseline

| 指标 | 结果 |
|---|---:|
| Input tokens | 11807 |
| Output tokens | 388 |
| TTFT | 8939.31 ms |
| TPOT | 40.85 ms/token |
| Total latency | 24.748 s |
| GPU utilization mean/peak | 98.5% / 100% |
| VRAM used peak | 43820 MB |
| Quality / verifier | 89.091 / False |

Baseline 被 Verifier 拦截：模型把 Law ID 写入 Evidence ID；该失败按真实日志保留，没有修饰为通过。

## MEM-04 Case Capsule

| 指标 | 结果 |
|---|---:|
| Input tokens | 8817 |
| Token reduction | 25.32% |
| TTFT | 5512.51 ms |
| TPOT | 40.06 ms/token |
| Total latency | 18.133 s |
| Latency change | -26.73% |
| VRAM peak change | 0 MB |
| Conclusion consistency | 27.86% |

结论一致性采用严格的 Fact/Evidence/Law ID 与审批/不确定性签名比较；它不等同于宽松的语义相似度。

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
| top12-rerank3 | 0.708 | 0.375 | 0.3906 | 55.8 |
| top12-rerank5 | 0.708 | 0.322 | 0.3898 | 53.5 |
| top4-rerank3 | 0.431 | 0.375 | 0.3910 | 40.6 |
| top4-rerank5 | 0.431 | 0.354 | 0.3883 | 39.6 |
| top8-rerank3 | 0.667 | 0.375 | 0.3865 | 53.5 |
| top8-rerank5 | 0.667 | 0.322 | 0.3869 | 51.2 |

## EXP-04 Prompt A/B

| Prompt | Correctness | Evidence | Legal | Verifier pass | Latency (s) |
|---|---:|---:|---:|---:|---:|
| A | 1.000 | 1.000 | 1.000 | 1.000 | 17.817 |
| B | 1.000 | 1.000 | 1.000 | 1.000 | 19.484 |

## EXP-05 稀疏反馈

生成 3 条 A/B 比较记录；字段符合 `sparse_feedback.schema.json`。这些记录仅演示人工偏好采集，未触发训练、微调或参数更新。
- 模拟偏好分布：{"A": 1, "B": 2}。

## EXP-06 Leaderboard

| Rank | 配置 | 综合分 | Verifier | Latency (s) | Tokens |
|---:|---|---:|---:|---:|---:|
| 1 | top12-rerank3-promptA | 90.872 | 0.779 | 18.207 | 10896 |
| 2 | top8-rerank3-promptA | 90.667 | 0.768 | 18.203 | 10896 |
| 3 | top4-rerank3-promptA | 89.342 | 0.703 | 18.208 | 10896 |
| 4 | top4-rerank5-promptA | 84.527 | 0.698 | 18.205 | 11271 |
| 5 | top12-rerank5-promptA | 81.123 | 0.767 | 18.207 | 11642 |
| 6 | top8-rerank5-promptA | 80.911 | 0.756 | 18.204 | 11642 |
| 7 | top12-rerank3-promptB | 80.018 | 0.779 | 19.875 | 10968 |
| 8 | top8-rerank3-promptB | 79.813 | 0.768 | 19.871 | 10968 |
| 9 | top4-rerank3-promptB | 78.488 | 0.703 | 19.875 | 10968 |
| 10 | top4-rerank5-promptB | 73.674 | 0.698 | 19.872 | 11343 |
| 11 | top12-rerank5-promptB | 70.269 | 0.767 | 19.874 | 11714 |
| 12 | top8-rerank5-promptB | 70.058 | 0.756 | 19.871 | 11714 |

## AMD 下一阶段输入

本次 JSON/CSV 已保存 full vs capsule 的 input/output tokens、TTFT、TPOT、总延迟、GPU 利用率、VRAM peak 和 concurrency=1。后续 AMD 优化应在相同模型、温度、请求与硬件下扩展 concurrency 2/4。
