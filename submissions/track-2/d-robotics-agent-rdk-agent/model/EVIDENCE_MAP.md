> English version: [EVIDENCE_MAP.en.md](EVIDENCE_MAP.en.md)

# EVIDENCE MAP — claim → 证据 → 哈希

全仓唯一的证据总索引。每一行是一个可独立核验的 claim。

## 数据

| Claim | 证据 | 关键哈希/数字 |
|---|---|---|
| 数据管线确定性且 fail-closed | `examples/magicbox-data-pipeline/`(`npm run check` 五步全绿) | 11 个输出文件与 `expected/` 逐字节一致;15 测试;secret 扫描零命中 |
| 每个示例文件来源可追溯 | `examples/magicbox-data-pipeline/source-manifest.json` | 26 条目:verbatim/subset/sanitized 逐条标注 |
| 正式发布数据的构成与风险 | `data/releases/rdk-sft-v1-20260803/RELEASE_README.orig.md` | 精选 327 + promoted 848(带 6 个标记键,可过滤回退);其中 428 条证据类失败已标注 |
| historically held-out Test 评测后公开 | `data/releases/rdk-sft-v1-20260803/agentic/test.jsonl` | 评测时与训练隔离;评测完成后随本仓库发布用于复现;113 任务,3,562,357 B,SHA `d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283` |
| 公开数据集(脱敏) | [ModelScope: ming01/RDK-Agentic-SFT-Sanitized-v1](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/files) | train `40522e4e…`、validation `68ac3053…`(平台侧);schema 与本仓库同源 `19854de1…` |
| 教师 lineage | 每条样本 metadata 的 `session_file` 与 provenance 标记 | 1175/1175 条可追溯至 d-robotics-glm/glm-5.2 教师会话 |

## 训练

| Claim | 证据 | 关键哈希/数字 |
|---|---|---|
| 训练按冻结合同执行完成 | `examples/qwen3-32b-training/evidence/training-summary.json` + [完整证据 tag](https://github.com/wm19999/rdk-sophon/tree/model-evidence-full-20260806/model/examples/qwen3-32b-training) | 119 optimizer steps,948 micro-windows,最终 checkpoint `COMPLETE` |
| 学习曲线 | `examples/qwen3-32b-training/evidence/validations/validation-step-*.json`(0/30/60/90/119) | validation mean CE 1.1516 → 0.5936630333639499 |
| 精简训练树字节级可对账 | `examples/qwen3-32b-training/{source-manifest.json,verify_subset.py}` | 主树代码与精简证据逐文件 SHA 核验；被移出的历史证据由固定 tag 承接 |
| 基座模型来源固定 | `examples/qwen3-32b-training/artifacts/model-acquisition/qwen3-32b-bnb-7f721e74-verification.json` | `unsloth/Qwen3-32B-bnb-4bit@7f721e74a6a8…` |

## 模型产物与部署身份

| Claim | 证据 | 关键哈希/数字 |
|---|---|---|
| adapter 权重即训练产物 | `model/SHA256SUMS` + [ModelScope 模型仓库](https://modelscope.ai/models/ming01/Qwen3-32B-Agentic-SFT-r1-v3/summary) | `adapter_model.safetensors` SHA `4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf`,268,555,264 B,四方逐字节一致;公开 `adapter_config.json` 仅做 base 路径与 revision 的可移植性规范化 |
| 服务加载的就是该 adapter | `model/served-model-manifest.json` + `model/deployment_manifest.orig.json` | 部署清单绑定主机指纹(u-7701-ae3eba8a/boot_id/GPU uid)与 adapter SHA;/health 报告 checkpoint-000119 |
| adapter 行为上确实生效 | `model/ab-probe/`(6 探针,temperature=0) | 能力探针(identity/math/tool_call)逐字一致,行为探针 3/3 可见差异 |
| 服务身份漂移风险已记录 | `model/served-model-manifest.json` 的 `serving_timeline_utc` 与 `known_footgun` | base 服务曾以 `--accepted-model-alias` 接受 SFT 模型名,但响应 `model` 与 `/health` 如实记录实际加载形态 |

## 评测(Base/SFT A/B)

| Claim | 证据 | 关键哈希/数字 |
|---|---|---|
| SFT 显著提升工具调用一致性 | `benchmark/runs/model-ab-heldout113-20260805-v2/{RESULTS.md,summary.json}` | 严格一致 37.19%→67.77%;工具名 39.67%→76.86%;全回合合同 0/49→15/49;配对 40:3 |
| 评测身份逐回合锁定 | 同 run 的 `arms/*.manifest.json` + 每条 raw 记录的 `response_models` | 服务进程参数含 `--adapter checkpoint-000119`;6 项 `--expect-file-sha256` 含 adapter `4dcee691…` |
| 证据不可篡改 | `SHA256SUMS` + `arms/*.recovery-seal.json` | `sha256sum -c` 一键核验;interrupted 臂经一次性只读封存 |
| 代价如实披露 | `RESULTS.md` Observed cost | SFT 延迟/token ≈ 2.1×;final-text 严格相等两臂均 0(不宣称语义正确性) |
| 独立重评分 | `benchmark/recompute_ab.py` + Test + Base/SFT raw | 从公开输入与逐回合响应重建参考并逐项比对 `summary.json` |

## 端到端 Agent 实机运行(RDK X5)

| Claim | 证据 | 关键哈希/数字 |
|---|---|---|
| 离线差距决定长程任务能否跑完 | `AGENT_E2E.md` + `assets/agent-e2e-sft-vs-base.png` | 同 agent、同板、同任务,仅切换模型:SFT 5/5 节点验收通过,用时 4 分 04 秒;Base 停在 3/5,14 分 25 秒后被终止 |
| Base 的失败方式与预测一致 | 同截图中的失败文本 | `Agent 的结构化结果无法解析` —— 验收节点无法解析结构化结果,而这正是 SFT 所针对的能力 |
| 无静默换模型 | 同截图中的运行横幅 | `模型: d-robotics-glm/Qwen3-32B-Agentic-SFT-r1-v3`、`模型回退: 无` |
| 不宣称物理动作 | 同次运行中 Agent 自己的报告 | 退出码 0 仅证明命令链路成功,不证明物理位移正确;仍需人类目视确认 |

## Radeon 推理优化

| Claim | 证据 | 关键哈希/数字 |
|---|---|---|
| 主 32B 模型推理优化有效 | `radeon-optimization/qwen3-32b-agentic-sft/{README.md,runtime.py,benchmark.py,results.json}` | 同 base + adapter `4dcee691…` + 同 GPU,每臂 88 次:用户可见 TTFT p50 17.41s→8.26s(2.11×),p95 6.52×,decode +2.8% |
| 该优化不改变输出 | `results.json` → `baseline_vs_optimized_output_agreement` + `quality_gates` | 88/88 输出逐字节一致;门禁全过;0 失败/超时/截断 |
| 被否决方案如实入档 | `radeon-optimization/qwen3-32b-agentic-sft/README.md` §5 + `results.json` → `boundaries` | LoRA 合并进 NF4(delta 低于量化步长,cosine 0.006)与 `torch.compile`+StaticCache(3–6k prompt 下更慢)均已实现、实测、否决 |
| 80B 单卡部署优化有效 | `radeon-optimization/qwen3-next-80b/{README.md,results/ab-20260730.json}` | Q4 KV + 47 层 offload:decode +34.0%,TTFT −10.5%;`verify_results.py` 重算十次测量全部一致 |
| 优化不破坏功能 | 同 README 的 canary 记录 | 结构化 tool_calls、tool continuation、42,028-token needle 检索通过 |
| 模型来源固定 | README 记录的模型指纹 | `Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf` 48,410,988,384 B,SHA `d103b273…` |

## 工程教训(如实入档)

- **服务身份漂移**:评测器首批记录即抓获"请求 SFT 名、base 应答"(2026-08-05);因此公开保留响应 `model` 与 `/health` 作为实际服务形态证据。
- **严格 fail-closed 的代价与价值**:评测臂绑定服务进程实例,跨重启不可续跑——三个半途臂作废重跑,换来每条记录的身份可证明。
- **多操作者协调**:同一训练机上并行操作导致两次服务切换对撞;结论:评测期资源必须单一 owner。
