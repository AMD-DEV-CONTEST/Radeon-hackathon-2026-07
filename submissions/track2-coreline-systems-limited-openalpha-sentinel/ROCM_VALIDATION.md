# Radeon Cloud 验证与队友交接

验证日期：2026-07-17

## 当前结论

- Radeon Cloud 的 ROCm/HIP 环境可用。
- 固定 commit 的 `ROCm/llama.cpp` 已针对 `gfx1100` 编译成功。
- Qwen3-8B Q4_K_M 已从 ModelScope 下载并通过固定 SHA-256 校验。
- 保存的 `llama-bench` 结果记录了 `ROCm` 后端与 `-ngl 99` 配置；独立详细加载轨迹进一步证明该模型连同输出层实际 `offloaded 37/37 layers to GPU`。
- 固定 `llama-bench` 快照已完成：Prompt processing `3033.77 +/- 154.27 tok/s`，生成 `93.47 +/- 0.08 tok/s`。
- Radeon 主机 Python 3.12.3 的早期保存报告为 `35 passed`；当前本地套件为 `56 passed`，语句覆盖率 `81%`。
- 已分别保存真实远程 CLI 和回环 HTTP 200 问答，两者均返回 `backend=llama.cpp-rocm` 与固定 commit 的行级引用。
- 已完成真实进程重启验证：模型、API、worker 的 PID 均变化，重启后健康检查通过，重复 seed 未产生重复卡片或通知，SQLite 完整性及外键检查通过。
- 24 小时 soak、TTFT 分位数和 CPU/Radeon 优化对照仍未完成，不能把它们描述为已完成。

## 实测环境

| 项目 | 结果 |
|---|---|
| 实例 | 一次性 Radeon Cloud Notebook；公开证据已移除临时实例与设备唯一标识 |
| 镜像 | `AMD OneClick Base / ROCm 7.2.1 / Python 3.12` |
| 系统 | Ubuntu 24.04.4 LTS，Linux 6.8.0-79 |
| GPU | 1 张 AMD Radeon，`gfx1100`；平台未提供可靠商业型号 |
| 显存 | `rocm-smi` 报告 `51,522,830,336` bytes；`llama.cpp` 初始化日志以 MiB 显示同一总量 `49,136 MiB` |
| HIP | `7.2.53211-e1a6bc5663` |
| 系统内存 | 503 GiB |
| CPU | 128 vCPU，AMD EPYC 9334 |
| `/workspace` | 98 GiB 文件系统；部署完成后约 87 GiB 可用 |
| 服务模式 | systemd offline，使用 PID + 启动时间校验 + 独立日志 |

## 固定运行时

```text
llama.cpp repository: https://github.com/ROCm/llama.cpp
llama.cpp commit:     1b99711a5f2582ec99686eb7958844749c223cf5
Model repository:     Qwen/Qwen3-8B-GGUF
Model file:           Qwen3-8B-Q4_K_M.gguf
Model license:        Apache-2.0
Model SHA-256:        d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785
Context:              8192
GPU-layer argument:   -ngl 99
Verified assignment:  37/37 layers offloaded to ROCm0
Flash attention:      on
```

构建参数：

```text
GGML_HIP=ON
AMDGPU_TARGETS=gfx1100
CMAKE_BUILD_TYPE=Release
LLAMA_CURL=OFF
```

服务器能访问 ModelScope，但访问 Hugging Face 超时，访问 GitHub 的部分 TLS 链路会被平台网络中间层影响。部署脚本不会使用 `curl -k` 或关闭 Git TLS 校验；优先准备干净的固定 Git checkout，Git 不可用时改用 SHA-256 为 `65536629d57a7b7f9ec81a323311dd497e09a5d8b981225c6c56feda63cefde4` 的官方 commit codeload 归档。模型从以下 ModelScope 官方镜像断点续传：

```text
https://modelscope.cn/models/Qwen/Qwen3-8B-GGUF/resolve/master/Qwen3-8B-Q4_K_M.gguf
```

## 部署与访问

真实连接保存在被 Git 忽略的 `.env.server`。当前或新实例只需更新 SSH host/port：

```bash
cp .env.example .env.server
chmod 600 .env.server
./scripts/server_deploy.sh
./scripts/server_cli.sh doctor
./scripts/server_cli.sh seed
./scripts/server_tunnel.sh
```

浏览器通过 SSH 隧道打开 `http://127.0.0.1:8765`。模型与 API 均只监听服务器的 `127.0.0.1`。

完整的 SSH 初始化、换机和备份恢复流程见 [docs/README.md](docs/README.md)。

## 已保存的应用响应

最终证据分别保存了完整的远程 CLI 命令/响应与回环 HTTP POST 请求、payload、HTTP 200 状态和响应。两条路径均呈现以下链路：

```text
问题 -> 本地混合检索 -> Agent 计划 -> llama.cpp ROCm -> 引用标签校验 -> 带来源回答
```

`openalpha doctor` 返回：

```json
{
  "python": "3.12.3",
  "fts5": true,
  "llm_backend": "llama.cpp-rocm",
  "offline": false
}
```

CLI 和 HTTP 响应均返回 `backend: llama.cpp-rocm`，并引用固定 commit `3aba9fc095ab77157ef225a6c5f77dfa5562ffa9` 中 `Daily Equity Mean Reversion` 的第 8-28 行。运行时日志中的单点 `rocm-smi` 快照记录整张 GPU 使用率为 `63%`、已用显存 `6,642,937,856 bytes`；它不是模型进程驻留值，也不是活动峰值显存轨迹。

## 基准快照

命令：

```bash
cd /workspace/openalpha-sentinel
./scripts/benchmark_rocm.sh
```

| 测试 | 结果 |
|---|---:|
| `llama-bench pp512`, 5 次，ROCm，`ngl=99` | `3033.77 +/- 154.27 tok/s` |
| `llama-bench tg256`, 5 次，ROCm，`ngl=99` | `93.47 +/- 0.08 tok/s` |
| 应用级请求 | 15/15 完成 |
| 应用级混合请求平均延迟 | 4.842 s |
| 应用级混合请求中位延迟 | 5.506 s |
| 应用级混合请求范围 | 0.005-10.180 s |

应用级数字混合了确定性工具路径与 LLM 路径，只作为端到端 smoke benchmark，不能冒充纯 LLM TTFT 或同配置优化对照。

## 已保存证据

- `docs/submission/generated/rocm-benchmark-20260717T051324Z.txt`：干净部署清单、系统/ROCm/模型哈希、原始 `llama-bench` 与应用级结果。
- `docs/submission/generated/rocm-test-run-20260717T050554Z.txt` 与对应 XML：Radeon 主机 35 项测试。
- `docs/submission/generated/rocm-cli-rag-20260717T050851Z.txt`：远程 CLI 请求、`llama.cpp-rocm` 响应及固定 commit 引用。
- `docs/submission/generated/rocm-http-rag-20260717T050918Z.txt`：回环 HTTP payload、HTTP 200 与对应响应。
- `docs/submission/generated/rocm-restart-trace-20260717T051301Z.txt`：停止/启动前后 PID、健康检查、重复 seed 与数据库校验。
- `docs/submission/generated/rocm-llama-runtime-20260717T051305Z.log`：服务命令、加载/监听、请求 timing 与采集时 GPU 全局快照；不证明实际 offload 层数或峰值显存。
- `docs/submission/generated/rocm-offload-validation-20260717T152430Z.txt`：绑定干净部署 commit `25129cdd...` 的详细设备/模型加载轨迹，证明 `ROCm0` 上实际 offload `37/37` 层；不属于峰值显存或延迟测试。
- `20260717T031413Z`、`0318Z` 与 `0320Z` 文件保留为早期遗留快照，不作为最终传输或重启证据。
- `data/server-backups/` 下的本地私有状态备份，不提交 Git。

## 仍待完成

1. 用机器可读逐请求计时采集 TTFT P50/P95 与真实峰值显存。
2. 用相同模型、Prompt、上下文与数据集完成 CPU、Radeon baseline、Radeon optimized 对照。
3. 完成 Radeon LLM 结构化抽取质量集与 citation support 人工评估。
4. 录制包含真实 GPU 活动、应用请求和最终输出的 3-5 分钟演示视频。
5. 若时间允许，完成可选的 24 小时 soak；未完成时继续明确标注。

不得用本次 smoke benchmark 填写尚未测量的对照提升、TTFT 或 24 小时稳定性。
