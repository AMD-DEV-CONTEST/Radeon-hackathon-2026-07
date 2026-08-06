# AMD Radeon GPU 实跑证据

验证时间：2026-08-06（北京时间）

## 环境

- Radeon Cloud 实例：`u-14615-b0cebd0b`
- 模板：`Solo Worker OS Debug`
- 容器：ROCm vLLM 开发镜像
- GPU vendor：`Advanced Micro Devices, Inc. [AMD/ATI]`
- ROCm architecture：`gfx1100`
- 推理框架：vLLM `0.16.1.dev0`
- 模型：`Qwen/Qwen3-4B`
- 上下文长度：4096

## 已验证结果

1. `rocm-smi` 在 vLLM 在线时显示 VRAM 分配约 51%。
2. 远端进程包含 `vllm serve Qwen/Qwen3-4B` 与 `VLLM::EngineCore`。
3. `http://127.0.0.1:8000/v1/models` 返回 `Qwen/Qwen3-4B`，`owned_by` 为 `vllm`。
4. Solo Worker OS 的 `/api/local-llm/status` 返回：

```json
{
  "provider": "local",
  "isLocal": true,
  "configuredModel": "Qwen/Qwen3-4B",
  "reachable": true,
  "servedModels": ["Qwen/Qwen3-4B"],
  "error": null
}
```

5. vLLM 日志记录了来自 Solo Worker OS 的多次请求：

```text
POST /v1/chat/completions HTTP/1.1 200 OK
```

6. 端到端普通对话成功。
7. 端到端工具调用成功：Agent 调用 `create_project`，并在 Demo Mode 中创建项目。

## vLLM 启动参数

```bash
vllm serve Qwen/Qwen3-4B \
  --host 0.0.0.0 \
  --port 8000 \
  --trust-remote-code \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.5 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

## 复核命令

```bash
date -Is
rocm-smi --showproductname --showmemuse --showuse
ps -ww -eo pid,stat,etime,rss,cmd | grep -E '[v]llm serve|EngineCore'
curl -sS http://127.0.0.1:8000/v1/models
grep 'POST /v1/chat/completions' /workspace/vllm.log | grep '200 OK' | tail -n 5
```

## 说明

公网隧道仅用于录屏期间把本机 Solo Worker OS 连接到参赛者独占的 Radeon Cloud vLLM 实例。录屏完成后应立即执行 `rc-tunnel stop`。临时隧道 URL 不写入提交文档。
