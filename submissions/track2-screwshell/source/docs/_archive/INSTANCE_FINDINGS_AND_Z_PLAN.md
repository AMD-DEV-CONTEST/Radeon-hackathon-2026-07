# ScrewShell 实例实测纪要 & 换栈可行性调查（Z 报告前置文档）

> 本文档由 2026-07-28 的一次对话沉淀而来。目的：把已实地验证的事实、已排除的死路、待做的 Z 报告清单固化下来，供新对话直接接续，不再重复探查。
>
> 所有"实测"结论均来自当天 SSH 连实例（root@36.150.116.206:31033）的真实输出，非推测。

---

## 0. 云端实例真实状态（实测，非交接文档所述）

交接文档 `instance-handoff.md` 与实例**实际状态多处不符**，以实测为准：

| 项目 | 交接文档说 | 实测真实 |
|---|---|---|
| GPU | gfx1100 / ~24GB | `0x744b` = Radeon W7900 级 gfx1100，**VRAM 51522MB ≈ 48GB** |
| 预置模型 | Qwen3-8B | **Qwen3-8B 不存在**；`/models/unsloth/Qwen3.5-9B` **存在** |
| torch/transformers/peft | 未装 | `/opt/venv` 已装：`torch 2.10.0+rocm7.2.4`、`transformers 5.5.0`、`peft 0.19.1` |
| /persistent | 空 | 已有 `hf-home/`、`loras/`、`screwshell/`、`start-ssh.sh` |
| LoRA | 未提及 | `/persistent/loras/` 下 **sygnif / metro / deltacoder 三个 adapter 均存在**，各有 adapter_config.json |

实例 SSH：`ssh -p 31033 root@36.150.116.206`（本机私钥 `C:\Users\dd\.ssh\id_rsa` 已授权；端口 31033，不是 31076）。
HF 直连不通，实例用镜像需 `export HF_ENDPOINT=https://hf-mirror.com`。

---

## 1. 现有 MoL 在实例上"能跑但 LoRA 是坏的"（核心问题）

### 1.1 已跑通的部分（day1/day2/day4 留有的 JSON 产物证实）
- 基座 Qwen3.5-9B 加载 11.6s，占 18.17GB，生成 14.83 tok/s ✅
- day1 实测热切换 8.5 / 10.2 / 9.8 ms（README 写 8.04ms 量级真实）✅
- day2 router 正确路由 metro/deltacoder/sygnif，switch 7~11ms ✅
- day4 e2e 真实读取 `demo_workspace/docs/migration_plan.md` 并给出**带行号引用**答案（RAG→证据链路通）✅
- Gradio UI 在 :7860 启动成功（HTTP 200）✅

### 1.2 致命问题：LoRA 权重大量 MISSING（被随机初始化）
`ui.log` 中 PEFT LOAD REPORT 铺天盖地 `MISSING`：deltacoder 的 `in_proj_qkv`/`o_proj`/`gate_proj` 等、metro 的 `up_proj`/`down_proj`/`q_proj` 等。
**含义**：这些 LoRA 权重没从 checkpoint 载入，是 newly initialized（随机）。因此"多专家切换"的演示是**假的**（实际接近基座单打 + 部分层被随机权重污染）。

### 1.3 根因（实测定位）
- `screwshell/core/mol_engine.py` 的加载写法：首个 adapter 用 `PeftModel.from_pretrained` 包基座，后续用 `model.load_adapter(...)`。
- deltacoder 的 `target_modules` 含 **GDN/Mamba 风格层名**（`in_proj_qkv`/`in_proj_z`/`in_proj_a`/`in_proj_b`/`out_proj`），**Qwen3.5-9B 是标准 transformer，无这些层** → deltacoder **整组 MISSING**。
- 加入 deltacoder 后触发 PEFT 层重建，把 sygnif/metro 的标准层权重也污染成 MISSING（多 adapter 串扰）。

### 1.4 单 adapter 实测验证（写临时脚本 /tmp/verify_lora.py 实测）
- **sygnif**：256 个 LoRA 参数，**zero_params=0** → 干净加载 ✅（base 匹配）
- **metro**（路径 `/persistent/loras/metro/adapter`）：256 参数，**zero_params=0** → 干净加载 ✅
- deltacoder：结构不兼容，必 MISSING ❌

**结论**：sygnif + metro 是真能用的双专家；deltacoder 是"找错基座"的坏权重。

---

## 2. 围绕"换基座 / 换栈"的实地搜索结论（全部来自 HF 镜像 curl 实测）

### 2.1 Qwen3.5-9B
- **HF 上无公开 Qwen3.5-9B 基座，也无任何 base=Qwen3.5-9B 的社区 LoRA**。
- 实例上的 sygnif/metro 能用，是因为它们**本就按这个私有/定制基座训的**（主办方或之前会话所留），非 HF 随便下。

### 2.2 Qwen3-8B
- **官方无纯文本 Qwen3-8B-Instruct**（只有 Qwen3-VL-8B 多模态和 gguf）。
- 搜到的 Qwen3-8B LoRA 全是下载量 0~7 的个人随意 SFT，无工具/代码/规划类专家。→ 堵死。

### 2.3 Qwen3.6 系列（用户多次询问"3.6 有小的吧""5060 能部署"）
- **官方(Qwen/)发布的 3.6 只有**：`Qwen3.6-35B-A3B`(MoE)、`Qwen3.6-27B`、`Qwen3.6-27B-FP8`、`Qwen3.6-35B-A3B-FP8`。**最小 27B**。
- 社区小尺寸（0.6B/1.7B/4B/8B/3B/1.5B/Coder/Next）**全部搜不到**。
- HF 上的 Qwen3.6 LoRA 全是 **base=27B/35B** 的（角色扮演/推理/语言类，无 agent 专家），如 `hotdogs/qwen3.6-27b-mythos5k-lora` 等。
- "5060 能部署 3.6" 只能是 **27B 的 2~4bit GGUF（llama.cpp/Ollama）**，与本项目 `transformers+peft` 架构**不兼容**。
- **结论**：在"保留 peft/MoL 架构"前提下，3.6 死路（最小 27B 原生 bf16 ~54GB 塞不下 48GB 卡 + GGUF 不兼容 peft）。

### 2.4 Qwen2.5-7B
- **有真实生态**：如 `Yaxin1992/qwen2.5-7b-grpo-tool-calling(-v2)` 是 base=Qwen2.5-7B 的工具调用 LoRA。
- bf16 ~15GB，48GB 卡轻松多专家。→ 唯一"公开基座 + 现成专家 LoRA"都成立的选项，但需**换血重做**（基座、LoRA、文档全改）。

### 2.5 热插拔框架对比（技术常识 + 已实测）
| 框架 | 多 LoRA 切换 | 延迟量级 | AMD/ROCm |
|---|---|---|---|
| transformers+peft `set_adapter` | 指针翻转 | ~8ms（已实测） | ✅ 已跑通 |
| vLLM `add_lora`/slot | 预编译 slot 近零拷贝 | ~0~几 ms（理论） | ⚠️ ROCm 支持挑剔，需特定 torch/rocm 组合 |
| llama.cpp `lora_adapter` | apply 部分权重 | 几十~几百 ms | ⚠️ ROCm 多 adapter 坑多 |

**关键点**：热插拔不是 peft 独有；vLLM ROCm 多 LoRA 可兼顾"快+省"，但 LoRA 须转成 vLLM 格式，且基座须 vLLM 支持的格式。

---

## 3. 用户最终目标（对话结尾明确）

> **保留 8ms 级热插拔 + 换更大更好的基座 + 用现成 LoRA**

技术栈收敛方向：**vLLM ROCm 多 LoRA**（最贴合：快+省+多 LoRA+可挂原生权重格式的 3.6 基座）。

---

## 4. 待做：Z 报告（新对话执行）

Z = **先出不落地的可行性报告**，不装重型包、不碰 /opt/venv。

### Z.1 必须查清的事实（按优先级）
1. **vLLM ROCm 官方版本矩阵**：vLLM 哪个版本支持 ROCm 7.2 + 什么 torch 版本？有没有预编译 wheel（`vllm-rocm` / AMD 维护分支）？还是必须源码编？
2. **实例 torch 2.10.0+rocm7.2.4 与 vLLM 的兼容性**：该定制 torch 能否装 vLLM？还是必须新建 venv 配官方 ROCm torch？
3. **基座选型**：Qwen3.6-27B-FP8 / Qwen3.6-35B-A3B-FP8 在 vLLM ROCm 上能否加载？显存占用（48GB 卡余量）？
4. **现成 LoRA 格式转换**：HF 上 Qwen3.6 的 LoRA（如 hotdogs/qwen3.6-27b-*）转 vLLM 格式的可行性与工具链。
5. **切换延迟实测预期**：vLLM ROCm 多 LoRA 热插拔能否接近 8ms（决定核心卖点是否保住）。

### Z.2 交付物
- 一份 `docs/VLLM_ROCM_FEASIBILITY.md`：明确"能/不能换 vLLM 栈"，给出推荐基座 + LoRA 来源 + 风险清单 + 若可行则给出安装/验证步骤草案。
- 若 vLLM ROCm 不可行，明确退路（路径 2：peft + Qwen3.6-35B-A3B 原生 bf16 验证；或路径 A：留 9B 双专家）。

### Z.3 风险红线（写进报告）
- 不在 Z 阶段动 `/opt/venv`（现有 peft 9B 可用环境是底线）。
- 若后续真装 vLLM，须新建隔离 venv（如 `/persistent/venv_vllm`），不污染现有环境。
- 实例 destroy = 全盘清空；一切写入 `/persistent`。本地项目**已是 git 仓库**（`master` 分支，缺 remote —— 只 `git remote add` 即可，无需 `git init`）；实例侧 `/persistent/screwshell` 仍非 git 仓库，需 `git init` + remote 防丢。

---

## 5. 遗留待决决策（新对话接续时向用户确认）
- A：留 Qwen3.5-9B + peft 双专家（sygnif+metro），最快交付。
- B：换 Qwen2.5-7B 重做（生态真实但换血）。
- C（用户倾向）：换栈到 vLLM ROCm + Qwen3.6，用现成 3.6 LoRA。
- 当前停在 Z 报告阶段，未执行任何安装/改码。

---

## 6. 实例路径速查
- 基座：`/models/unsloth/Qwen3.5-9B`
- LoRA：`/persistent/loras/{sygnif,metro,delta_coder}`（metro 实际在 `metro/adapter/` 子目录，mol_engine._find_adapter_config 会 walk 找到）
- 已部署代码：`/persistent/screwshell/app/`
- 运行产物：`/persistent/screwshell/{day1_smoke.json,day2_router_demo.json,day4_e2e.json,ui.log}`
- venv：`/opt/venv`（peft 栈，勿动）；建议新 venv 放 `/persistent/venv_vllm`
- SSH 探活命令参考：`ssh -i ~/.ssh/id_rsa -p 31033 root@36.150.116.206 "rocm-smi --showmeminfo vram; ls /models/unsloth"`
