> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# Path D 实例侧执行交接文档（HANDOFF）

> 本文件记录 `PATH_D_IMPLEMENTATION.md` 在远程 GPU 实例（`root@36.150.116.206 -p 31033`，W7900 / ROCm 7.2.4）逐阶段执行的**真实进度与偏离**。接手者据此继续，不要照手册盲跑——手册有多处假设已被现实推翻。
>
> 生成时间：2026-07-28。执行者：opencode agent。
>
> **⚠️ 阵容已终审（2026-07-29，见 `HANDOFF_EXPERT_ROSTER.md`）**：本文件写作时仍以 `hermes_s2`(工具) + `fable5`(代码) + `teichai`(规划) 三专家为假设。其中 **`hermes_s2` 被查出基座静默错配（真基座 Opus-CoT-Stage1）、`fable5` 实测 404/私有化从未下载成功，二者均已从阵容清除**。最终阵容为 `btl3`(工具/代码) + `cybersec`(安全,新增) + `teichai_fable5_plan`(规划) + `rag_n7`(文档,回退=base)，全部 base 上游核验 == `Qwen/Qwen3.6-27B`。本文件保留为历史执行记录，勿将其专家假设当作现状。

---

## 0. 实例环境基线（实测）

| 项 | 值 |
|---|---|
| SSH | `ssh -p 31033 root@36.150.116.206`（公网 IP，仅经隧道访问） |
| ROCm | 7.2.4（`/opt/rocm`，`ROCM_PATH` 默认空，编译时需 `export ROCM_PATH=/opt/rocm`） |
| hipcc | 7.2.5，AMD clang 22.0.0 |
| Python | 3.12.3（`/usr/bin/python3`） |
| gcc / cmake | 13.3.0 / 3.28.3 |
| GPU | 识别为 "AMD Radeon Graphics"（即 W7900） |
| `/opt/venv` | 存在（torch 2.10+rocm7.2.4），**全程未碰** ✅ |
| `/persistent` | 99G 空闲，已有 `screwshell/`、`loras/`、`hf-home/` |

### 网络约束（重要）
- **github 直连 git 报证书错误**（`CAfile: none`）。解决：实例有 git-wrapper 走 `gh-proxy.org`，`git clone` 实际可用；或 `GIT_SSL_NO_VERIFY=1`。
- **huggingface.co 主站不通**（超时/无响应），但 **`hf-mirror.com` 镜像可用**（HTTP 200，能列 repo + 下文件）。
- 所有 HF 下载走 `https://hf-mirror.com/<repo>/resolve/main/<file>`。
- pypi 直连可用。

---

## 1. 阶段执行状态

### 阶段 0（固化环境）—— 部分完成
- 本机侧：`D:\ai\screwshell` 已是 git 仓库（`master` 分支，无 remote）。本机改动未 commit（见 §4）。
- **实例侧：`/persistent/screwshell` 不是 git 仓库**（实测 `not a git repo`）。阶段 0 实例侧 `git init` + LFS 未做。
- 大文件策略：GGUF/LoRA 走 `hf-mirror` 可重新下载，未做 LFS/对象存储备份。

### 阶段 3a / 3b（venv + 编译 llama.cpp）—— ✅ 完成
- venv：`/persistent/venv_llamacpp`（Python 3.12）。
- **编译路径修正**：手册推荐的路径 A（`pip install .`）在 llama.cpp 当前主干里实际装成 **`llama-cpp-scripts` 废包**，不编 HIP、无 `llama-server` 二进制。**已改用路径 B（CMake 直编）**：
  ```bash
  source /persistent/venv_llamacpp/bin/activate
  export ROCM_PATH=/opt/rocm
  cd /persistent/llama.cpp
  cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100 \
        -DCMAKE_BUILD_TYPE=Release -DGGML_HIP_ROCWMMA_FATTN=ON .
  cmake --build build --config Release -j$(nproc)
  ```
- 产物：`/persistent/llama.cpp/build/bin/llama-server`（version 1, commit 8161641）+ `libllama-server-impl.so`（HIP）。
- **注意**：`pip install .` 顺带装了 CPU 版 torch 2.11 进 venv（转化脚本依赖，无害）。
- `/opt/venv` 的 torch 未被改动 ✅。

### 阶段 1（基座 GGUF）—— ✅ 完成
- 下载：`unsloth/Qwen3.6-27B-Q4_K_M.gguf` → `/persistent/models/Qwen3.6-27B-Q4_K_M.gguf`
- 大小 **16.8GB（16817244384 bytes）**，与文档预期一致，`DL_EXIT=0`。
- **llama-server 实测能加载该 GGUF**（日志 `model loaded`，qwen3_5 架构 llama.cpp 认得）。

### 阶段 2（LoRA 准备）—— ⚠️ 部分完成，有硬阻塞
已下载（token-free，经 hf-mirror）：
- `/persistent/loras/hermes_s2/`：`adapter_model.safetensors`(338M) + `adapter_config.json`（工具调用专家，r=16）
- `/persistent/loras/teichai_fable5_plan/`：`adapter_model.safetensors`(1.8G) + `adapter_config.json`（规划候选，r=64，full-linear）

**阻塞点 1（硬）：`hotdogs/qwen3.6-27b-fable5-lora`（代码/Agent 专家）返回 401**
- 手册称其"直接附带 GGUF，drop-in，零转换风险"。实际 **repo 被 gated（401 / Invalid username or password）**，无 HF token 拿不到。
- 实例无缓存 token（`/root/.cache/huggingface/token` 不存在，无 `HF_TOKEN` 环境变量）。
- **这是三专家里唯一"代码"专家，缺口。需接手者提供 `HF_TOKEN` 或换替代源。**

**阻塞点 2（已破解 transformers 部分，但暴露更深转换墙）：Qwen3.6 LoRA 转 GGUF 在 stock llama.cpp 下实际不可行**
- `hermes_s2`/`teichai` 的 `adapter_config.json` 里 `base_model` 指向 `Qwen/Qwen3.6-27B`，`config.json` 的 `model_type=qwen3_5`。
- 原 venv 的 transformers 4.57.6 不认 `qwen3_5`（`KeyError`），已升级到主干 **5.15.0.dev0**（TF_EXIT=0，已认 qwen3_5）。
- 但转换仍卡两道墙：
  1. **硬编码域名墙（已绕过）**：`gguf/utility.py` 的 `SafetensorRemote.BASE_DOMAIN` 写死 `https://huggingface.co`，实例访问不通。已编辑本仓库克隆（`/persistent/llama.cpp/gguf-py/gguf/utility.py:112`）改为读 `HF_ENDPOINT` 环境变量；配合 `HF_ENDPOINT=https://hf-mirror.com` 可拉到 `Qwen/Qwen3.6-27B` 的 safetensors（15 shard，镜像可下）。**备份在 `/persistent/utility.py.bak`**。
  2. **`out_proj` reshape 真墙（未解，文档 §0 雷区属实）**：转换 `hermes_s2` 时抛 `NotImplementedError`，位于 `convert_lora_to_gguf.py:153` 的 `LoraTorchTensor.reshape`（`if new_shape[-1] != orig_shape[-1]: raise NotImplementedError`）。根因是 Qwen3.6 的 linear-attention `out_proj`/`o_proj` 头布局与标准不同，转换器无法 trivially reshape。这正是 issue #21125 / PR #24627（未合）描述的 bug。**文档曾误判"最新主干已无此异常"——错：`conversion/qwen.py` 里的 `_reorder_v_heads` 是另一个函数，LoRA 转换器用的是自己那份会抛 `NotImplementedError` 的 reshape。文档 §0 的雷区警告才是对的。**
- **结论**：当前 stock llama.cpp 无法把**任何**含 `out_proj`/`o_proj` target 的 Qwen3.6 LoRA 转成 GGUF。`hermes_s2`（targets 含 out_proj/o_proj/q/k/v_proj…）和 `teichai`（full-linear 正则含 out_proj）**都会撞这堵墙**。`fable5` 因 401 连 PEFT 源都拿不到，更无从转。
- **可行出路（需决策）**：
  - (a) 打补丁修 `convert_lora_to_gguf.py:153` 的 reshape（有权重损坏风险，非专家不建议盲改）；
  - (b) 拿 HF token 拉 `fable5`（但其 base 同样是 Qwen3.6，转换仍撞同一堵墙）；
  - (c) **退回 path A（手册风险表明示的零风险回退）**：现有 peft + Qwen3.5-9B + sygnif/metro 双专家已在本实例实测可用（README），path D 的 LoRA 转换墙不解除前，这是可交付的兜底。
  - (d) 等 PR #24627 合并进 llama.cpp 主干后重转。

### 阶段 4 / 5（起 server + 热切验收）—— ✅ 完成（2026-07-28 实测，数据见 `bench/benchmark_pathd.json`）
- **实测结果**：加载 9s（16.8GB 全 GPU）、VRAM 18.9/48GB、基座 decode 31.0 tok/s（prefill ~100）、LoRA 激活 23.4–26 tok/s、热切换（`POST /lora-adapters` 调 scale）10 次 avg **2.09ms**（稳态 0.3–0.8ms）。行为差异 temp=0 验证：hermes_s2 先做工具选择推理，teichai 规划 8 步含 Post-Mortem/canary（基座对照 6 步）。
- **正确启动命令（注意：重复 `--lora` 已废弃只认最后一个，必须逗号分隔！）**：
  ```bash
  /persistent/run_lora_server.sh   # 已落实例的启动脚本，内容如下
  /persistent/llama.cpp/build/bin/llama-server \
      -m /persistent/models/Qwen3.6-27B-Q4_K_M.gguf \
      --lora-init-without-apply \
      --lora /persistent/loras/teichai_fable5_plan/adapter.gguf,/persistent/loras/btl3/adapter.gguf,/persistent/loras/cybersec/adapter.gguf,/persistent/loras/n7/adapter.gguf \
      -ngl 99 -fa on -c 8192 --host 127.0.0.1 --port 8080
  ```
- 集成三坑（app/demo 必须处理）：① `--lora` 逗号分隔（上）；② **teichai 默认烧 300–700 thinking token 不出正文** → 请求带 `/no_think` + `chat_template_kwargs.enable_thinking=false`；③ SSH 里 `pkill -f llama-server` 会自杀（-f 匹配自身命令串）→ 用 `pkill -x llama-server`。
- 访问经 SSH 隧道：`ssh -L 8080:127.0.0.1:8080 -p 31033 root@36.150.116.206`

### 阶段 6（mol_engine_llamacpp.py + Router + 本机单测）—— ✅ 本机已完成
见 §3。

---

## 2. 待决策 / 待办（接手者必读）

1. **[阻塞] 提供 HF token 拉 fable5**：否则代码/Agent 专家缺位。替代方案（降级，偏离手册三专家设计）：
   - 用 `hermes_s2` 兼当 工具+代码；`teichai` 兼当 规划；或
   - 代码槽 `route("code")` 退回基座（`None`）→ Router `skill_map` 里 `"code": None`。
   无论哪种，改 `router.py` 的 `DEFAULT_SKILL_MAP` 一行即可，零重构。

2. **[进行中] 确认 transformers 升级结果**：升级完后重跑 hermes_s2 转换：
   > ⚠️ 历史命令（hermes_s2 已移除，此块不再执行；仅留作 out_proj reshape 补丁的回溯记录）
   ```bash
   source /persistent/venv_llamacpp/bin/activate
   export ROCM_PATH=/opt/rocm
   cd /persistent/llama.cpp
   # 仍需 base-model 的 config.json（已下到 /persistent/hf-home/Qwen3.6-27B-config/）
   python convert_lora_to_gguf.py /persistent/loras/hermes_s2 \
       --base-model /persistent/hf-home/Qwen3.6-27B-config \
       --outtype f16 --outfile /persistent/loras/hermes_s2/adapter.gguf
   ```
   若仍报架构错误，从 HF 拉 `Qwen/Qwen3.6-27B` 完整 config（含 tokenizer_config）到 `/persistent/hf-home/Qwen3.6-27B-config/` 重试。

3. **teichai 转换**：同上命令，把路径换成 `/persistent/loras/teichai_fable5_plan`。

4. **阶段 0 实例侧 git**：`/persistent/screwshell` 需 `git init` + remote（源码入 git；GGUF/LoRA 大文件走镜像重下或 LFS，不要直接 push 二进制）。

5. **阶段 5 规划专家 B+ 验收**：teichai 转成 GGUF 后，按手册阶段 5 发规划类请求人工评估；达标升格、不达标则 `router.py` 的 `"agent": None` 退回基座 thinking。

---

## 3. 本机已完成代码（阶段 6，已落盘未 commit）

- `screwshell/core/mol_types.py`（新增）：`SwitchRecord`/`GenStats` 抽到 torch-free 模块，两个后端共用。
- `screwshell/core/mol_engine_llamacpp.py`（新增）：`MoLLlamaCpp` 独立类，5 方法同名同签名，HTTP(urllib) 走 server，`activate(None)`=关全部=规划 native 兜底。
- `screwshell/core/router.py`：`DEFAULT_SKILL_MAP` 改为 `hermes_s2`/`fable5`/`teichai_fable5_plan`/`None`（旧名注释留存）。
- `screwshell/app.py`：`build_app` 加 `MOL_BACKEND` 环境变量切换（peft 默认，llamacpp 走 `MOL_LLAMACPP_URL`，默认 127.0.0.1:8080）；llama.cpp 模式跳过本地 adapter 发现。
- `screwshell/core/mol_engine.py`：`SwitchRecord`/`GenStats` 改为从 `mol_types` 导入（去 torch 依赖）。
- `tests/test_mol_llamacpp.py`（新增）：mock HTTP server 验证 activate/chat 契约 + 接口签名对等（torch 对等测试在无 torch 环境 skip）+ skill_map 路由。本机 `pytest` 6 passed / 1 skipped。

---

## 4. 实例侧临时文件索引（接手排查用）

| 文件 | 内容 |
|---|---|
| `/persistent/build_llamacpp.log` | 第一次 `pip install .`（废包，失败路径，可忽略） |
| `/persistent/cmake_cfg.log` / `cmake_build.log` | CMake 路径 B 配置/编译日志 |
| `/persistent/dl_base.log` | 基座下载日志（DL_EXIT=0） |
| `/persistent/dl_lora.log` | hermes_s2/teichai 下载日志（LORA_DL_DONE） |
| `/persistent/conv_hermes.log` | hermes_s2 转换日志（前两次失败：GGUF 路径误用 / qwen3_5 架构） |
| `/persistent/upgrade_tf.log` | transformers 升级日志（进行中） |
| `/persistent/server_test.log` | llama-server 加载基座测试日志（model loaded 成功） |

---

## 5. 红线提醒（来自手册，执行中已遵守）
1. 隔离 venv `/persistent/venv_llamacpp`，绝不碰 `/opt/venv` ✅
2. 产物落 `/persistent` ✅
3. 实例 destroy = 全盘清空 → 源码 git + 大文件镜像/LFS 备份（**实例侧 git 尚未做，见待办 4**）
4. 不在 Z 阶段安装/编译（阶段 3 编译属正常，Z 是另一阶段）
5. llama-server 绝不 0.0.0.0 裸跑，仅 127.0.0.1 + SSH 隧道

---

## 6. 一句话当前状态（2026-07-28 深夜：path D 端到端验收通过）
**path D 已全链路跑通并实测验收**：转换墙手补清除（§7）→ `hermes_s2`(176.7M/608张量) + `teichai`(933.8M/992张量) 转成合法 GGUF → llama-server 挂双 LoRA 起服务 → **热切换 avg 2.09ms、基座 31.0 tok/s、VRAM 18.9/48G、行为差异 temp=0 对照验证**（阶段 4/5 实测详情见 §1，原始数据 `bench/benchmark_pathd.json`）。**剩余缺口只有一个：`fable5` 第三专家仍 401 需 HF token**（或降级 `"code": None` 退基座）。README §5 / SPEC §5 / BENCHMARK_STATUS 均已更新为实测数字。

### 已验证可行的部分（不要重复踩坑）
- ✅ venv 隔离 + CMake 路径 B 编译出 HIP llama-server（version 1 / commit 8161641）
- ✅ 基座 `unsloth/Qwen3.6-27B-Q4_K_M.gguf`（16.8GB）下载完成，server 能 `model loaded`
- ✅ transformers 升级到 5.15.0.dev0 认 qwen3_5
- ✅ 镜像 `hf-mirror.com` 可下 HF 资源（主站 huggingface.co 实例不通）
- ❌ `gguf/utility.py` 硬编码 huggingface.co → 已打补丁读 HF_ENDPOINT（备份 utility.py.bak）
- ✅ **LoRA→GGUF 的 out_proj reshape 死墙已手补清除（见 §7），hermes_s2/teichai 均成功转出合法 GGUF**

### 接手者下一步建议
1. ~~阶段 4/5 验收~~ **✅ 已完成**（见 §1 阶段 4/5 实测与三坑）；下一步是把 `MOL_BACKEND=llamacpp` 的 app/UI 端到端接到这台 server 上跑通 demo 流程（注意 thinking 关闭坑）。
2. **补齐第 3 个专家 fable5**：仍需 HF token（401）。拿到 token 后 `export HF_TOKEN=...` 拉 `hotdogs/qwen3.6-27b-fable5-lora`，再按 §7 命令转 GGUF。或降级：代码槽 `route("code")` 退回基座（`router.py` 的 `"code": None`）。
3. **防丢（见 §7）**：两处补丁目前只在实例 `/persistent/llama.cpp/convert_lora_to_gguf.py`（已备份 `convert_lora_to_gguf.py.bak_reorder_patch`）。实例 destroy = 补丁丢失，建议尽快 `git diff` 落本地或设实例侧 git 提交（实例侧 git 仍未 init，见待办 4）。

---

## 7. 转换墙手动补丁详情（2026-07-28，已落实例并实测）

未合 PR #24627 的方向（给 `LoraModel` 加 `_reorder_v_heads` 重载）是对的，但**不能直接套 PR diff**：
实例的 `convert_lora_to_gguf.py`（commit 8161641）里 `model_class` 是 `convert()` 函数局部变量，嵌套类的静态方法看不到它（会 NameError）。
故改为**实例方法 + `super()`**，逻辑照 PR（对单个 LoRA 因子做 permutation）。

### 补丁 1：`LoraModel._reorder_v_heads` 重载（清除 reshape 死墙）
位置：在 `class LoraModel(model_class):` 内、`get_tensors` 之后、`modify_tensors` 之前插入：
```python
def _reorder_v_heads(self, tensor, dim, num_k_heads, num_v_per_k, head_dim):
    if not isinstance(tensor, LoraTorchTensor):
        return super()._reorder_v_heads(tensor, dim, num_k_heads, num_v_per_k, head_dim)
    shape = tensor.shape
    if dim < 0:
        dim += len(shape)
    lora_a, lora_b = tensor.get_lora_A_B()
    if dim == len(shape) - 1:
        perm = super()._reorder_v_heads(
            torch.arange(shape[dim], dtype=torch.long).unsqueeze(0),
            1, num_k_heads, num_v_per_k, head_dim).squeeze(0)
        lora_a = lora_a.index_select(-1, perm)
    else:
        perm = super()._reorder_v_heads(
            torch.arange(shape[dim], dtype=torch.long).unsqueeze(-1),
            0, num_k_heads, num_v_per_k, head_dim).squeeze(-1)
        lora_b = lora_b.index_select(dim, perm)
    return LoraTorchTensor(lora_a, lora_b)
```
根因：`conversion/qwen.py:369` 的 `_reorder_v_heads` 对张量做 `reshape`，遇到 `LoraTorchTensor`（W=B@A 分解）在 `convert_lora_to_gguf.py:153` 抛 `NotImplementedError`。

### 补丁 2（辅助）：`load_hparams_from_hf` 本地目录分支
`--base-model-id` 传本地路径时 `try_to_load_from_cache` 会 `HFValidationError`；加：
```python
if os.path.isdir(hf_model_id):
    # local path: config already on disk, no HF cache lookup needed
    return config.to_dict(), Path(hf_model_id)
```
（实测最终用 repo-id 路径，此补丁为离线兜底，无害。）

### 正确的转换命令（关键：用 repo id + 镜像，不是本地路径）
```bash
source /persistent/venv_llamacpp/bin/activate
export ROCM_PATH=/opt/rocm
export HF_ENDPOINT=https://hf-mirror.com
cd /persistent/llama.cpp
# （历史命令，hermes_s2 已移除 —— 此转换不再执行；仅留作 out_proj reshape 补丁的回溯记录）
python convert_lora_to_gguf.py /persistent/loras/hermes_s2 \
    --base-model-id Qwen/Qwen3.6-27B \
    --outtype f16 --outfile /persistent/loras/hermes_s2/adapter.gguf
# teichai 同理：把路径换成 /persistent/loras/teichai_fable5_plan
```
注意：handoff 旧命令 `--base-model /persistent/hf-home/Qwen3.6-27B-config`（本地路径）在本版本**不通**——
`index_tensors` 本地分支只认 `.safetensors`，本地只有 GGUF，故必须走 `--base-model-id <repo_id>` 让脚本经 `HF_ENDPOINT` 镜像拉张量清单（懒加载，不下完整权重）。

### 防丢（重要）
两处补丁**目前只在实例 `/persistent/llama.cpp/convert_lora_to_gguf.py`**（已备份 `convert_lora_to_gguf.py.bak_reorder_patch`）。
实例 destroy = 补丁丢失。建议：(a) 把补丁 `git diff` 存到本地仓库，或 (b) 设好实例侧 git（见待办4）后提交。
