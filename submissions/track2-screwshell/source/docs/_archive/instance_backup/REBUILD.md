# ScrewShell 远程实例产物重建手册（REBUILD）

> **用途**：万一持久盘 `/persistent` 丢失，凭本文从零重建所有 GGUF 产物。
> **生成**：2026-07-29，依据 `PATH_D_HANDOFF.md` + `LORA_GGUF_GATES.md`（均已备份于同目录 `docs/`）。
> **实例**：W7900 / ROCm 7.2.4 / 51.5GB VRAM；SSH `ssh -i ~/.ssh/id_ed25519 -p 31033 root@36.150.116.206`

## 0. 关键前提
- 持久盘 `/persistent` 是**独立 NFS 网络盘**（腾讯云 SFSTurbo），实例重启/销毁**不丢**；本文是额外保险，正常情况用不到。
- 实例 `huggingface.co` 主站不通 → 所有 HF 操作必须 `export HF_ENDPOINT=https://hf-mirror.com`。
- 实例 github 直连证书错 → 用 `gh-proxy.org` 或 `GIT_SSL_NO_VERIFY=1`（仅实例侧）。
- llama.cpp 已打补丁：`gguf/utility.py` 硬编码域名改读 `HF_ENDPOINT`（备份 `utility.py.bak`）。

## 1. 实例环境基线（已具备，盘丢才需重做）
- venv：`/persistent/venv_llamacpp`（Python 3.12，torch 2.11+cpu 用于转换）
- llama.cpp：`/persistent/llama.cpp`（patched，已 CMake 编译）
  - 编译命令（**路径 B**，勿用 `pip install .` 会装成废包 `llama-cpp-scripts`）：
    ```bash
    source /persistent/venv_llamacpp/bin/activate
    export ROCM_PATH=/opt/rocm
    cd /persistent/llama.cpp
    cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100 \
          -DCMAKE_BUILD_TYPE=Release -DGGML_HIP_ROCWMMA_FATTN=ON .
    cmake --build build --config Release -j$(nproc)
    ```
  - 产物：`/persistent/llama.cpp/build/bin/llama-server`（version 1, commit 8161641）

## 2. 基座模型（16.8GB）
- 源：`unsloth/Qwen3.6-27B-Q4_K_M.gguf`（HF 镜像可下）
- 落盘：`/persistent/models/Qwen3.6-27B-Q4_K_M.gguf`
- 下载（若丢失重下）：
  ```bash
  export HF_ENDPOINT=https://hf-mirror.com
  /persistent/venv_llamacpp/bin/python3 -c \
    "from huggingface_hub import hf_hub_download as d; d('unsloth/Qwen3.6-27B-Q4_K_M.gguf', local_dir='/persistent/models')"
  ```
- 四个 LoRA 的 `base_model_name_or_path` 均为 `Qwen/Qwen3.6-27B`（镜像 main revision `6a9e13bd…`），与基座 GGUF 同源。

## 3. 四个决赛 LoRA 源仓库（可重下）
| 阵容位 | adapter | HF 仓库 | tensor 数 | GGUF 大小 | GGUF 路径 |
|---|---|---|---|---|---|
| tool / code | `btl3` | `badtheorylabs/BTL-3` (r32/α64) | 992 | 466.9M | `/persistent/loras/btl3/adapter.gguf` |
| security | `cybersec` | `hotdogs/qwen3.6-27b-cybersecurity-lora` (r8/α16) | 512 | 79.7M | `/persistent/loras/cybersec/adapter.gguf` |
| agent / planning | `teichai_fable5_plan` | `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA` (r64) | 992 | 934M | `/persistent/loras/teichai_fable5_plan/adapter.gguf` |
| doc / evidence | `rag_n7` | `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7` (r128/α256) | 992 | 1.9G | `/persistent/loras/n7/adapter.gguf` |

> 已移除（残留不挂载）：`hermes_s2`（基座静默错配）、`fable5`（仓库 404/私有化）。
> 实验性未转源（不在阵容，可重下）：`deltacoder` / `metro` / `sygnif`（见 `/persistent/loras/`）。

## 4. 转换流程（safetensors → GGUF f16）
对每个 `<x>` ∈ {btl3, cybersec, teichai_fable5_plan, n7}：
```bash
export HF_ENDPOINT=https://hf-mirror.com
# 4.1 下载源（venv python，token-free 经镜像）
/persistent/venv_llamacpp/bin/python3 -c \
  "from huggingface_hub import snapshot_download as s; s('<repo>', local_dir='/persistent/loras/_raw/<x>')"
# 4.2 转换（第一个位置参数是本地目录！不是 repo id；输出目录必须先 mkdir）
mkdir -p /persistent/loras/<x>
/persistent/venv_llamacpp/bin/python3 /persistent/llama.cpp/convert_lora_to_gguf.py \
  /persistent/loras/_raw/<x> --outtype f16 --outfile /persistent/loras/<x>/adapter.gguf
```
- **坑**：`convert_lora_to_gguf.py` 第一个位置参数是**本地目录**（含 `adapter_model.safetensors`），不是 HF repo id；输出目录必须先 `mkdir`，否则末尾 `FileNotFoundError`（白算）。
- **历史墙（已解，记录防复发）**：早期 `convert_lora_to_gguf.py:153` 的 `out_proj` reshape `NotImplementedError`（issue #21125 / PR #24627 未合），通过 patched llama.cpp + transformers 5.15.0.dev0 解决；现四个 adapter 均转换成功（G1 PASS，tensor 数与同族一致）。

## 5. 启动 + 热切验收
```bash
/persistent/llama.cpp/build/bin/llama-server -m /persistent/models/Qwen3.6-27B-Q4_K_M.gguf \
  --lora /persistent/loras/teichai_fable5_plan/adapter.gguf,/persistent/loras/btl3/adapter.gguf,/persistent/loras/cybersec/adapter.gguf,/persistent/loras/n7/adapter.gguf \
  --lora-init-without-apply --host 127.0.0.1 --port 8080 -ngl 99 -fa on -c 8192
```
- **坑**：新版本 llama.cpp **不支持重复 `--lora`**，必须逗号分隔单次传。
- 激活/切换（**数组格式**，非对象）：`POST /lora-adapters` body `[{"id":N,"scale":1.0}]`；回基座 body `[]`。
- **G3 大坑**：Qwen3.6 推理模型先吐 `reasoning_content` 占满 `max_tokens` 导致 `content` 空 → 关思考 `chat_template_kwargs:{"enable_thinking":False}`（推荐）或 `max_tokens` 提到 ~1100。
- **G4**：热切控制面均值 <1ms 即过（实测 0.5–0.8ms/专家）。

## 6. 本机备份现状（2026-07-29）
- 小文件（文档/脚本）已备份至本机 `D:\AI\gpu_instance_backup\docs\`：`LORA_GGUF_GATES.md`、`PATH_D_HANDOFF.md`、`g3_validate.py`、`_tmp_verify_lora.py`。
- GGUF 大文件按决策**不备份文件**（持久盘独立 NFS 已稳）；本机顺手捡到：`cybersec/adapter.gguf`(77M，**完整可用**)；`hermes_s2/adapter.gguf`(88M，**不完整/应169M，勿依赖**)、`n7/adapter.gguf`(1.1G，**不完整/应1.8G，勿依赖**)。
- **重建以本文第 2–5 节为准，不依赖本机任何 GGUF 副本。**

## 7. 红线
- llama-server 绝不 `0.0.0.0` 裸跑，仅 `127.0.0.1` + SSH 隧道：`ssh -L 8080:127.0.0.1:8080 -p 31033 root@36.150.116.206`。
- 产物只落 `/persistent`，绝不 `/root`/`/tmp`/`/opt`。
- venv 隔离 `/persistent/venv_llamacpp`，绝不碰 `/opt/venv`。
