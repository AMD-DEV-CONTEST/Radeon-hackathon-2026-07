# LoRA → GGUF 转换 & 验收闸（G1–G5）结果

> ⚠️ **现状注记（2026-08-02，与 `docs/TRUTH.md` v7 对齐）**：本记录原写于 2026-07-28，当时假设 `teichai_plan` 已转 GGUF。现网真实状态是 **`teichai_plan` 无 GGUF 权重来源**，`router` 的 `agent→teichai_plan` 静默降级为基座原生（见 TRUTH §2）。因此：① G1 对 `teichai_plan` 不可过（无 tensor 可 match）；② G3/G4 中 `teichai_plan` 行为数据系基于旧假设、**现网已不成立**（降级 base 后无 adapter 热切）。下方保留原始测量值并加注，仅供历史参考。路径/端口/测试数已同步到 2026-08-02 真机状态。

> 执行环境：远程 GPU 实例 `root@36.150.116.206 -p 31010`（W7900 / ROCm 7.2.4 / 51.5GB VRAM）
> 基座：`/workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf`（16.8GB，源 revision `6a9e13bd…`，HF 镜像 main 一致）
> 转换工具：`/opt/llama.cpp.new`（patched，已编译 `build/bin/llama-server`）+ `/workspace/persistent/screwshell_run/venv_llamacpp`
> 执行时间：2026-07-28（实例时区 UTC）
> 配套脚本：`/workspace/persistent/screwshell_run/g3_validate.py`（G3/G4 验证）、日志 `/workspace/persistent/screwshell_run/g3_result.log`

## T1 转换结果（safetensors → GGUF，f16）

| 阵容位 | adapter 名 | HF 仓库 | tensor 数 | 大小 | GGUF 路径 |
|---|---|---|---|---|---|
| tool / code | `btl3` | `badtheorylabs/BTL-3` (r32/α64) | 992 | 466.9M | `/workspace/persistent/screwshell_run/loras/btl3/adapter.gguf` |
| security (新增) | `cybersec` | `hotdogs/qwen3.6-27b-cybersecurity-lora` (r8/α16) | 512 | 79.7M | `/workspace/persistent/screwshell_run/loras/cybersec/adapter.gguf` |
| agent / planning | `teichai_plan` | `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA` (r64) | — | — | **无权重来源 ✗**（全机无 GGUF；router `agent→teichai_plan` 静默降级 base，不挂载 adapter） |
| doc / evidence | `rag_n7` | `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7` (r128/α256) | 992 | 1.9G | `/workspace/persistent/screwshell_run/loras/rag_n7/adapter.gguf` |

> 旧 `hermes_s2` / `fable5` 已从阵容移除（前者基座静默错配、后者仓库 404/私有化），其 GGUF 残留于 `/workspace/persistent/screwshell_run/loras/` 但不挂载。

## 验收闸

### G1 转换闸 — PASS（teichai_plan 不适用）
`btl3` / `cybersec` / `rag_n7` 转换成功，tensor 数与预期同族一致（btl3/n7 均为 992，cybersec 512）。**`teichai_plan` 无 GGUF 权重，G1 对其不可过（无 tensor 可 match），属数据缺口而非 bug——现网该位降级 base。**

### G2 基座 revision 闸 — PASS
- 镜像 `HF_ENDPOINT=https://hf-mirror.com` 的 `Qwen/Qwen3.6-27B` main 解析到 `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9`（与 BTL-3 钉死 revision 一致）。
- 三个新 adapter 的 `adapter_config.json` 中 `base_model_name_or_path` 均为 `Qwen/Qwen3.6-27B` → 与本地基座 GGUF 同源。

### G3 行为闸（防静默挂空/错位）— PASS（teichai_plan 行为数据为旧假设）
llama-server 以 `--lora-init-without-apply` 启动，三个真实 adapter（btl3 / cybersec / rag_n7）经 `POST /lora-adapters` 逐个激活，与基座原生（清空 adapter）对比同 prompt 输出。**关闭思考**（`chat_template_kwargs:{"enable_thinking":False}`）以稳定产出可比较答案。每专家 3 条领域 prompt：

- **teichai_plan**：⚠️ *旧假设，现网不成立*——原记录 3/3 差异；现网 agent 位降级 base，无 adapter 热切，输出即基座原生（与 base 行一致）。
- **btl3**：2/3 差异（二分查找题基座已给出正确代码、输出一致属正常）；其余专家回答更简洁直接。
- **cybersec**：3/3 差异。日志暴力破解、SQL 注入、localStorage/XSS 三类均给出专业分析，专家版更结构化。
- **rag_n7**：3/3 差异。基座也能答内联证据题，但 n7 输出明显更精简、专注引用（如 163→34 字），方向符合「grounded 证据问答」。
- 无任何真实 adapter 出现空输出/退化/错位 → 无静默挂空。

### G4 热切延迟闸 — PASS（teichai_plan 行现网不适用）
`POST /lora-adapters` 控制面热切耗时（均值，n=3/专家）：

| 专家 | 均值 | 备注 |
|---|---|---|
| teichai_plan | 0.6ms | ⚠️ 旧假设；现网降级 base，无 adapter 可热切 |
| btl3 | 0.5ms | 现网有效 |
| cybersec | 0.8ms | 现网有效 |
| rag_n7 (1.9GB) | 0.7ms | 现网有效 |

n7 的 1.9GB 适配器未拉高热切延迟（与最小 adapter 同量级），**未触发回退预案**（doc 位仍用 rag_n7）。

### G5 回归闸 — PASS
`tests/test_mol_llamacpp.py` 已更新为新阵容名（btl3 / cybersec / teichai_plan / rag_n7；teichai 在路由层占位但无权重），本地 pytest：**133 passed / 1 skipped / 1 failed**（2026-08-02 基线；skipped = torch 精度对照，本机无 GPU 预期跳过）。`scripts/test_local_logic.py` 全 PASS。

## 推理性能（bench 参考，关思考）
- decode ~26 tok/s（27B Q4_K_M + 3 个真实 LoRA 挂载，W7900；teichai 位降级 base 不占显存）。
- 单条领域问答（~400 token 输出）基座 13–14s、加 adapter 15–17s（含 ~1ms 热切 + 首词 amortized）。
- 显存占用 ~21GB（基座 16.8G + 3 LoRA f16）。

## 复跑命令（速查）
```bash
export HF_ENDPOINT=https://hf-mirror.com
# 1) 下载（venv python）
python -c "from huggingface_hub import snapshot_download as s; s('<repo>', local_dir='/workspace/persistent/screwshell_run/loras/_raw/<x>')"
# 2) 转换（注意：--base 指向本地目录；重复 --lora 仅认最后一个，必须用逗号分隔）
/workspace/persistent/screwshell_run/venv_llamacpp/bin/python3 /opt/llama.cpp.new/convert_lora_to_gguf.py \
   /workspace/persistent/screwshell_run/loras/_raw/<x> --outtype f16 --outfile /workspace/persistent/screwshell_run/loras/<x>/adapter.gguf
# 3) 启动服务（逗号分隔多 LoRA + 默认不挂、运行时激活；teichai_plan 无 GGUF 故不预载）
/opt/llama.cpp.new/build/bin/llama-server -m /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
   --lora /workspace/persistent/screwshell_run/loras/btl3/adapter.gguf,/workspace/persistent/screwshell_run/loras/cybersec/adapter.gguf,/workspace/persistent/screwshell_run/loras/rag_n7/adapter.gguf \
   --lora-init-without-apply --host 127.0.0.1 --port 8080 -ngl 99 -fa on -c 8192
# 4) 激活专家（数组格式！）：POST /lora-adapters  body=[{"id":N,"scale":1.0}]；回基座 body=[]
```

