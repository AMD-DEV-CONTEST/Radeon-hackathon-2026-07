> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# vLLM ROCm 换栈可行性报告（Z 报告）

> 本文档只做**不落地**的可行性调查，按 `INSTANCE_FINDINGS_AND_Z_PLAN.md` 第 4 节 Z 清单执行。
> **未安装任何重型包、未改动 `/opt/venv`、未执行任何编译/下载。**
> 全部结论基于：实例只读 SSH 实测 + vLLM/AMD 官方文档与源码 + 社区实测证据。
> 日期：2026-07-28。

> **⚠️ 阵容已终审（2026-07-29，见 `HANDOFF_EXPERT_ROSTER.md` / `bench/LORA_GGUF_GATES.md`）**：下文"三专家覆盖"仍写作 `hermes_s2`(工具) + `fable5`(代码) + 规划自训，二者均已移除——`hermes_s2` 基座静默错配（真基座 `samscrack/Qwen3.6-27B-Opus-CoT-Stage1`）、`fable5` 仓库 404/私有化从未下载。**最终阵容**：`btl3`(工具/代码) + `cybersec`(安全) + `teichai_fable5_plan`(规划) + `rag_n7`(文档)，全部 base == `Qwen/Qwen3.6-27B`。本 Z 报告仅作可行性调查，阵容以执行手册 `PATH_D_IMPLEMENTATION.md`（已更正）为准。

---

## 0. 一句话结论（给决策层）

**在这台实例（Radeon PRO W7900 = RDNA3 / gfx1100，48GB，定制 `torch 2.10.0+rocm7.2.4`）上，path C（vLLM ROCm + Qwen3.6 FP8 + 8ms 热插拔）不可行，且有两个独立的根因级否决点：**

1. **FP8 推理在 RDNA3（gfx1100）上被 vLLM 源码直接 gate 掉** —— `supports_fp8()` 仅对 CDNA（MI300+，gfx9）和 RDNA4（gfx12）返回 True。W7900 是 RDNA3，跑不了 FP8，因此 "Qwen3.6-27B-FP8 / 35B-A3B-FP8 省显存" 的前提在这张卡上不成立。
2. **定制 torch 与 vLLM 预编译 wheel ABI 不兼容** —— 实例的 `torch 2.10.0+rocm7.2.4.git3d3aa833` 是本地自定义 `+rocm` 构建（实测 `torch.version.hip` 为 `None`），而 vLLM ROCm wheel 自带并强绑定特定 torch+ROCm 组合，装预编译 wheel 会覆盖现有 torch 且大概率内核加载失败；只能**源码编译 + 新建隔离 venv**。

**附带的次级否决点**：vLLM 多 LoRA 热插拔延迟是 **30–50ms（冷 swap）到 ~60ms（批内开销）量级**，无法保住现有 peft `set_adapter` ~8ms 的核心卖点。

**推荐**：保留 path A（Qwen3.5-9B + peft 双专家 sygnif+metro，已实测可用）作为底线交付；若坚持"更大基座 + 现成 LoRA"，走 path B（Qwen2.5-7B + peft，生态真实）比 vLLM 务实。**vLLM ROCm 仅在硬件换成 CDNA（MI300 级）时才值得评估。**

---

## 1. Z.1 事实清单逐项查证

### Z.1#1 vLLM ROCm 官方版本矩阵（事实）

- **预编译 wheel 不在 PyPI 主索引，而在 `https://wheels.vllm.ai/rocm/`**。
- 历史上独立的 `vllm-rocm` PyPI 包（0.6.3, 2024-10）已**废弃**，现行是 `vllm` 主包带 ROCm 变体子目录。
- 实测可用的 ROCm 变体（wheel 索引）：

  | 变体 | ROCm 版本 | Python | glibc | 覆盖的 vLLM 版本 |
  |---|---|---|---|---|
  | `rocm700` | 7.0 | 3.12 | ≥2.35 | v0.14.0 – v0.18.0（稳定版） |
  | `rocm721` | 7.2.1 | 3.12 | ≥2.35 | **仅 nightly**（commit 171775f 之后） |
  | `rocm723` | 7.2.3 | 3.12 | ≥2.34 | **v0.26.0**（索引上见到的最新） |

- **关键缺口：没有 ROCm 7.2.4 的预编译 wheel。** 实例系统是 ROCm 7.2.4，但 vLLM 只发布了 7.2.1（nightly）和 7.2.3（v0.26.0）的 wheel。
- 源码编译的最低 ROCm 要求为 **≥6.3**。
- 捆绑的 torch 版本：官方文档未显式声明 wheel 内 torch 版本；据 vLLM CI/PR 证据，ROCm 7.2.x 对应 **torch 2.10**（vLLM 正迁向 2.11+）。

**来源**：
- vLLM ROCm 安装文档：<https://docs.vllm.ai/en/latest/getting_started/installation/gpu/>
- Wheel 索引：<https://wheels.vllm.ai/rocm/vllm>
- PR #38252（ROCm 7.2.1 + torch 2.10）：<https://github.com/vllm-project/vllm/pull/38252>
- 废弃的 `vllm-rocm`：<https://pypi.org/project/vllm-rocm/>

### Z.1#2 实例定制 torch 与 vLLM 的兼容性（事实 + 实测）

**实测（本次只读 SSH，`/opt/venv/bin/python -c "import torch; ..."`）：**
```
torch 2.10.0+rocm7.2.4.git3d3aa833
torch.version.hip  ->  None   # 自定义 +rocm 构建，无标准 HIP 版本属性
GPU[0]: AMD Radeon Graphics  (gfx1100 / W7900 级，见原纪要)
```

**结论：预编译 vLLM ROCm wheel 不能装到这个 torch 上，只能源码编译。**

原因（多重叠加）：
1. vLLM ROCm wheel **自带并强绑定 PyTorch**（文档明示："wheel bundles PyTorch … use the included PyTorch"）。`pip install vllm` 会**覆盖**现有定制 torch。
2. **ROCm 内核 `.so` 在 minor 版本间不保证 ABI 稳定**。实例 torch 基于 ROCm 7.2.4 本地编，而 vLLM wheel 是针对 7.0 / 7.2.1 / 7.2.3 编的 → HIP 内核符号解析大概率失败（`libhiprtc` / undefined symbol）。
3. vLLM 源码 `csrc/torch_bindings.cpp` 对 ROCm 上不同 torch（2.10 vs 2.11）有独立条件编译分支，混用官方 wheel + 定制 torch 属未支持路径。

> 注：即便 `pip` 强行装进去，运行时内核加载失败也几乎必然。此组合**未经 vLLM 验证、不支持**。

**推荐隔离路径（若后续真要试）**：新建 `/persistent/venv_vllm`，从源码编译 vLLM 并显式指定 ROCm 架构 `PYTORCH_ROCM_ARCH=gfx1100`，且**不要复用 `/opt/venv`**（见 §3 红线）。

**来源**：
- vLLM 文档："If you need a different ROCm version or want to use an existing PyTorch, build from source."
- vLLM `csrc/torch_bindings.cpp` 跨 torch 版本条件编译（PR #44334, #44648 ABI 迁移）
- 实例实测：`torch 2.10.0+rocm7.2.4.git3d3aa833`，`torch.version.hip=None`

### Z.1#3 基座选型：Qwen3.6 FP8 在 vLLM ROCm（RDNA3）能否加载（事实，决定性否决）

**决定性事实：vLLM 在 RDNA3（gfx1100）上不支持 FP8。**

vLLM ROCm 平台源码：
```python
@classmethod
def supports_fp8(cls) -> bool:
    return on_gfx9() or on_gfx12x()   # 仅 CDNA(gfx9) 或 RDNA4(gfx12)
```
W7900 = **RDNA3 / gfx1100 → `supports_fp8()` 返回 False**。`torch._scaled_mm`（vLLM 的 FP8 matmul 内核）需要 MI300+ 或 Blackwell，RDNA3 直接报 `fp8e4nv not supported in this architecture`。

社区实测同样确认 RDNA3 上 FP8 KV cache / 前缀缓存崩溃（vLLM #13147）。AMD ROCm 优化文档的 FP8 仅列 MI300X/MI325X/MI350X/MI355X（CDNA）；RDNA3 拿到的是 **W4A16 内核，不是 FP8**。

**显存占用估算（仅权重，不含 KV cache）：**

| 模型 | 精度 | 权重 | 48GB 卡余量 |
|---|---|---|---|
| Qwen3.6-27B | bf16 | ~54 GB | ❌ 装不下 |
| Qwen3.6-27B-FP8 | FP8 | ~28 GB | ⚠️ 装得下但**FP8 跑不了**（gfx1100） |
| Qwen3.6-35B-A3B | bf16 | ~72 GB | ❌ 装不下 |
| Qwen3.6-35B-A3B-FP8 | FP8 | ~36–40 GB | ⚠️ 紧、且 FP8 跑不了 |
| Qwen3.6-27B-**W8A16**（社区 `88plug`） | W8A16 | ~27 GB | ✅ 装得下、能跑（非 FP8） |
| Qwen3.6-27B-**GGUF Q4/Q5** | 4–5bit | ~15–21 GB | ✅ 装得下、能跑（但非 vLLM 原生）

**对 path C 的判定**：
- "Qwen3.6-FP8 在 W7900 上省显存又快" —— **不成立**，因为 FP8 在这张 RDNA3 卡上被 gate 掉。
- bf16 27B (~54GB) 塞不进 48GB；只有 **W8A16（~27GB）或 GGUF Q4/Q5（~15–21GB）** 能上，但这俩要么非 FP8、要么（GGUF）与 vLLM 原生基座/LoRA 体系不兼容（GGUF 需 llama.cpp/Ollama，与 peft/vLLM LoRA 格式不同路）。
- 因此 "用现成 3.6 LoRA（base=27B/35B）" 的前提也连带动摇：你得先真跑一个 27B/35B 基座，而它在 48GB 卡上只有 W8A16/GGUF 形态可行，且 GGUF 不是 vLLM LoRA 的合法 base。

**来源**：
- vLLM ROCm 平台 `supports_fp8()`：<https://github.com/vllm-project/vllm/blob/main/vllm/platforms/rocm.py>
- vLLM #13147（RDNA3 FP8 崩溃）：<https://github.com/vllm-project/vllm/issues/13147>
- RDNA3 FP8 实测日志：<https://llm-tracker.info/_TOORG/vLLM-on-RDMA3>
- vLLM 官方 recipe（27B/27B-FP8）：<https://recipes.vllm.ai/Qwen/Qwen3.6-27B>
- 社区 W8A16：<https://huggingface.co/88plug/Qwen3.6-27B-W8A16>
- AMD ROCm vLLM 优化（FP8 仅 CDNA）：<https://rocm.docs.amd.com/en/latest/how-to/rocm-for-ai/inference-optimization/vllm-optimization.html>

### Z.1#4 现成 LoRA 格式转换（事实，偏乐观但受限于 §Z.1#3）

**好消息**：vLLM **直接接受标准 HuggingFace PEFT LoRA 目录**，无需转换。vLLM 的 `PEFTHelper` 直接解析 `adapter_config.json`（`peft_type: LORA`、`target_modules`、`r`、`lora_alpha`、`bias: "none"`）+ `adapter_model.bin/.safetensors`。不需要 `lora_convert.py`（那是 SGLang/KTransformers 体系，与 vLLM 不通用）。

**坑（若真要跑 vLLM LoRA）**：
- 不支持 DoRA（`use_dora: true` 被拒）。
- 不支持 `modules_to_save`（必须为 `null`）。
- rank 必须 ≤ `--max-lora-rank`，否则静默截断/输出乱码。
- MoE（如 35B-A3B）混 2D/3D adapter 需 `--enable-mixed-moe-lora-format` 并显式声明 `is_3d_lora_weight`，声明错静默乱码。
- `target_modules` 必须匹配模型实际模块名（vLLM 用 `qkv_proj`/`o_proj`/`down_proj` 等后缀）。

**关键约束**：HF 上 Qwen3.6 的现成 LoRA（如 `hotdogs/qwen3.6-27b-*-lora`）**base 都是 27B/35B**。按 §Z.1#3，你在 48GB RDNA3 卡上只能跑 W8A16/GGUF 形态的 27B，而 GGUF 不是 vLLM LoRA 的合法 base —— 所以这些现成 3.6 LoRA 在**这台机器 + vLLM 栈下基本用不上**。

**来源**：
- vLLM LoRA 文档：<https://docs.vllm.ai/en/latest/features/lora/>
- `PEFTHelper` API：<https://docs.vllm.ai/en/stable/api/vllm/lora/peft_helper/>
- MoE LoRA 格式说明：vLLM LoRA 文档 MoE 章节

### Z.1#5 切换延迟实测预期（事实，卖点保不住）

- vLLM 多 LoRA 用**固定 GPU slot + CPU 池 + LRU 驱逐**：adapter 权重需 CPU→GPU 分页搬运。
- **冷 swap（仅在 CPU 池）：~30–50ms（p50）**；仅在磁盘：数百 ms 先入 CPU 再 ~30–50ms 入 GPU；**已在 GPU slot：近零，但每批多 adapter 有 ~60ms 分组 GEMM 开销**。
- **sub-10ms 不可达**（冷 swap）。PEFT `set_adapter` ~8ms 是"权重本就在同一 PyTorch 模型显存里、只翻指针"，与 vLLM 的分页架构本质不同。
- 风险：`max_loras` 设太小 → 工作集超 slot → 缓存抖动 → **p99 TTFT 可冲到 8 秒以上**。经验最优 `max_loras` ≈ 活跃 adapter 数的 90 分位（通常 16–32）。

**来源**：
- 真实多 LoRA 服务报告：<https://dev.to/marcuswwchen/serving-40-lora-adapters-on-one-base-model>
- 基准：<https://github.com/priyaltaneja/multi-lora-serving-benchmark>
- vLLM PR #31317（MoE LoRA B 权重 pinned memory 提速 ~40%）

---

## 2. Z.2 交付物：明确"能 / 不能" + 推荐 + 风险 + 草案

### 2.1 能 / 不能 判定

| 问题 | 判定 | 依据 |
|---|---|---|
| vLLM ROCm 能否装到本实例？ | ⚠️ 仅能**源码编译 + 新建 venv**，预编译 wheel 不行 | §Z.1#1/#2，torch 定制 + 无 7.2.4 wheel |
| Qwen3.6-FP8 能否在 W7900 跑？ | ❌ 不能（RDNA3 被 gate） | §Z.1#3 |
| 48GB 卡能否跑 27B/35B 基座？ | ⚠️ 仅 W8A16(~27GB)/GGUF Q4(~15GB)，且 GGUF 非 vLLM base | §Z.1#3 |
| 现成 3.6 LoRA 能否用？ | ❌ 基本用不上（base 不匹配本机可行形态） | §Z.1#4 |
| 8ms 热插拔卖点能否保住？ | ❌ 不能（vLLM 30–50ms+） | §Z.1#5 |

**总判定：path C（vLLM ROCm + Qwen3.6）在这台实例上不可行。** 两个根因级否决（RDNA3 无 FP8、定制 torch 无兼容 wheel）已足够，次级否决（延迟、LoRA base 不匹配）进一步确认。

### 2.2 推荐基座 / 栈（务实排序）

1. **path A（最快交付，推荐底线）**：留 **Qwen3.5-9B + peft 双专家（sygnif+metro）**。已实测：基座加载 11.6s/18.17GB、生成 14.83 tok/s、router 正确、e2e 带行号引用、Gradio 200。唯一真问题是 deltacoder 权重坏（结构不兼容）→ 直接剔除 deltacoder，保留 sygnif+metro 即干净双专家。**零风险、零安装。**
2. **path B（若坚持"更大 + 现成 LoRA"）**：换 **Qwen2.5-7B + peft**，HF 有真实生态（如 `Yaxin1992/qwen2.5-7b-grpo-tool-calling` 等 base=2.5-7B 的工具/LoRA），bf16 ~15GB，48GB 卡可多专家。代价：基座/LoRA/文档全换血。延迟仍是 peft 8ms 量级（卖点保住）。
3. **path C（仅当硬件升级到 CDNA/MI300 级时再评估）**：那时 FP8 可行、vLLM ROCm wheel 匹配度更高，再走 vLLM + Qwen3.6-FP8 + 现成 LoRA 路线。

### 2.3 风险清单（写进报告，与 §3 红线呼应）

- **R1（硬件错配）**：W7900 是 RDNA3，vLLM FP8 仅 CDNA/RDNA4 → 任何 FP8 方案在此卡无效。
- **R2（环境污染）**：预编译 vLLM wheel 会覆盖 `/opt/venv` 的定制 torch → 必须新建隔离 venv，否则破坏现有可用 9B 环境（底线）。
- **R3（显存）**：48GB 跑 27B bf16 装不下；FP8 又跑不了 → 只剩 W8A16/GGUF，且与 vLLM LoRA 体系不对齐。
- **R4（延迟退化）**：vLLM 多 LoRA swap 30–50ms+，若 slot 配置不当 p99 可达 8s，核心卖点（8ms）丢失。
- **R5（LoRA base 不匹配）**：现成 3.6 LoRA base=27B/35B，与本机可行基座形态不一致 → 实际不可用。
- **R6（数据丢失）**：实例 destroy = 全盘清空；一切写入 `/persistent` 并尽快 `git push` 远程（本地项目**已是 git 仓库**，`master` 分支缺 remote；实例侧 `/persistent/screwshell` 仍非 git 仓库，需 `git init`）。

### 2.4 若后续真要试 vLLM 的安装/验证步骤草案（仅草案，Z 阶段不执行）

> 仅作未来参考。Z 阶段**不执行**。所有操作须在新 venv、不碰 `/opt/venv`。

```bash
# 0. 红线：绝不 pip install 进 /opt/venv
# 1. 新建隔离 venv
python3 -m venv /persistent/venv_vllm
source /persistent/venv_vllm/bin/activate

# 2. 源码编译 vLLM（针对 gfx1100），不要装预编译 wheel
export PYTORCH_ROCM_ARCH=gfx1100
git clone https://github.com/vllm-project/vllm && cd vllm
pip install -r requirements/rocm.txt
python setup.py develop

# 3. 验证 FP8 是否被 gate（预期在 W7900 上返回 False）
python -c "from vllm.platforms import get_current_platform; print(get_current_platform().supports_fp8())"

# 4. 用 W8A16（非 FP8）试跑 27B，验证显存与多 LoRA（仅当 R3 可接受时）
#    vllm serve 88plug/Qwen3.6-27B-W8A16 --enable-lora --max-loras 16 ...
```

---

## 3. Z.3 风险红线（已遵守 / 须持续遵守）

- ✅ **Z 阶段未动 `/opt/venv`**：本报告零安装、零改码；只读 SSH 仅查询 `torch.__version__` 等，未写任何文件。
- ⚠️ **若后续真装 vLLM**：必须新建隔离 venv（如 `/persistent/venv_vllm`），绝不污染现有 peft 9B 环境（R2）。
- ⚠️ **实例 destroy = 全盘清空**：一切写入 `/persistent`，并尽快 `git push` 远程（本地项目**已是 git 仓库**，`master` 分支缺 remote —— 只 `git remote add` 即可，无需 `git init`；实例侧 `/persistent/screwshell` 仍需 `git init` + 远端）。
- ⚠️ **不做未经验证的"8ms 保住"承诺**：vLLM 路径下该卖点必然退化（R4）。

---

## 4. 待用户决策（接续 `INSTANCE_FINDINGS_AND_Z_PLAN.md` 第 5 节）

- **A（推荐）**：留 Qwen3.5-9B + peft 双专家（sygnif+metro），最快交付，剔除坏权重 deltacoder。
- **B**：换 Qwen2.5-7B + peft 重做（生态真实但换血，卖点保住）。
- **C**：换栈 vLLM ROCm + Qwen3.6 —— **本报告指出在此硬件上不可行**，除非升级到 CDNA（MI300 级）显卡。

> 当前停在 Z 报告阶段，未执行任何安装/改码。结论：path C 在此实例不可行，建议 path A 或 path B。

---

## 5. 补充：llama.cpp 能否热切 LoRA？（用户追问，Z 阶段追加调研）

> 用户问"那 llama.cpp 能切热 lora 吗"。结论是：**能，且延迟接近 PEFT 8ms，且绕开了 vLLM 在 RDNA3 上跑不了 FP8 的死穴。** 这把"更大基座 + 热 LoRA"的目标从 path C（vLLM，不可行）变成了一条**在本机可行**的新路径（暂称 path D）。

### 5.1 核心答案

**llama.cpp 支持运行时热切 LoRA，且 base 常驻显存、不重载模型。**

- 应用机制（PR #8332 后）：LoRA 以 `Wx + B(Ax)` **逐前向计算**，非加载时合并进权重。基座权重始终在 VRAM。
- 热切方式：启动时用 `--lora a.gguf --lora b.gguf --lora-init-without-apply` 预载全部 adapter，运行时通过 `POST /lora-adapters`（`[{"id":0,"scale":1.0},{"id":1,"scale":0.0}]`）或请求体内 `"lora"` 字段切换。
- **切换本质**：只改 `llama_context` 里 LoRA 的 scale 值 + 触发一次调度器 reserve 重算，**不卸载/重载模型**。

### 5.2 延迟（vs PEFT 8ms）

| 场景 | 延迟 | 说明 |
|---|---|---|
| 预载后只切 scale（权重已常驻显存） | **亚毫秒级（<1ms）** | 基座常驻，仅改 scale + 调度 reserve；PEFT `set_adapter` ~8ms 是同一量级区间（均远快于 vLLM 分页 swap），并非"亚毫秒 vs 8ms 矛盾" |
| 首次访问（从盘读 ~500MB GGUF LoRA） | **12–18ms** | 受 NVMe/磁盘 I/O 主导（Medina 14B 实测，RTX 3090/3060 等） |
| PEFT `set_adapter` | ~8ms | 所有 adapter 已在 VRAM，纯指针翻转 |

**结论**：预载后热切与 PEFT 8ms 同级（理想亚毫秒）；即便含首次磁盘读取也仅 12–18ms，对"每步切换一个专家"的 MoL 场景完全可接受，**核心卖点（≈8ms 热插拔）在 llama.cpp 上保得住**。

> 口径澄清（与 `PATH_D_IMPLEMENTATION.md` 阶段 5 一致）：「亚毫秒」指预载后仅切 scale；「8ms」指 PEFT 同级区间；验收上限按连续 50 次切换 p50 ≤ 20ms。20–50ms 为灰色带，需排查是否误触发从盘重载。

### 5.3 与 PEFT 的关键差异（架构级 caveat）

- **无真正的 per-request 并发隔离**：同一 batch 内不同 LoRA 的请求**不会被一起批处理**（ngxson 在 issue #10374 明确："both requests are processed in the same batch" 时做不到）。即一个 batch = 一种 LoRA 配置。
- **对本项目的影响**：MoL Router 本就是"每步激活一个专家、顺序路由"（见 README 架构），请求大多是顺序/按专家分组的 → 该限制**不构成障碍**。若未来要同一 batch 内混跑多个专家，则 llama.cpp 不满足，PEFT/vLLM 也不满足（vLLM 同样 batch 级）。
- 旧版"加载时合并"路径（`llama_model_apply_lora_from_file`）已废弃、且要 60s+ 重算量化，**禁止用于热切**。

### 5.4 格式：PEFT LoRA 需转 GGUF（一次性离线转换）

- llama.cpp **不直接吃** PEFT safetensors，要用 `convert_lora_to_gguf.py` 转成 GGUF adapter：
  ```bash
  # 注意：参数是 --base-model（指向本地 GGUF/权重目录），不是 --base-model-id 传 HF id（会报错）
  python convert_lora_to_gguf.py ./my-peft-adapter --base-model /path/to/Qwen3.6-27B-Q4_K_M.gguf --outtype f16
  ```
- 转换器读 `adapter_config.json` + `adapter_model.safetensors`，按 Qwen 张量命名映射到 GGML 约定，**保留 A/B 分解形式**，输出 `adapter.type="lora"` 的 GGUF。
- **转换雷区（影响全部 Qwen3.6 LoRA）**：`convert_lora_to_gguf.py` 对 Qwen3.6 家族（含稠密 27B）的 linear-attention 目标模块（`out_proj` / `in_proj_qkv` 等）会抛 `_reorder_v_heads → NotImplementedError`（issue #21125）；修复 PR #24627 截至调研时**尚未合并**。已有成功先例（`hotdogs/qwen3.6-27b-fable5-lora`、`Extr/qwen36-blueprint-lora-gguf` 发布者均成功转出 GGUF LoRA），做法通常是**训练时限制 target_modules 避开 `out_proj`**，或手动转换，或**直接用 repo 已附带的 GGUF LoRA**（fable5 即此情况，零转换风险）。详见 `PATH_D_IMPLEMENTATION.md` 第 0 节与阶段 2。
- **项目既有 PEFT adapter（sygnif/metro，base=Qwen3.5-9B）虽可被 `convert_lora_to_gguf.py` 转换（脚本对 Qwen3.5/3.6 命名有感知），但 path D 决策已主动弃用 3.5 旧专家、统一到 base=Qwen3.6-27B 生态**——不复用、不再维护旧 LoRA（见 `PATH_D_IMPLEMENTATION.md` 阶段 2 红线）。
- 这是**一次性离线步骤**，不要求在实例上装重型包（转换脚本只需 transformers，本机或别处跑均可）。

### 5.5 栈契合度（本机 W7900 / gfx1100 / 48GB / ROCm 7.2.4）

| 项 | 状态 | 来源 |
|---|---|---|
| Qwen3.6-27B 在 llama.cpp | ✅ 支持（`qwen35` arch），`convert_hf_to_gguf.py` 原生支持，官方 GGUF 已发布 | PR #19468 / Qwen 官方 llama.cpp 文档 |
| GGUF base 上多 LoRA | ✅ 多个 `--lora` + `--lora-init-without-apply` + `POST /lora-adapters` 切换 | llama.cpp server README |
| ROCm/HIP on gfx1100 (W7900) | ✅ 编译 `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100`；ROCm 7.2+ 原生支持 gfx1100 | AMD ROCm llama.cpp 安装文档 |
| Qwen3.6-27B Q4_K_M(~16.8GB, unsloth)/Q5_K_M(~18GB) 48GB | ✅ 装得下，余量大，可多 LoRA | 社区 GGUF 惯例（unsloth Q4_K_M 实测 16.8GB） |
| **RDNA3 FP8 死穴** | ✅ **绕开**：GGUF Q4/Q5 在 RDNA3 原生运行，不依赖 FP8（vLLM 的否决点在此失效） | — |

### 5.6 对决策的影响

- **path D（llama.cpp + Qwen3.6-27B GGUF + 热 LoRA）在本机可行**，且同时满足"更大基座 + 热插拔 ≈8ms + 现成 3.6 生态"三个诉求——这正是 path C 想做但被 RDNA3/vLLM 卡死的目标。
- **基座选型（依据 HF 实测生态）**：选 **Qwen3.6-27B（稠密，非 MoE）**，不选 35B-A3B MoE——后者现成 LoRA 生态极稀疏且转换 bug 更麻烦。27B 稠密有两个专家 LoRA 现成可热切（工具调用 `samscrack/Qwen3.6-27B-Hermes-S2-LoRA`、代码 `hotdogs/qwen3.6-27b-fable5-lora` 且自带 GGUF），但**规划/推理专家无干净独立 LoRA，必须自训**（base=Qwen3.6-27B，r=32~64，避开 out_proj）或暂用基座原生 thinking 顶替。详见 `PATH_D_IMPLEMENTATION.md` 第 0 节。
- 代价：① PEFT LoRA 需离线转 GGUF（一次性，且须规避 issue #21125 转换 bug）；② 失去 PEFT 的 per-request 并发隔离（本项目 MoL 路由顺序执行，无影响）；③ 要从 `transformers+peft` 架构迁移到 llama.cpp server / `llama_cpp` 绑定，需重写 MoL 推理核心的 adapter 切换调用（但 Router 逻辑可保留）。
- **推荐更新**：原 Z 报告 §2.2 的 path 排序应追加 path D 作为"换更大基座且保住热插拔"的**首选务实路线**；path C（vLLM）仅在升级到 CDNA(MI300) 显卡后才值得。

> 本节为 Z 阶段可行性追加，未执行任何安装/转换/改码。path D 的可行性结论基于官方文档、PR 与社区实测，待正式实施时再用真机基准复核 12–18ms 数字。

---

## 6. path D 落地草案（已抽离为独立执行手册）

path D 的完整执行步骤、命令、验收门槛、风险与回退，已抽取为独立手册：

> **`docs/PATH_D_IMPLEMENTATION.md`** —— 勾选式执行清单（阶段 0–6），每阶段完成判据、红线。已确定走 **llama.cpp + Qwen3.6-27B GGUF（稠密，非 MoE）**（即原 D2），手册内不再保留 D1 选项，也不选 35B-A3B MoE。

摘要（详见手册）：
- **已决策**：基座换 **Qwen3.6-27B GGUF**（unsloth Q4_K_M ≈16.8GB），LoRA 用 base=Qwen3.6-27B 的 GGUF。**四专家覆盖（最终阵容，2026-07-29）**：工具/代码 `badtheorylabs/BTL-3`(btl3) + 安全 `hotdogs/qwen3.6-27b-cybersecurity-lora`(cybersec) + 规划 `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA`(teichai_fable5_plan) + 文档 `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7`(rag_n7)，全部 base==`Qwen/Qwen3.6-27B`。*注：本 Z 报告写作时曾写 `hermes_s2`(工具)+`fable5`(代码) 方案，二者已证实不可用并移除——见上方 banner。* 现有 sygnif/metro（base=Qwen3.5-9B）因不匹配直接弃用。
- **阶段顺序（3a 前置）**：① git init+远端（源码 git，GGUF/LoRA 走 LFS/对象存储防 destroy）→ ② 实例先建 `/persistent/venv_llamacpp` + 装 llama.cpp（阶段 1–2 复用其依赖）→ ③ 准备基座 GGUF(3.6-27B) → ④ 准备 LoRA（工具+代码现成；规划自训）→ ⑤ 启 server 预载 LoRA（绑定 127.0.0.1 + SSH 隧道）→ ⑥ 热切基准(验收 p50≤20ms) → ⑦ 迁移 `mol_engine` 后端。
- **红线不变**：隔离 venv、不碰 `/opt/venv`、产物落 `/persistent`、先 git/LFS 防 destroy。

> 本节仅作索引；执行以 `PATH_D_IMPLEMENTATION.md` 为准。
