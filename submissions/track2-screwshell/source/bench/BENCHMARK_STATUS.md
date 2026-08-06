# Benchmark Status — 引用任何数字前先读本文

> **权威运行数据在 `benchmark_pathd.json`**（path-D / llama.cpp / Qwen3.6-27B）。
> 热切控制面延迟：**均值 0.65 ms**（每专家 0.5–0.8 ms，n=3）。
> decode：基座 26 tok/s，+LoRA 23–26 tok/s。模型加载 9 s，显存 ~21/48 GB。
> 本文件夹里**其余文件都是 9B-PEFT 历史基线**——请勿抄进 path-D 文档、视频或 PPT。

## 当前权威数字（path-D，见 `benchmark_pathd.json`）
在实例实测（W7900，ROCm 7.2.4，llama-server，挂载 4 个 LoRA，temp=0，关思考）：

| Metric | Value |
|---|---|
| 模型加载（16.8 GB Q4_K_M，全量进 GPU） | 9 s |
| 显存（基座 + 4 adapter 常驻） | 21 / 48 GB |
| Decode，基座 | 26 tok/s（prefill ~100 tok/s） |
| Decode，LoRA 激活 | 23–26 tok/s |
| 热切（`POST /lora-adapters` scale 切换，n=3/专家） | **均值 0.65 ms**，每专家 0.5–0.8 ms |
| 行为差异（temp=0，同 prompt，每专家 3 条领域 prompt） | 4 专家全部与基座 DIFFERS；无空输出/退化 |

集成注意（app/demo 必须处理）：
- `--lora` 重复传已废弃（只认最后一个）→ 用逗号分隔 `--lora a.gguf,b.gguf`。
- Qwen3.6 是推理模型 → `reasoning_content` 可能占满 `max_tokens` 导致 `content` 为空。
  关思考（`chat_template_kwargs.enable_thinking=false`）或调大 `max_tokens`。
- 经 SSH 执行 `pkill -f llama-server` 会杀掉你自己的会话（命令行字符串匹配）→ 用 `pkill -x`。

## 9B-PEFT 历史基线（勿引用）
| File | 是什么 | Caveat |
|---|---|---|
| `benchmark_mol.py` | 旧 PyTorch/PEFT `MoLEngine`（Qwen3.5-9B + sygnif/DeltaCoder/metro）的 A/B 脚本 | 面向 PEFT `set_adapter`；对 path-D 核心不可跑 |
| `benchmark_mol.json` / `.csv` | 上面的原始结果 | 含 `mol_switch_cost_ms_mean: 8.04` —— **已废弃** |
| `day4_e2e.json` | 9B-PEFT 栈的端到端运行 | path-D 之前；引用已退役专家 |

### 为什么 9B 基线不再适用
- 基座：9B bf16（PEFT）→ 27B Q4_K_M GGUF，经 llama.cpp 服务。
- 专家：sygnif / DeltaCoder / metro（9B PEFT；DeltaCoder 是**损坏** LoRA）→
  定稿的 **4 专家** btl3 / cybersec / teichai_plan / rag_n7（27B GGUF）。
  注：曾尝试过一个*中间* 27B 阵容（hermes_s2 / fable5 / teichai）随后**废弃**——
  `hermes_s2` 是基座静默错配（真实基座 = Opus-CoT-Stage1，不是 Qwen3.6-27B），
  因此其任何"行为差异"测量都**无效、作废**。
- 切换机制：PEFT `set_adapter()`（8.04 ms）→ llama.cpp LoRA adapter 切换（~0.65 ms）。
  8.04 ms / 1,305× 数字**不沿用**。

README §5 / SPEC §5 已采用上面的 path-D 数字。
