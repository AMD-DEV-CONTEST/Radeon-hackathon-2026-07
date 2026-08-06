> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# path D 执行手册：llama.cpp + Qwen3.6-27B GGUF + 热 LoRA

> 本手册从 `VLLM_ROCM_FEASIBILITY.md` 第 5–6 节抽取、独立成册，供**逐阶段执行**使用。
> **所有命令均为草案，未执行。** 每阶段独立可回退。
> **红线（务必遵守）**：① 新建隔离 venv，绝不碰 `/opt/venv`；② 一切产物落 `/persistent`；③ 实例 destroy = 全盘清空，先 `git init` + 远端再落产物；④ 不在 Z 阶段安装/编译。
> **目标**：用 llama.cpp server 跑 **Qwen3.6-27B（稠密，非 MoE）GGUF** 基座，预载多个 GGUF LoRA（base=Qwen3.6-27B），运行时 `POST /lora-adapters` 热切。延迟口径见阶段 5。以此替换现有 `transformers+peft` 的 MoL 推理核心。
> **基座选型已决策（依据 HF 实测生态调研）**：确定走 llama.cpp + **Qwen3.6-27B（稠密）**。不选 35B-A3B MoE 的理由：35B 的现成 LoRA 生态极稀疏（连代码专家都没有可热切的现成 LoRA），且 MoE 权重转换 bug 更麻烦；27B 稠密有两个专家 LoRA 现成可热切、转换更简单。现有 sygnif/metro 因 base=Qwen3.5-9B 不匹配，直接弃用。

> **⚠️ 阵容已终审（2026-07-29，见 `HANDOFF_EXPERT_ROSTER.md` / `bench/LORA_GGUF_GATES.md`）**：本手册阶段 2 写作时仍以 `hermes_s2`(工具) + `fable5`(代码) 为假设，二者均已从阵容清除——`hermes_s2` 被查出基座静默错配（真基座 `samscrack/Qwen3.6-27B-Opus-CoT-Stage1`）、`fable5` 实测 404/私有化从未下载成功。**最终阵容**：`btl3`(工具/代码) + `cybersec`(安全,新增) + `teichai_fable5_plan`(规划) + `rag_n7`(文档,回退=base)，全部 base 上游核验 == `Qwen/Qwen3.6-27B`。本手册的启动命令与 `DEFAULT_SKILL_MAP` 示例已按最终阵容更正；其余 `hermes_s2`/`fable5` 叙述为历史过程记录，勿当作现状。

---

## 0. 基座与 LoRA 选型结论（先读，避免走错）

**基座 GGUF（推荐）**：`unsloth/Qwen3.6-27B-GGUF` 的 `Qwen3.6-27B-Q4_K_M.gguf`（**16.8 GB**，质量/体积最优）；备选 `bartowski/Qwen_Qwen3.6-27B-GGUF`（Q4_K_M ≈ 17.98 GB）。W7900 48GB 上 16.8GB 基座 + 多 LoRA 常驻余量充足。

**四专家 LoRA 覆盖（base 精确 = `Qwen/Qwen3.6-27B`）**：

| 专家槽 | 现成 LoRA（base 精确匹配） | 状态 |
|---|---|---|
| 工具调用 | `samscrack/Qwen3.6-27B-Hermes-S2-LoRA`（r=16，Hermes `<tool_call>` 格式） | PEFT，转 GGUF 即用 |
| 代码 / Agent | `hotdogs/qwen3.6-27b-fable5-lora` v3.0（r=64） | ~~**repo 直接附带 GGUF LoRA，drop-in，零转换风险**~~ ❌ **已失效**：该 repo 实测 404/私有化（gated 401），从未成功下载，fable5 已从阵容清除。代码/Agent 位改用 `badtheorylabs/BTL-3`（见 §6 阵容）。 |
| 规划 / 推理 | ⚠️ **白嫖优先，无干净独立 LoRA** | 已排除 merge/OOM 的 `samscrack/Opus-CoT-Stage1`、`kai-os/Opus4.6-reasoning`。**候选**：`TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA`（r=64，规划向实验品，转 GGUF 试）；`hotdogs/fable5` 兼测规划行为。都不行则退回**基座原生 thinking** 顶替；自训为质量上限（非必须） |

> **诚实预期**：工具调用 + 代码两个专家有现成可热切 LoRA；规划/推理专家无干净现成 LoRA，但采用 **B+' 策略**——先白嫖 TeichAI（零自训成本）试错，不行退回基座 thinking，工期不增。自训仅当白嫖与基座顶替均不满足质量时再启动。**不要假设"社区三件套直接跑通"。**

**转换雷区（影响全部 Qwen3.6 LoRA）**：llama.cpp `convert_lora_to_gguf.py` 对 Qwen3.6 家族（含稠密 27B）的 linear-attention 目标模块（`out_proj` / `in_proj_qkv` 等）会抛 `_reorder_v_heads → NotImplementedError`（issue #21125）。修复 PR #24627 **截至调研时尚未合并**。已有成功先例（`hotdogs/fable5-lora`、`Extr/blueprint-lora-gguf` 发布者均成功转出 GGUF LoRA），做法通常是**训练时限制 target_modules 避开 `out_proj`**，或手动转换。阶段 2/3 必须确认 llama.cpp 版本并处理此坑。

---

## 1. 执行清单（勾选式）

- [ ] 阶段 0：本机 + 实例侧 `git init` + 远端（防 destroy 丢产物，注意大文件用 LFS/对象存储）
- [ ] 阶段 3a（前置）：实例先建 `/persistent/venv_llamacpp` + 装 llama.cpp（阶段 1–2 复用其依赖）
- [ ] 阶段 1：准备基座 GGUF（Qwen3.6-27B，unsloth Q4_K_M）
- [ ] 阶段 2：准备 LoRA（工具 hermes_s2 + 代码 fable5 现成；规划优先白嫖 TeichAI/Fable-5-Experimental，转 GGUF 试，不行退回基座 thinking）
- [ ] 阶段 3b：编译 llama.cpp（HIP, gfx1100）— 已随 3a 装好，此处验证
- [ ] 阶段 4：启 `llama-server` 预载多 LoRA（绑定 127.0.0.1）
- [ ] 阶段 5：热切基准验收（见延迟口径）
- [ ] 阶段 6：迁移 `mol_engine` 后端 + Router 适配

---

## 0.1 执行者切分（本机 Windows vs 远程 GPU 实例）—— 开工前必读

> 本文档阶段 1–5 的全部命令**必须在远程 GPU 实例执行**，本机（Windows，无 ROCm/W7900）**执行不了**。本机当前能做的只有两件事：阶段 0 本机侧 git 远端、阶段 6 纯代码。先确认边界，避免 agent 照文档跑却卡在"本机没有 GPU"。

**远程实例（SSH `root@36.150.116.206 -p 31033`，`/persistent`，W7900 / ROCm 7.2.4）执行：**
- 阶段 0 实例侧：`/persistent` 上 `git init` + LFS 配置 + 远端（大文件走 LFS/对象存储）
- 阶段 1：下载基座 GGUF（`unsloth/Qwen3.6-27B-GGUF` Q4_K_M）
- 阶段 2：下载 LoRA（hermes_s2 / fable5 / teichai）+ 转 GGUF（遇 out_proj bug 按 §0 规避）
- 阶段 3：建 `venv_llamacpp` + 编译 llama.cpp（HIP/gfx1100）
- 阶段 4：启 `llama-server` 预载多 LoRA（127.0.0.1 + SSH 隧道）
- 阶段 5：热切基准 + 规划专家 B+ 验收（curl 实测）

**本机（Windows，D:\ai\screwshell）执行：**
- 阶段 0 本机侧：仓库已在 `master` 分支、**无 remote**，只需 `git remote add origin <远端>`（不要 `git init`，已存在）；本机只 custody 源码/脚本，不碰 GGUF
- 阶段 6：写 `mol_engine_llamacpp.py` + Router 后端切换键，**纯 Python 代码，可本机开发 + 单元测试（见 §阶段 6 的离线自测法）**，无需 GPU

**阻塞点透明化**：阶段 6 的**真机联调**（连实例 server 跑 e2e）依赖阶段 4–5 先完成；但阶段 6 的**代码编写与单测可现在就做**，用 mock HTTP server 或离线 fixture 验证接口契约，不等 GPU。

---

## 阶段 0：固化现有环境（防 destroy 丢失）

**位置：本机（非实例）+ 实例侧各自做**

```bash
# 本机（仓库已存在于 master 分支，实测无 remote —— 只加远端，不要 git init）
cd D:\ai\screwshell
git remote add origin <你的远端，如 git@github.com:you/screwshell.git>
git push -u origin master   # 注意分支是 master，不是 main
```

> ⚠️ **本机侧只 custody 源码/脚本**：GGUF/LoRA 大文件在实例侧走 LFS/对象存储（见下），本机仓库保持轻量，只 push `.py` / `.md` / 配置。

> ⚠️ **大文件警告（修正原文档漏洞）**：GGUF（16.8GB+）/ LoRA（几百 MB）/ 编译产物**绝不能直接 `git push` 到普通 git 远端**——会把仓库撑爆。请改用：① **Git LFS**（`git lfs track "*.gguf"`），或 ② 对象存储 / 分卷备份（如 `rclone` 到 OSS），或 ③ 仅把源码/脚本入 git，大二进制走对象存储。原文档"实例侧也 git init 并 push"的说法对 GGUF 不成立，必须改。
> 实例 `/persistent` 已有 `screwshell/`、`loras/`、`hf-home/`。源码写 `/persistent` 并定期推送；GGUF/LoRA 大文件走 LFS 或对象存储。
> **完成判据**：远端仓库可见源码 commit（本机）；实例侧大文件在 LFS/对象存储可见对应备份。

---

## 阶段 1：准备基座 GGUF

**位置：在实例的隔离 venv `/persistent/venv_llamacpp` 内执行（与 `/opt/venv` 无关，绝不碰它）**

> 转换脚本 `convert_hf_to_gguf.py` 的依赖（transformers / tokenizers 等）在**阶段 3a 安装 llama.cpp 时随 `pip install -r requirements.txt` 一并装好**。阶段 1–2 复用已建好的 `venv_llamacpp`（见清单顺序调整：3a 前置）。若本机/别处已有 transformers 环境也可离线跑，但实例侧统一用 `venv_llamacpp` 最干净。

- 准备 `Qwen3.6-27B` 的 GGUF（**稠密 27B，非 MoE**）：
  - 选项 1（推荐）：直接拉社区已转好的 GGUF：
    - `unsloth/Qwen3.6-27B-GGUF` → `Qwen3.6-27B-Q4_K_M.gguf`（**16.8 GB**，推荐）
    - 备选 `bartowski/Qwen_Qwen3.6-27B-GGUF` → `Q4_K_M.gguf`（17.98 GB）
  - 选项 2（自建）：需先有 HF 原始权重（实例 `/persistent/hf-home` 或镜像拉取），在 `venv_llamacpp` 内转：
    ```bash
    python llama.cpp/convert_hf_to_gguf.py Qwen/Qwen3.6-27B \
        --outtype q4_k_m --outfile /persistent/models/Qwen3.6-27B-Q4_K_M.gguf
    ```
    > Q4_K_M ≈ 16.8GB（unsloth）/ 18GB（bartowski）。W7900 48GB 余量充足（基座 + 多 LoRA 同时常驻无压力）。**注意**：27B 是稠密模型，Q4 体积约 16–18GB；此前文档写"约16GB"对 27B 成立，但"6GB 可部署"是 35B-A3B MoE 的误植，不适用于本基座。

**完成判据**：GGUF 文件落到实例 `/persistent/models/`，`ls -lh` 大小合理（Q4_K_M 应 ~16–18GB 级）。

---

## 阶段 2：准备 LoRA（base=Qwen3.6-27B 的 GGUF LoRA）

**位置：在实例的隔离 venv `/persistent/venv_llamacpp` 内执行（与 `/opt/venv` 无关）**

> **现有 sygnif/metro 弃用**：它们 base=Qwen3.5-9B，与 Qwen3.6-27B 不匹配，**不再转换、不再使用**。本阶段只准备 base=Qwen3.6-27B 的 LoRA。

**2.1 工具调用专家（现成）**
> ⚠️ 历史章节（hermes_s2 已移除，本节工具专家改用 `badtheorylabs/BTL-3`/btl3）。以下 `samscrack/Qwen3.6-27B-Hermes-S2-LoRA` 转换示例仅留作 out_proj reshape 补丁的回溯记录，**不再执行**。
- `samscrack/Qwen3.6-27B-Hermes-S2-LoRA`（r=16，Hermes `<tool_call>` 格式，Apache-2.0）。下载后转 GGUF：
  ```bash
  python llama.cpp/convert_lora_to_gguf.py \
      /persistent/loras/hermes_s2 \
      --base-model /persistent/models/Qwen3.6-27B-Q4_K_M.gguf --outtype f16 \
      --outfile /persistent/loras/hermes_s2/adapter.gguf
  ```
  > **参数修正**：`convert_lora_to_gguf.py` 用的是 `--base-model`（指向本地 GGUF/权重目录），**不是 `--base-model-id` 传 HF id**——原文档 `--base-model-id Qwen/Qwen3.6-27B` 会报错。
  > **转换雷区**：若报 `_reorder_v_heads → NotImplementedError`，说明该 LoRA 的 target_modules 含 `out_proj`/`in_proj_qkv`。GitHub 上的 hotdogs/fable5、Extr/blueprint 发布者均成功转出，做法是训练时避开这些模块。如遇此坑：① 换用已带 GGUF 的 LoRA（见 2.2），或 ② 重训时限制 target_modules，或 ③ 手动合并后离线转。

**2.2 代码 / Agent 专家（~~现成，零转换风险~~ ❌ 已失效）**
> ⚠️ **fable5 已从阵容清除**：`hotdogs/qwen3.6-27b-fable5-lora` 实测 404/私有化（gated 401），repo 内并无可取 GGUF，原"drop-in 零转换"说法不成立。代码/Agent 位现由 `badtheorylabs/BTL-3`（r32/α64，本地转换 GGUF）顶替，见 §6 最终阵容。
- ~~`hotdogs/qwen3.6-27b-fable5-lora` v3.0（r=64，代码+工具+推理，Apache-2.0）。该 repo 已直接附带 GGUF LoRA 权重，下载即可作为 `--lora` 参数使用，无需转换：~~
  ```bash
  # 直接取 repo 内的 adapter.gguf，落到 /persistent/loras/fable5/
  ```
  > 这是规避阶段 2.1 转换 bug 的最稳路径——优先用现成 GGUF LoRA。

**2.3 规划 / 推理专家（白嫖优先，不行退回基座；自训为最终上限）**

> **实测生态结论（HF 调研，2026-04 发布线）**：`Qwen/Qwen3.6-27B` 上**不存在**干净、可热切、通用的规划/编排/任务分解 LoRA。已排除：`samscrack/Qwen3.6-27B-Opus-CoT-Stage1`（已 merge 成权重，不能热切）、`kai-os/Qwen3.6-27b-Opus4.6-reasoning`（OOM 半成品 104/286 步）、`nerkyor/DSV4Pro-Thinking-Distill`（已 merge，仅 GGUF 权重）。samscrack/kai-os 均未发布未 merge 的独立规划 LoRA。

**策略：B+'（零自训成本试错出口）** —— 先白嫖现成候选，不行退回基座 thinking，工期不增；自训留作质量上限路径。

- **候选 1（优先试）**：`TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA`（r=64，full-linear，PEFT，Apache-2.0，base 精确 = `Qwen/Qwen3.6-27B`）。作者宣称"good for planning"，但**小数据集实验品、自承部分任务退化**。转 GGUF 后作为规划专家候选接入热切（见阶段 4）。
- **候选 2（顺带测）**：`hotdogs/qwen3.6-27b-fable5-lora` v3.0 本身含多步 agent 推理/任务分解 traces，其规划行为一并测，若够用可兼当"代码+弱规划"。
- **退回方案（兜底）**：若候选 1/2 规划行为不达标，阶段 4–5 验证期直接让 Router 对"规划"skill 走**基座原生 thinking 模式**（不挂 LoRA / scale=0），不阻塞交付。
- **自训方案（质量上限，非必须）**：以 `Qwen/Qwen3.6-27B` 为 base，r=32~64，**target_modules 避开 `out_proj`/`in_proj_qkv`**（防转换 bug），用规划/推理 SFT 数据训 PEFT LoRA，再按 2.1 转 GGUF。仅当白嫖候选与基座顶替均不满足质量时再启动。

**完成判据**：规划专家三选一已落地——① TeichAI 转 GGUF 接入且验收通过（升格为规划专家）；或 ② fable5 规划行为验收通过（兼当）；或 ③ 明确退回基座 thinking 顶替（Router `native` 分支）。三者任一即满足，无需自训。

---

## 阶段 3：实例编译 llama.cpp（隔离 venv + ROCm/HIP）

**位置：实例（SSH `-p 31033`）**

> **顺序修正**：原文档阶段 1–2 要在阶段 3 才建的 `venv_llamacpp` 里跑，逻辑矛盾。现调整为 **3a 前置**：先建 venv + 装 llama.cpp（含 transformers 依赖），阶段 1–2 复用；3b 仅做编译验证。

```bash
ssh -p 31033 root@36.150.116.206

# 3a) 新建隔离 venv —— 绝不碰 /opt/venv
python3 -m venv /persistent/venv_llamacpp
source /persistent/venv_llamacpp/bin/activate

# 确认 ROCm 工具链
which hipcc; echo "ROCM_PATH=$ROCM_PATH"   # 应指向 ROCm 7.2.4

# 克隆并安装（HIP + gfx1100）—— 此步同时装好 convert 脚本依赖
git clone https://github.com/ggml-org/llama.cpp /persistent/llama.cpp
cd /persistent/llama.cpp
CMAKE_ARGS="-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100 -DCMAKE_BUILD_TYPE=Release" \
    pip install -r requirements.txt
CMAKE_ARGS="-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100" pip install .
# 可选 FlashAttention 内核（ROCm 7.2+ 已满足）：追加 -DGGML_HIP_ROCWMMA_FATTN=ON
```

> **两种编译路径（二选一，不要混用）**：
> - **路径 A — Python 包（上文）**：产出 `venv_llamacpp/bin/llama-server` 入口，与手册其余部分一致，推荐。
> - **路径 B — CMake 直编 C++ 二进制**：若想要独立可执行文件（不依赖 venv 入口），改用：
>   ```bash
>   cmake -B /persistent/llama.cpp/build \
>       -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100 -DCMAKE_BUILD_TYPE=Release \
>       [-DGGML_HIP_ROCWMMA_FATTN=ON]
>   cmake --build /persistent/llama.cpp/build --config Release -j$(nproc)
>   # 产物：/persistent/llama.cpp/build/bin/llama-server
>   ```
>   注意：CMake 直编不会装 `llama_cpp` Python 库，阶段 6 若用 `llama_cpp.Llama(...)` 绑定则需改回路径 A 或 `pip install .`。
> 首次编译约 10–30min。若不想编译：用官方预编译 ROCm 构件 / Docker 镜像（需确认实例支持 Docker）。

**完成判据（3b）**：`/persistent/venv_llamacpp/bin/llama-server --version` 正常输出版本；`/opt/venv` 的 torch 未被改动（对比 `torch.__version__` 仍为 `2.10.0+rocm7.2.4`）。

---

## 阶段 4：启动 server，预载多 LoRA

**位置：实例**

```bash
# 基座 Qwen3.6-27B + 最终四专家 GGUF LoRA（btl3/cybersec/teichai_fable5_plan/rag_n7）
/persistent/venv_llamacpp/bin/llama-server \
    -m /persistent/models/Qwen3.6-27B-Q4_K_M.gguf \
    --lora /persistent/loras/teichai_fable5_plan/adapter.gguf \
    --lora /persistent/loras/btl3/adapter.gguf \
    --lora /persistent/loras/cybersec/adapter.gguf \
    --lora /persistent/loras/n7/adapter.gguf \
    --lora-init-without-apply \
    --host 127.0.0.1 --port 8080 \
    -fa on   # FlashAttention（可选）
```

> `--lora-init-without-apply` 让所有 adapter 常驻显存，scale 初始为 0；运行时再激活。
> **规划专家预载（B+ 试错）**：阶段 2.3 已决策——规划专家优先白嫖 `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA`（id=2），与工具/代码专家一并常驻。阶段 5 实测其规划行为；若达标则**升格为规划专家**（零自训成本），若退化不达标则在 Router 层把规划 skill 退回**基座原生 thinking**（`native` 分支，不挂该 LoRA），teichai LoRA 仅留作常驻不激活。无论哪种，server 启动命令不变、工期不增。

> ⚠️ **安全（修正示例）**：实例 `36.150.116.206` 是公网 IP。上面示例已改为 `--host 127.0.0.1`，**仅经 SSH 隧道访问**（`ssh -L 8080:127.0.0.1:8080 -p 31033 root@36.150.116.206` 后本地 `curl http://localhost:8080`）。若必须对外暴露：② 前置反向代理（nginx + credential/API key），③ 用安全组/防火墙限制来源 IP。**绝不在公网裸跑 0.0.0.0:8080**（llama-server 无内置鉴权）。

**完成判据**：server 日志显示模型加载成功 + N 个 LoRA 已注册（含 teichai 规划候选）；`curl http://127.0.0.1:8080/health` 返回 ok。

---

## 阶段 5：热切验证（核心卖点复核）

**位置：实例（经 SSH 隧道访问 127.0.0.1:8080）**

```bash
# 阵容已定稿（见 HANDOFF_EXPERT_ROSTER.md）：挂载顺序决定 id
#   id0=teichai_fable5_plan(agent)  id1=btl3(tool/code)
#   id2=cybersec(security)          id3=rag_n7(doc)
# 验证 id 映射：GET /lora-adapters 返回已注册适配器与序号

# 激活单一专家（其余关 0）：例如只挂 btl3（id1）
curl -s -X POST http://127.0.0.1:8080/lora-adapters \
  -H "Content-Type: application/json" \
  -d '[{"id":1,"scale":1.0},{"id":0,"scale":0.0},{"id":2,"scale":0.0},{"id":3,"scale":0.0}]'

# 工具/代码类请求（btl3）
curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"m","messages":[{"role":"user","content":"列出当前目录并解释每个文件作用"}],"lora":[{"id":1,"scale":1.0}]}'

# 规划类请求（teichai_fable5_plan，id0）
curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"m","messages":[{"role":"user","content":"调查这份 ROCm 迁移计划的主要风险，先给出分步调查方案"}],"lora":[{"id":0,"scale":1.0}]}'

# 安全类请求（cybersec，id2）
curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"m","messages":[{"role":"user","content":"审查这段登录代码有无暴力破解/注入风险"}],"lora":[{"id":2,"scale":1.0}]}'

# 文档/证据类请求（rag_n7，id3）
curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"m","messages":[{"role":"user","content":"基于工作区文档回答并给出引用"}],"lora":[{"id":3,"scale":1.0}]}'

# 回基座原生（清空所有 adapter）
curl -s -X POST http://127.0.0.1:8080/lora-adapters \
  -H "Content-Type: application/json" \
  -d '[]'
```
> 注：旧版 `hermes_s2` / `fable5` 激活示例已废弃——两者已从阵容移除（hermes_s2 基座静默错配、fable5 仓库 404）。历史命令见 git 历史，勿在新环境执行。

> **规划专家已定稿**：`teichai_fable5_plan` 在 G3 行为闸中 3/3 差异达标，**已升格为 agent/规划专家**（零自训成本），见 `bench/LORA_GGUF_GATES.md`。`fable5` 因仓库 404/私有化未采用，不再作为回退候选；若 `rag_n7` 行为不达标则 doc 位回退 `None`（基座原生），见 `HANDOFF_EXPERT_ROSTER.md` §阵容与回退。

> 建议写 `/persistent/screwshell/scripts/bench_lora_swap.sh`：用 `date +%s%N` 高精度包住两次切换，采样 50 次取 p50。
> **延迟口径（统一，修正原文档矛盾）**：
> - **预载后仅切 scale（权重已常驻显存）**：llama.cpp 改 scale 标量 + 应用增量，理想为**亚毫秒级**（<1ms）；peft 的 `set_adapter` 同量级约 8ms，两者是同一数量级区间，不是"亚毫秒 vs 8ms 矛盾"——文档原表述有误，此处澄清。
> - **含首次从盘读 LoRA**：约 12–18ms（仅首次，之后走常驻）。
> - **验收门槛**：连续 50 次切换（已预载、仅切 scale）**p50 ≤ 20ms**，理想亚毫秒级；若实测 **>50ms** 说明每次从盘重载 → 查 `--lora-init-without-apply` 与 endpoint 用法。20–50ms 为灰色带，需排查是否误触发重新加载。

**完成判据**：连续 50 次切换 p50 ≤ 20ms；hermes_s2/fable5 各自输出符合预期专家行为；**规划专家验收结论已落定**（TeichAI 升格 / fable5 兼当 / 退回基座 thinking 三选一，并记录）。

---

## 阶段 6：迁移 MoL 推理核心（代码层，纯本机可开发）

> **开工前置（已读现有代码，接口契约如下）**：写 llama.cpp 后端前，已读 `screwshell/core/mol_engine.py`、`router.py`、`app.py`，对齐抽象接口。本阶段是**纯 Python 代码**，可在本机 Windows 开发 + 单元测试（无需 GPU），真机联调等阶段 4–5 完成。

### 6.1 现有接口契约（必须对齐，避免 Router/Orchestrator 改写）

`MoLEngine`（peft 版，`mol_engine.py`）对外方法，llama.cpp 后端需**同名同签名**实现：

| 方法 | 签名 | 说明 |
|---|---|---|
| `load_base()` | `() -> self` | 加载基座（peft 版走 `AutoModelForCausalLM`；llamacpp 版走 HTTP 无本地加载，或 `llama_cpp.Llama(...)`） |
| `load_adapter(name, path)` | `(str, str) -> dict` | 挂载专家；peft 版 `PeftModel.load_adapter`；llamacpp 版仅记录 `{name: gguf_path}`（server 侧已 `--lora` 预载） |
| `activate(name: Optional[str])` | `(str|None) -> SwitchRecord` | **热切核心**。peft 版 `set_adapter`；llamacpp 版 `POST /lora-adapters` 设 scale。`name=None` = 关所有 adapter（纯基座 / 即规划 `native` 兜底） |
| `chat(messages, max_new_tokens, temperature, enable_thinking)` | `-> (text, GenStats)` | peft 版本地 `model.generate`；llamacpp 版 `POST /v1/chat/completions` 转发 messages |
| `status()` | `-> dict` | 返回 base/active_adapter/adapters/vram/switches |

**数据结构**（两个后端共用，不改）：`SwitchRecord(ts, from_adapter, to_adapter, latency_ms, mode)`、`GenStats(adapter, prompt_tokens, new_tokens, seconds)`。

**Orchestrator 调用点**（`orchestrator.py:121,157`）：`decision = router.route(...)` → `engine.activate(decision.adapter)`。Router 只产出 `adapter` 名（或 `None`），**不感知后端**——所以后端切换对 Orchestrator 零改动，只要 `activate()` 签名一致。

**app.py 装配逻辑（关键，原文档漏写）**：`app.py:43-58` 从 `lora_dir` 目录**自动加载子目录名为 adapter 名**，并 `router.skill_map` 里**未加载成功的 adapter 自动 degrade 成 `None`**（走纯基座）。因此：
- llama.cpp 后端下，`load_adapter` 只需把 `hermes_s2`/`fable5`/`teichai_fable5_plan` 注册进 `self.adapters` 即可，名字来自 `--lora` 预载顺序（id=0/1/2）。
- **无需新增 engine 方法**实现 `native` 兜底：`activate(None)` 已存在，直接对应规划 skill 退回基座 thinking。

### 6.2 Router 的 `skill_map` 必须重命名（原文档漏写）

`router.py:18-24` 的 `DEFAULT_SKILL_MAP` 是**写死旧专家名**的，path D 必须改：

```python
# router.py —— path D 适配（替换 DEFAULT_SKILL_MAP 或运行时覆盖）
# 最终阵容（2026-07-29 定稿）：hermes_s2(静默错配)/fable5(404) 已移除
DEFAULT_SKILL_MAP = {
    "tool": "btl3",                                   # BTL-3（工具调用专家，阶段 2.1）
    "code": "btl3",                                   # BTL-3 兼代码/Agent（HumanEval 95.1%）
    "agent": "teichai_fable5_plan",                   # 规划专家（阶段 2.3 / 阶段 5 验收）
    "security": "cybersec",                           # 安全审计（新增步骤）
    "doc": "rag_n7",                                  # 文档摘要（回退 = None = 基座原生 thinking）
    "base": None,                                     # 纯基座 = 规划 native 兜底
}
```

> **阶段 5 验收结论回填**：若 TeichAI 不达标，`agent` 改为 `None`（走 `activate(None)` = 基座 thinking），`teichai_fable5_plan` LoRA 仅常驻不激活。这一行就是 B+ 决策的代码落点——**改一个 map 值即回退，零重构**。

### 6.3 两个后端的差异点（写代码时务必注意）

| 维度 | peft 版（现状） | llama.cpp 版（path D） |
|---|---|---|
| 设备 | `torch.cuda.*`（`synchronize`/`mem_get_info`/`device_map="cuda:0"`） | **无 CUDA 调用**；server 模式走 HTTP，本地模式走 `llama_cpp` 绑定。CUDA 相关调用必须去掉或 no-op |
| 热切 | 进程内 `set_adapter` | HTTP `POST /lora-adapters`（需 `host=127.0.0.1:8080`，见阶段 4 隧道） |
| chat 模板 | 本地 `tokenizer.apply_chat_template(enable_thinking=...)` | server 侧处理；`enable_thinking` 映射为 llama.cpp 的 thinking/reasoning 参数（如 `--reasoning-budget` 或请求体字段） |
| VRAM 查询 | `torch.cuda.mem_get_info()` | server 模式无本地显存查询 → `vram_gb()` 改为返回 `None` 或查 `/health`/进程；或标 `@staticmethod` 返回固定值 |

> **抽象建议**：定义 `MolBackend` protocol（含上述 5 方法），`MoLEngine`(peft) 与 `MoLLlamaCpp`(llamacpp) 都实现它。Orchestrator 持 `MolBackend` 类型，靠 `MOL_BACKEND` 配置键选实现。

### 6.4 后端切换配置键

在 `app.py` 或 `config.yaml` 加 `MOL_BACKEND: "peft" | "llamacpp"`（读环境变量）。装配时：
```python
if os.getenv("MOL_BACKEND") == "llamacpp":
    from screwshell.core.mol_engine_llamacpp import MoLLlamaCpp
    engine = MoLLlamaCpp(base, server_url="http://127.0.0.1:8080").load_base()
else:
    engine = MoLEngine(base).load_base()   # 现状 peft，零风险回退
```
Router / Orchestrator 代码**不改**。

### 6.5 本机离线自测（不等 GPU 也能验证代码）

阶段 4–5 未完成时，阶段 6 代码可本机开发并用以下方式自测：
- **mock server**：用 `unittest.mock` 或本地 `http.server` 起一个假 `/lora-adapters` + `/v1/chat/completions`，断言 `MoLLlamaCpp.activate()` 发的 JSON body 是 `[{"id":0,"scale":1.0},...]`、`chat()` 转发 messages 正确。
- **接口契约测试**：断言 `MoLLlamaCpp` 与 `MoLEngine` 方法签名一致（可用 `inspect.signature` 比对），保证 Router/Orchestrator 免改。
- **skill_map 单测**：断言 `route("调查ROCm风险")` → `agent` → `teichai_fable5_plan`（或验收后 `None`），`route("读这个py文件")` → `code` → `fable5`。
- 真机联调（连实例 server 跑 day4 式 e2e）留到阶段 4–5 完成后做。

**完成判据**：新增 `screwshell/core/mol_engine_llamacpp.py` 实现 `MolBackend` 5 方法；`router.py` 的 `skill_map` 已改为 path D 专家名；`MOL_BACKEND` 键可切换 peft/llamacpp；本机单测全过（mock server 验证 activate/chat 契约）；真机联调端到端跑通 day4 式 e2e（读本地文档 + 带行号引用），热切延迟与阶段 5 一致。

---

## 风险与回退

| 风险 | 缓解 |
|---|---|
| 编译 llama.cpp 在 gfx1100 失败 | 改用预编译 ROCm 构件 / 官方 Docker；或退守 **path A**（即 README 现状：Qwen3.5-9B + peft 双专家 sygnif+metro，已实测可用、未动，零风险回退） |
| 规划/推理专家无干净现成 LoRA | B+ 策略：先白嫖 `TeichAI/...Fable-5-Experimental` 转 GGUF 试（阶段 5 验收）；不行则退回基座原生 thinking（Router `native` 分支，`activate(None)`）；自训仅作质量上限（非必须） |
| LoRA 转 GGUF 报 `_reorder_v_heads NotImplementedError`（issue #21125，PR #24627 未合） | 改用已带 GGUF 的 LoRA（hotdogs/fable5）；或自训时限制 target_modules 避开 out_proj；或手动合并后离线转 |
| 热切实测 >50ms | 检查 `--lora-init-without-apply` 与 endpoint 用法；必要时改用请求内 `"lora"` 字段 |
| 失去 per-request 并发隔离 | 本项目顺序路由无影响；若需并发多专家则本路径不满足 |
| 实例 destroy 丢产物 | 阶段 0 已 git init+远端；源码入 git，GGUF/LoRA 大文件走 Git LFS 或对象存储定期备份 |
| 公网暴露 llama-server | 阶段 4 已改 127.0.0.1 + SSH 隧道；对外必须前置鉴权代理 + 安全组限制 |

---

## 执行顺序总览

```
0. git init + 远端（本机只加 remote 到 master；GGUF/LoRA 走实例侧 LFS/对象存储）   [本机侧 + 实例侧]
3a. 实例建 /persistent/venv_llamacpp + 装 llama.cpp（前置）  [实例，隔离]
1. 准备基座 GGUF（Qwen3.6-27B, unsloth Q4_K_M）            [实例 venv_llamacpp]
2. 准备 LoRA：工具(hermes_s2) + 代码(fable5) 现成；规划白嫖 TeichAI 转 GGUF 试 [实例 venv_llamacpp]
3b. 编译验证 llama.cpp (HIP,gfx1100)                       [实例]
4. 启 server 预载 LoRA（127.0.0.1 + SSH 隧道，含 TeichAI id=2） [实例]
5. 热切基准 + 规划 B+ 验收（p50 ≤ 20ms；TeichAI 升格/退回基座） [实例]
6. 迁移 mol_engine_llamacpp.py + Router skill_map 重命名 + MOL_BACKEND 键 [本机代码，可离线单测；真机联调等 4-5]
```

> **执行者边界（见 §0.1）**：阶段 0 本机侧 / 阶段 6 代码可在本机 Windows 做；阶段 1–5 必须在远程 GPU 实例做，本机执行不了。阶段 6 代码编写与单测可现在开始，不等 GPU。
> 全部命令均为**草案**，待用户在 path D 上拍板后再逐阶段执行；每阶段独立可回退，且 `/opt/venv` 全程不被触碰。
> 可行性依据见 `VLLM_ROCM_FEASIBILITY.md` 第 5 节（llama.cpp 热 LoRA 调研）；基座/LoRA 选型依据见本手册第 0 节（HF 实测生态调研，2026-04 发布线）。
