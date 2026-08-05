# Radeon Cloud 当前部署记录

## 已完成

- Template：`Accident Rights Agent - Radeon ROCm`
- Container：
  `vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0`
- Deploy Type：`Notebook (Jupyter / OpenCode)`
- SSH Access：已启用
- Legacy Workspace Mode：`SSD + legacy replication`
- Model Directory：`None`
- 实例：已启动并通过 SSH 接管

## 持久化目录

实例内实际发现：

- `/workspace`：约 98 GB SSD scratch；
- `/persistent`：100 GB NFS/PVC；
- `/workspace/persistent -> /persistent`；
- `/workspace/legacy-workspace`：同一复制存储。

因此项目与模型固定放置在：

```text
/persistent/accident-rights-agent
/persistent/models/Qwen3-VL-8B-Instruct
```

持久性 marker：

```text
/persistent/.accident-rights-agent-persistence-marker-20260728
```

## 运行时

- Python：`/opt/venv/bin/python`
- vLLM：`/opt/venv/bin/vllm`
- 本地端点：`http://127.0.0.1:8000/v1`
- 当前 PID：记录在项目的 `artifacts/vllm.pid`
- 当前日志：项目的 `artifacts/vllm-baseline.log`

实例内的 `sshd` 是在 Jupyter Terminal 中手动启动的。实例重建后，如 SSH
端口拒绝连接，需要再次确认 `/usr/sbin/sshd` 已运行。

## 停止实例前

1. 确认项目、模型和必要报告都位于 `/persistent`；
2. 下载需要提交的脱敏报告；
3. 不删除持久化卷；
4. 停止实例会中断本地 vLLM，但不应删除上述持久化目录。
