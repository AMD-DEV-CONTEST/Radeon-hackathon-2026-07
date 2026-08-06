> English version: [../en/MODEL_TRACK.md](../en/MODEL_TRACK.md)

# 模型侧 —— 在 AMD Radeon 上训练、部署并优化

本页是模型侧工作的索引。下列每个数字都有 [`model/`](../../model/README.md) 中的保存证据支撑，没有一项是估计值。复现说明会区分需要 GPU 的重新运行与针对保存结果的离线验证。

## 在 Radeon 上完成了什么

| 阶段 | 产物 | 硬件 |
| --- | --- | --- |
| SFT 训练 | 基于 `unsloth/Qwen3-32B-bnb-4bit@7f721e74` 的 LoRA `checkpoint-000119` | AMD Radeon gfx1100、ROCm、119 optimizer steps |
| 部署 | OpenAI 兼容服务，服务身份与训练产物哈希绑定 | 同一张卡 |
| 推理优化 | 真流式 / TTFT + lean LoRA 解码路径，实机 A/B | 同一张卡 |
| 第二个优化案例 | 现成 80B 单卡部署：KV 精度 + offload 深度 | 另一台 gfx1100 主机 |

adapter 身份 `4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf` 在四个独立来源上一致：训练冻结清单、训练机原件、本地备份、ModelScope 平台侧哈希。

## 结果一 —— SFT 模型确有提升

Base vs SFT，同一冻结 held-out Test、同一服务栈、temperature=0、模型身份逐回合哈希锁定：

| 指标 | Base | SFT |
| --- | ---: | ---: |
| 严格工具调用一致（名称+参数） | 37.2% | **67.8%** |
| 工具名称一致 | 39.7% | **76.9%** |
| 全回合任务合同 | 0/49 | **15/49** |

代价如实披露：SFT 的 token 与延迟约为 Base 的 2.1 倍。

## 结果二 —— 这个差距决定真实任务能否完成

上面的数字是与冻结参考的一致性。把两个模型都放到真实 `rdk-agent` 五节点工作流、面向真实 RDK X5，只换模型、其余不变，请求同一个能力（`wave-right-hand`）：

| | Base | SFT |
| --- | --- | --- |
| 工作流节点完成度 | 3 / 5（60%） | **5 / 5（100%）** |
| 结局 | 卡在 CLI 真机验收，14 分 25 秒后被终止 | **验收通过**，用时 4 分 04 秒 |

Base 不是崩溃。它返回了验收节点无法解析的结果——`Agent 的结构化结果无法解析`——而这恰是严格工具调用指标所衡量的能力。离线数字就是实机结果背后的机理。物理位移仍留待人类目视确认，且这是每臂一个任务而非抽样成功率；两条限制均写在 [`model/AGENT_E2E.md`](../../model/AGENT_E2E.md)。

## 结果三 —— 该模型的推理在 Radeon 上被优化

同一 base、同一 adapter、同一 GPU、temperature=0，每臂 88 次试验。基线为未改动的生产推理路径：

| 指标 | 基线 | 优化后 |
| --- | ---: | ---: |
| 用户可见 TTFT p50 | 17.41 s | **8.26 s**（2.11×） |
| 用户可见 TTFT p95 | 83.97 s | **12.89 s**（6.52×） |
| Decode | 6.54 tok/s | **6.72 tok/s**（+2.8%） |
| 与基线输出一致性 | — | **88/88 逐字节一致** |

两个上限更高的候选（把 LoRA 合并进 NF4 base；`torch.compile` + StaticCache 解码）已实现并实机测量，**基于证据被否决** —— 二者均如实入档而非隐去。

环境：gfx1100、ROCm 7.2.1、torch 2.9.1+rocm7.2.0、transformers 5.5.0、peft 0.19.1、bitsandbytes 0.50.0。

## 结果四 —— 同一 GPU 架构，另一个优化层

上面那个优化刻意不动数值：32B 是全部质量主张的载体，验收门槛设成了"输出逐字节一致"，这决定了它的天花板。为了展示能力区间的另一端，另一台采用相同 `gfx1100` GPU 架构的主机部署了现成的 `Qwen3-Next-80B-A3B-Instruct`（官方 Q4_K_M GGUF，ROCm/HIP `llama.cpp`）——**48.4 GB 权重跑在 48 GiB（51.5 GB）显存的单卡上**——这里允许拿 KV 精度做交换：

| 指标 | Q8 KV / 45 层 | Q4 KV / 47 层 | 变化 |
| --- | ---: | ---: | ---: |
| Prefill（2,332 tok） | 1,271.45 tok/s | 1,397.39 tok/s | +9.9% |
| Decode（64 tok） | 37.19 tok/s | **49.82 tok/s** | **+34.0%** |
| TTFT 中位 | 2,021.26 ms | 1,808.76 ms | −10.5% |
| 平均墙钟延迟 | 3,727.88 ms | 3,084.19 ms | −17.3% |

同一份权重、同样 262,144-token 配置上下文、同样请求形态、两臂均开 Flash Attention；每臂 1 次预热 + 5 次正式测量。优化后的配置仍然通过结构化 `tool_calls`、`role=tool` 续写与 42,028-token needle 检索三个 canary。

两个案例合起来覆盖了 ROCm 部署可调优的两个层：

| | 自训练 32B SFT | 现成 80B |
| --- | --- | --- |
| 优化层 | serving —— 流式、LoRA 执行 | runtime —— KV 精度、offload 深度 |
| 约束 | 输出必须逐字节不变 | KV 精度可以交换 |
| 头条数字 | 用户可见 TTFT **2.11×** | decode **+34.0%** |

```bash
cd model/radeon-optimization/qwen3-next-80b && python3 verify_results.py   # 从十条记录重算保存的聚合指标与 delta，无需 GPU
```

这个 80B 是现成模型：既不是本团队训练的模型，也不是产出训练数据的教师。模型产物固定为 48,410,988,384 B，SHA-256 `d103b273…`。

## 复现

无 GPU（约 5 分钟）—— 从封存的原始记录重算 A/B 全表：

```bash
cd model/benchmark/runs/model-ab-heldout113-20260805-v2
sha256sum -c SHA256SUMS
python3 ../../recompute_ab.py \
  --test ../../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl \
  arms/base.raw.jsonl arms/sft.raw.jsonl summary.json
```

有 Radeon GPU —— 一条命令完成下载公开权重、fail-closed 校验 adapter 哈希并起服务：

```bash
cd model/model/serving && bash deploy.sh      # DRY_RUN=1 只校验主机与制品，不启动任何服务
```

在该主机上重跑推理 A/B：

```bash
cd model/radeon-optimization/qwen3-32b-agentic-sft
python3 benchmark.py --run-dir run-full       # 重新生成 results.json
```

## 证据索引

| 主题 | 路径 |
| --- | --- |
| 模型侧总览 | [`model/README.md`](../../model/README.md) |
| 全部结果一页 | [`model/RESULTS.md`](../../model/RESULTS.md) |
| claim → 证据 → 哈希 地图 | [`model/EVIDENCE_MAP.md`](../../model/EVIDENCE_MAP.md) |
| 端到端 Agent 运行，SFT vs Base | [`model/AGENT_E2E.md`](../../model/AGENT_E2E.md) |
| 推理优化代码与 A/B | [`model/radeon-optimization/qwen3-32b-agentic-sft/`](../../model/radeon-optimization/qwen3-32b-agentic-sft/README.md) |
| 80B 单卡案例 | [`model/radeon-optimization/qwen3-next-80b/`](../../model/radeon-optimization/qwen3-next-80b/README.md) |
| 部署与身份校验 | [`model/model/serving/README.md`](../../model/model/serving/README.md) |

## 边界

重放一致性衡量的是与 held-out 教师轨迹的合同一致，其本身不证明 Agent 端到端成功或板端物理执行。Test 集在评测完成后为复现而公开，不应再作为无污染评测集使用。推理优化已由上述 A/B 验证，但尚未接入线上服务路径。`model/radeon-optimization/qwen3-next-80b/` 中的 Qwen3-Next-80B 单卡案例使用的是现成模型，并非本团队训练的模型。
