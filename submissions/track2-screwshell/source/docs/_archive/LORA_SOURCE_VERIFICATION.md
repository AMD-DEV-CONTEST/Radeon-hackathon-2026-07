> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# LoRA 真实来源核实报告（hermes_s2 / teichai）— samscrack 基座不匹配隐患

> 生成时间：2026-07-28。核实者：WorkBuddy。
> 核实方法：直接拉取 HuggingFace 上游 `adapter_config.json` 原始 JSON + 模型卡（model card），
> 不依赖本项目文档断言（手册已多次出现"声称 vs 实测不符"，如 fable5 的 401、转换墙）。

---

## 0. 一句话结论

- **teichai**：✅ 真实来源与文档一致，基座 = `Qwen/Qwen3.6-27B`，**与项目基座精确匹配，无隐患**。
- **hermes_s2**：⚠️ 真实来源是 `samscrack/Qwen3.6-27B-Hermes-S2-LoRA` 没错，但它的**真实基座不是** `Qwen/Qwen3.6-27B`，
  而是 `samscrack/Qwen3.6-27B-Opus-CoT-Stage1`（一个 stage-1 推理合并模型）。**用户担心的"samscrack 基座不匹配隐患"是真实存在的，且当前已悄悄活在 path-D 的运行配置里。**

---

## 1. hermes_s2 核实（⚠️ 不匹配，隐患确认）

**上游原始 `adapter_config.json`（samscrack/Qwen3.6-27B-Hermes-S2-LoRA）：**

```json
"base_model_name_or_path": "samscrack/Qwen3.6-27B-Opus-CoT-Stage1",
"auto_mapping": { "base_model_class": "Qwen3_5ForCausalLM", ... },
"r": 16, "lora_alpha": 16,
"target_modules": ["down_proj","out_proj","v_proj","o_proj","q_proj","k_proj","up_proj","gate_proj"]
```

**模型卡原文（决定性证据）：**

> **Lineage:** `Qwen/Qwen3.6-27B` → stage-1 reasoning LoRA → merge → **this LoRA (tool-calling SFT)**.
> It is **not** standalone — apply it to the stage-1 reasoning base below.
> **Limitations:** Useless without the right base — apply specifically to
> `samscrack/Qwen3.6-27B-Opus-CoT-Stage1`.

**完整血缘链：**

```
Qwen/Qwen3.6-27B (干净基座，本项目 GGUF 来源)
   └─ stage-1 推理 LoRA (r=64) → merge → samscrack/Qwen3.6-27B-Opus-CoT-Stage1 (BF16 合并推理模型, ~52GB, 公开, Apache-2.0)
         └─ stage-2 工具调用 LoRA (r=16) = samscrack/Qwen3.6-27B-Hermes-S2-LoRA  ← 我们的 hermes_s2
```

**关键判定：**

1. hermes_s2 的 LoRA delta 是相对 **Opus-CoT-Stage1 权重**训练的，不是相对干净 `Qwen3.6-27B`。
2. 项目 path-D 的 server 用干净 `Qwen3.6-27B-Q4_K_M.gguf` 作基座 + 挂 hermes_s2（见 `bench/benchmark_pathd.json` 的 `server_args`）→ **把 stage-2 delta 加到了错误的基座上**，输出不是文档宣称的 Hermes 工具调用，而是"干净基座 + (Hermes − Opus-CoT)"的错位叠加。
3. **隐患是"静默"的**：hermes_s2 的架构是 `Qwen3_5ForCausalLM`，与干净 `Qwen3.6-27B` 架构一致 → llama.cpp 加载**不报错**、能跑、能出 token。所以 handoff 里"hermes_s2 先做工具选择推理"的观测是在**错误基座**上测的，不能当作验收通过信号。这正是"隐患"最危险的地方——没有报错，但行为不对。

---

## 2. teichai 核实（✅ 匹配，无隐患）

**上游原始 `adapter_config.json`（TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA）：**

```json
"base_model_name_or_path": "Qwen/Qwen3.6-27B",
"auto_mapping": { "base_model_class": "Qwen3_5ForCausalLM", ... },
"r": 64, "lora_alpha": 64,
"target_modules": "<full-linear 正则，含 out_proj / in_proj_qkv 等>"
```

- 真实基座 = `Qwen/Qwen3.6-27B`，**与项目基座精确一致** ✅。无基座不匹配。
- 唯一已知问题是转换墙（`out_proj` reshape，`issue #21125`）——已在 handoff §7 打补丁清除，属构建问题，**非基座匹配问题**，已解决。
- 模型卡自承"小数据集实验品、部分任务退化"，这是质量风险（需在阶段 5 验收），不是来源/基座风险。

---

## 3. 系统设计层面的根因（拔高看）

path-D 手册 §0 的选型表断言"三专家 base 精确 = `Qwen/Qwen3.6-27B`"，**对 hermes_s2 是错的**。
而手册 §2.3 自己把 `samscrack/Qwen3.6-27B-Opus-CoT-Stage1` 排除为"已 merge、不能热切"——
可 hermes_s2 **恰恰依赖这个被排除的合并模型作基座**。手册自我矛盾，且 `router.py` 的注释把真实基座藏了起来（只写 `samscrack/Qwen3.6-27B-Hermes-S2-LoRA, r16`），导致 mismatch 一路混到运行配置。

**核心冲突**：项目假设"所有专家热切到同一个共享干净基座上"。但 hermes_s2 的真实基座是
中间产物 Opus-CoT-Stage1，teichai 的真实基座是干净 Qwen3.6-27B。**单个共享基座无法同时满足两者**——
这才是反复出"能加载但跑不对"类问题的流程缺口：选型阶段没有把"LoRA 的真实 base_model"逐项拉上游核实，
只信了文档里的选型表。

---

## 4. 修复路径（供拍板，按开箱即用程度排序）

| 方案 | 做法 | 代价 | 是否保住"单共享基座"设计 |
|---|---|---|---|
| **A（推荐）** | 把工具专家换成**基座本就是干净 `Qwen/Qwen3.6-27B`** 的工具调用 LoRA；或把 hermes_s2 的 stage-2 在干净基座上**重训**（需 hermes-agent-traces 数据集 + Unsloth） | 找/训一个 LoRA | ✅ 保住 |
| B | 整个 server 基座换成 **Opus-CoT-Stage1 的 GGUF** + hermes_s2 → hermes 正确 | Opus-CoT-Stage1 公开但仅 BF16(~52GB)，需自转 GGUF（Q4≈16–18GB，W7900 48GB 放得下+hermes LoRA） | ❌ teichai 反过来不匹配 |
| C | 用合并版 FP8 `samscrack/Qwen3.6-27B-Opus-CoT-S1-Hermes-S2-SFT` 作工具技能的固定基座（Hermes 已烤进权重、不可热切），teichai 另起一个干净基座 server | 放弃单共享基座，跑两套 base profile | ❌ 放弃 |
| D | 接受错配的 hermes_s2（现状） | 零 | — 但不推荐：模型卡明说 "Useless without the right base" |

> 注：Opus-CoT-Stage1 仓库**公开可下**（Apache-2.0），所以方案 B 在可达性上没有 401 阻塞；阻塞只在"要自转 GGUF"。

**建议**：若要保住 path-D"单共享基座 + 热切"的核心卖点，走 **方案 A**——要么找基座为干净 Qwen3.6-27B 的工具 LoRA，要么在干净基座上重训 hermes_s2 的 stage-2。否则就得接受方案 B/C 的多基座现实。

---

## 5. 立即动作（已做 / 待做）

- ✅ 已修正 `screwshell/core/router.py` 注释：hermes_s2 行补上"真实基座 = Opus-CoT-Stage1，切勿挂到干净基座"的告警，消除隐患藏身处。
- ⚠️ `bench/benchmark_pathd.json` 里 hermes_s2 的 `behavior_diff` 是在错配基座上测的，**不能作为验收依据**，建议重测或标注。
- ⏳ 等拍板采用哪一方案后，再改 `router.py` 的 `DEFAULT_SKILL_MAP` / server 启动基座。当前 `skill_map` 的 `"tool": "hermes_s2"` 暂不动（属设计决策，非单一注释可定）。
