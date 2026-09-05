# LoRA → GGUF 转换 & 验收闸（G1–G5）结果

> 执行环境：远程 GPU 实例 `root@36.150.116.206 -p 31033`（W7900 / ROCm 7.2.4 / 51.5GB VRAM）
> 基座：`/persistent/models/Qwen3.6-27B-Q4_K_M.gguf`（16.8GB，源 revision `6a9e13bd…`，HF 镜像 main 一致）
> 转换工具：`/persistent/llama.cpp`（patched，已编译 `build/bin/llama-server`）+ `/persistent/venv_llamacpp`
> 执行时间：2026-07-28（实例时区 UTC）
> 配套脚本：`/persistent/g3_validate.py`（G3/G4 验证）、日志 `/persistent/g3_result.log`

## T1 转换结果（safetensors → GGUF，f16）

| 阵容位 | adapter 名 | HF 仓库 | tensor 数 | 大小 | GGUF 路径 |
|---|---|---|---|---|---|
| tool / code | `btl3` | `badtheorylabs/BTL-3` (r32/α64) | 992 | 466.9M | `/persistent/loras/btl3/adapter.gguf` |
| security (新增) | `cybersec` | `hotdogs/qwen3.6-27b-cybersecurity-lora` (r8/α16) | 512 | 79.7M | `/persistent/loras/cybersec/adapter.gguf` |
| agent / planning | `teichai_fable5_plan` | `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA` (r64) | 992 | 934M | `/persistent/loras/teichai_fable5_plan/adapter.gguf`（已存在） |
| doc / evidence | `rag_n7` | `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7` (r128/α256) | 992 | 1.9G | `/persistent/loras/n7/adapter.gguf` |

> 旧 `hermes_s2` / `fable5` 已从阵容移除（前者基座静默错配、后者仓库 404/私有化），其 GGUF 残留于 `/persistent/loras/` 但不挂载。

## 验收闸

### G1 转换闸 — PASS
所有 adapter 转换成功，tensor 数与预期同族一致（teichai/btl3/n7 均为 992，cybersec 512）。

### G2 基座 revision 闸 — PASS
- 镜像 `HF_ENDPOINT=https://hf-mirror.com` 的 `Qwen/Qwen3.6-27B` main 解析到 `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9`（与 BTL-3 钉死 revision 一致）。
- 三个新 adapter 的 `adapter_config.json` 中 `base_model_name_or_path` 均为 `Qwen/Qwen3.6-27B` → 与本地基座 GGUF 同源。

### G3 行为闸（防静默挂空/错位）— PASS
llama-server 以 `--lora-init-without-apply` 启动，四种 adapter 经 `POST /lora-adapters` 逐个激活，与基座原生（清空 adapter）对比同 prompt 输出。**关闭思考**（`chat_template_kwargs:{"enable_thinking":False}`）以稳定产出可比较答案。每专家 3 条领域 prompt：

- **teichai_fable5_plan**：3/3 差异。专家方案维度更全（雪崩归因补全「高并发+缺失熔断+依赖链脆弱」；调查维度补「组织内部能力」）。
- **btl3**：2/3 差异（二分查找题基座已给出正确代码、输出一致属正常）；其余专家回答更简洁直接。
- **cybersec**：3/3 差异。日志暴力破解、SQL 注入、localStorage/XSS 三类均给出专业分析，专家版更结构化。
- **rag_n7**：3/3 差异。基座也能答内联证据题，但 n7 输出明显更精简、专注引用（如 163→34 字），方向符合「grounded 证据问答」。
- 无任何 adapter 出现空输出/退化/错位 → 无静默挂空。

### G4 热切延迟闸 — PASS
`POST /lora-adapters` 控制面热切耗时（均值，n=3/专家）：

| 专家 | 均值 |
|---|---|
| teichai_fable5_plan | 0.6ms |
| btl3 | 0.5ms |
| cybersec | 0.8ms |
| rag_n7 (1.9GB) | 0.7ms |

n7 的 1.9GB 适配器未拉高热切延迟（与最小 adapter 同量级），**未触发回退预案**（doc 位仍用 rag_n7）。

### G5 回归闸 — PASS
`tests/test_mol_llamacpp.py` 已更新为新阵容名（btl3 / cybersec / teichai_fable5_plan / rag_n7），本地 pytest：**7 passed / 1 skipped**（skip = torch 精度对照，本机无 GPU 预期跳过）。`scripts/test_local_logic.py` 全 PASS。

## 推理性能（bench 参考，关思考）
- decode ~26 tok/s（27B Q4_K_M + 4 LoRA 挂载，W7900）。
- 单条领域问答（~400 token 输出）基座 13–14s、加 adapter 15–17s（含 ~1ms 热切 + 首词 amortized）。
- 显存占用 ~21GB（基座 16.8G + 4 LoRA f16）。

## 复跑命令（速查）
```bash
export HF_ENDPOINT=https://hf-mirror.com
# 1) 下载（venv python）
python -c "from huggingface_hub import snapshot_download as s; s('<repo>', local_dir='/persistent/loras/_raw/<x>')"
# 2) 转换（注意：--base 指向本地目录；重复 --lora 仅认最后一个，必须用逗号分隔）
/persistent/venv_llamacpp/bin/python3 /persistent/llama.cpp/convert_lora_to_gguf.py \
   /persistent/loras/_raw/<x> --outtype f16 --outfile /persistent/loras/<x>/adapter.gguf
# 3) 启动服务（逗号分隔多 LoRA + 默认不挂、运行时激活）
/persistent/llama.cpp/build/bin/llama-server -m /persistent/models/Qwen3.6-27B-Q4_K_M.gguf \
   --lora /persistent/loras/teichai_fable5_plan/adapter.gguf,/persistent/loras/btl3/adapter.gguf,/persistent/loras/cybersec/adapter.gguf,/persistent/loras/n7/adapter.gguf \
   --lora-init-without-apply --host 127.0.0.1 --port 8080 -ngl 99 -fa on -c 8192
# 4) 激活专家（数组格式！）：POST /lora-adapters  body=[{"id":N,"scale":1.0}]；回基座 body=[]
```
