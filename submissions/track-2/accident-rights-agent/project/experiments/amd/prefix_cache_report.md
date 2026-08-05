# AMD-01 Prefix Cache 报告

重复案件第二问 TTFT 从 9.002s 降至 0.104s，改善 98.8%。
- Baseline second-question TTFT: 9.002298003062606
- Optimized second-question TTFT: 0.10388815309852362
- Improvement: 0.988459818474885
- vLLM log peak hit rate: 99.4
- 两组使用同一模型、同一 Case Capsule 前缀、不同第二问和相同输出上限。
