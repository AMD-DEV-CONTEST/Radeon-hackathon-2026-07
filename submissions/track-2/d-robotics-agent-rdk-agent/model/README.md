> English version: [README.en.md](README.en.md)

Author: 韩兆鸣；汪明


# RDK MagicBox 蒸馏闭环(distill)

**在 AMD Radeon(gfx1100, ROCm)上训练出的 Qwen3-32B Agentic SFT 模型,经哈希绑定的身份链部署为推理服务,在评测时保持隔离、评测后为复现而公开的教师轨迹 Test 上把严格工具调用一致率从 37.2% 提升到 67.8%。**本仓库提供模型侧各环节的可验证证据。

## 结果(先看这个)

Base vs SFT,同一冻结 Test 前缀(49 任务 / 每臂 170 回合)、同一服务栈、temperature=0、双臂模型身份逐回合哈希锁定:

| 指标 | Base | SFT | Δ |
|---|---:|---:|---:|
| 严格工具调用一致(名称+参数) | 37.2% | **67.8%** | +30.6pp |
| 工具名称一致 | 39.7% | **76.9%** | +37.2pp |
| 全回合任务合同 | 0/49 | **15/49** | +30.6pp |
| 最终回合干净收尾 | 89.8% | **98.0%** | +8.2pp |

配对结论:40 个回合仅 SFT 答对,仅 3 个回合仅 Base 答对。提升不在"会不会输出结构化调用"(两臂都 ~95%),而在**选对工具、给对参数、调用对次数**。代价:SFT 生成约 2.1 倍 token/延迟。完整口径、成本与边界:[benchmark/runs/…/RESULTS.md](benchmark/runs/model-ab-heldout113-20260805-v2/RESULTS.md)。**全部模型侧结果(SFT 效果 + 训练收敛 + 部署身份 + Radeon 推理优化)汇总一页:[RESULTS.md](RESULTS.md)。**

## 闭环链路与证据

```text
 数据管线              训练               产物身份             部署               评测
 examples/magicbox-    examples/qwen3-    adapter sha256      model/             benchmark/
 data-pipeline/        32b-training/      4dcee691…f20bf      served-model-      runs/…-v2/
 npm run check         119 steps          四方一致:            manifest.json      49 任务 A/B
 逐字节确定性 ✔        CE 1.152→0.594     冻结清单/训练机/      health+进程参数+   身份逐回合
 fail-closed 负向 ✔    Phase1/2 PASS ✔    本地备份/ModelScope   base/SFT diff ✔   锁定 ✔
```

## 公开制品(ModelScope)

| 制品 | 地址 | 关键校验 |
|---|---|---|
| LoRA adapter(checkpoint-000119) | [ming01/Qwen3-32B-Agentic-SFT-r1-v3](https://modelscope.ai/models/ming01/Qwen3-32B-Agentic-SFT-r1-v3/summary) | `adapter_model.safetensors` 268,555,264 B,SHA-256 `4dcee691…f20bf`,平台侧哈希与训练冻结清单逐字节一致 |
| 训练数据(脱敏 train+validation) | [ming01/RDK-Agentic-SFT-Sanitized-v1](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/files) | schema 与本仓库逐字节一致;Test 在评测时 historically held out,评测完成后已随本仓库公开用于复现 |

基座模型:`unsloth/Qwen3-32B-bnb-4bit@7f721e74`(4-bit base + LoRA 在线加载,非合并量化交付)。

## 三层复现(按你手头的硬件走到最深一层)

**Tier 0 — 普通电脑,约 5 分钟,不调模型:**

```bash
# 数据管线闭环:重导出 → 复验 → 与钦定输出逐字节比对 → 负向测试 → secret 扫描
cd examples/magicbox-data-pipeline && pip install -r requirements.txt && npm run check

# 训练证据链哈希对账
cd ../qwen3-32b-training && python3 verify_subset.py

# A/B:证据字节完整性 + 从原始记录重算全表(应与已发布 summary 逐项一致)
cd ../../benchmark/runs/model-ab-heldout113-20260805-v2
sha256sum -c SHA256SUMS
python3 ../../recompute_ab.py \
  --test ../../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl \
  arms/base.raw.jsonl arms/sft.raw.jsonl summary.json
```

**Tier 1 — 有 Radeon GPU,约 20 分钟:**下载公开 base+adapter、一条命令起服务、健康检查显示 `checkpoint-000119`、行为探针复现 base/SFT diff。完整步骤:[model/serving/README.md](model/serving/README.md)。

**Tier 2 — 有 RDK 板:**在 `rdk-agent` 自己的模型配置中接入 Radeon 服务暴露的 OpenAI-compatible API,再运行现有 `rdk-agent → sophonctl → RDK` 链路;物理效果以当次板端观察为准。

训练不要求复跑:公开 adapter 即 demo 与 A/B 所用制品;冻结训练代码、配置与一条示例命令在 `examples/qwen3-32b-training/`,历史事实为 119 optimizer steps、AMD Radeon gfx1100 单卡。完整重训是可选项,因硬件与软件版本差异,数值结果可能不同。

## 目录导览

| 目录 | 内容 | 一句话 |
|---|---|---|
| `examples/magicbox-data-pipeline/` | 产线原件代码 + 冻结小输入 + 钦定输出 | 数据是怎么产出并被校验的 |
| `examples/qwen3-32b-training/` | 逐字节冻结训练代码 + 紧凑结果证据；完整历史见固定 tag | 训练实现、收敛与产物哈希 |
| `model/` | 身份链 + base/SFT 行为 diff + 服务时间线 | 部署的就是训练出的那份权重 |
| `model/serving/` | 服务端原件(证据同哈希)+ serve.sh + 依赖 | Tier 1:自己把它跑起来 |
| `benchmark/` | 冻结重放评测器 + sealed 运行证据 | SFT 比 base 强多少、代价几何 |
| `data/releases/…/agentic/test.jsonl` | historically held-out 冻结 Test(评测后公开) | 评测输入,SHA `d1e1856b…5e283`,供评委独立重评分 |
| [`AGENT_E2E.md`](AGENT_E2E.md) | 真实 agent 工作流在 RDK X5 实机上的端到端运行,SFT vs Base | SFT 5/5 节点验收通过;Base 停在 3/5 |
| `radeon-optimization/qwen3-32b-agentic-sft/` | **本模型**在 gfx1100 上的推理优化 + 实机 A/B | 用户可见 TTFT 2.11×,输出逐字节一致 |
| `radeon-optimization/qwen3-next-80b/` | Qwen3-Next-80B 单卡部署优化(独立案例) | decode +34%,可离线重算 |
| `EVIDENCE_MAP.md` | claim → 证据文件 → 哈希 总索引 | 全仓一张地图 |

## 边界(公开表述以此为准)

重放一致性衡量的是与 historically held-out 教师轨迹的合同一致,**不等于** Agent 端到端成功、板端执行或物理效果;后者必须由当次 Agent、`sophonctl` 与板端观察共同证明——该证明即 [`AGENT_E2E.md`](AGENT_E2E.md),其为每臂一次运行而非抽样成功率,且物理位移仍留待人类目视确认。Test 在评测完成后为复现而公开,不应再作为未来无污染评测集使用。评测前缀为确定性有序前缀而非随机抽样,不含 promoted controlled-actuation 任务。训练数据含 848 条带标记的 promoted 样本(一行过滤器可回退,详见数据集 README)。训练代码为 fail-closed 已验证快照,硬绑定原主机与环境；完整历史训练证据固定在 tag [`model-evidence-full-20260806`](https://github.com/wm19999/rdk-sophon/tree/model-evidence-full-20260806/model/examples/qwen3-32b-training)。

## 许可说明

本仓库当前未声明统一许可证;在仓库所有者完成许可证确认前,源代码保留所有权利。公开模型、数据集与第三方依赖分别遵循其各自仓库所列许可。
